"""Pluggable weather/air-quality data providers.

Every provider adapter normalizes its response into the exact shape
Open-Meteo returns (WMO weathercodes, same field names), so the rest of the
app - evaluate(), build_daily_digest(), describe_weathercode() - never
needs to know which provider is active.

Honest limitation: only Open-Meteo's Air Quality API provides a real,
directly-comparable "dust" concentration and a numeric 0-500 US AQI. The
three API-key providers below give raw PM10/PM2.5 concentrations (so those
threshold checks work everywhere), but not a literal "dust" metric or a
0-500 US AQI - their own air-quality indices use different scales, so
those two fields come back as None (and are skipped, not faked) for
non-Open-Meteo providers.

Sunrise/sunset: OpenWeatherMap's free forecast endpoint only gives one
sunrise/sunset pair (today's, at request time), not a per-day value for
tomorrow too. Rather than approximate, fetch_weather() transparently makes
one extra (free, keyless) call to Open-Meteo's daily sunrise/sunset fields
whenever the active provider's daily data doesn't already include them, and
fills both days in from that single consistent source.
"""

import logging

import requests

log = logging.getLogger("weatherman")

OPEN_METEO_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
OWM_AIR_POLLUTION_URL = "https://api.openweathermap.org/data/2.5/air_pollution"
WEATHERAPI_FORECAST_URL = "https://api.weatherapi.com/v1/forecast.json"
TOMORROWIO_TIMELINES_URL = "https://api.tomorrow.io/v4/timelines"

# Roughly worst-to-mildest, used to pick one representative condition for a
# day when a provider only gives hourly/3-hourly data and we have to bucket
# it into daily ourselves.
_WMO_SEVERITY = [
    99, 96, 95,             # thunderstorm
    82, 81, 80,             # violent/moderate/slight rain showers
    75, 73, 71, 86, 85, 77,  # snow
    67, 66, 65, 63, 61,      # freezing rain, rain
    57, 56, 55, 53, 51,      # drizzle
    48, 45,                  # fog
    3, 2, 1, 0,               # cloud cover
]


def _most_severe_code(codes):
    present = set(codes)
    for code in _WMO_SEVERITY:
        if code in present:
            return code
    return codes[0] if codes else 0


def _bucket_daily_from_hourly(dates, temps, precip_probs, weathercodes):
    """Group hourly/3-hourly data by calendar date into Open-Meteo-shaped
    daily arrays (max/min temp, max precip probability, most-severe code)."""
    by_date = {}
    for date, temp, prob, code in zip(dates, temps, precip_probs, weathercodes):
        day = date[:10]
        bucket = by_date.setdefault(day, {"temps": [], "probs": [], "codes": []})
        if temp is not None:
            bucket["temps"].append(temp)
        if prob is not None:
            bucket["probs"].append(prob)
        bucket["codes"].append(code)

    days = sorted(by_date)[:2]
    return {
        "time": days,
        "weathercode": [_most_severe_code(by_date[d]["codes"]) for d in days],
        "temperature_2m_max": [max(by_date[d]["temps"]) if by_date[d]["temps"] else None for d in days],
        "temperature_2m_min": [min(by_date[d]["temps"]) if by_date[d]["temps"] else None for d in days],
        "precipitation_probability_max": [max(by_date[d]["probs"]) if by_date[d]["probs"] else None for d in days],
    }


def _extract_hhmm(value):
    """Normalize a provider's sunrise/sunset value into 24h 'HH:MM'.

    Accepts Open-Meteo/Tomorrow.io-style ISO strings ('...T06:13...') or
    WeatherAPI-style 12-hour strings ('6:13 AM')."""
    if not value:
        return None
    if "T" in value:
        return value.split("T")[1][:5]
    import datetime as _datetime

    cleaned = value.strip().upper().replace(".", "")
    for fmt in ("%I:%M %p", "%I:%M%p"):
        try:
            return _datetime.datetime.strptime(cleaned, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return None


def _fetch_sunrise_sunset_open_meteo(cfg):
    params = {
        "latitude": cfg["location"]["latitude"],
        "longitude": cfg["location"]["longitude"],
        "timezone": cfg["location"].get("timezone", "auto"),
        "daily": "sunrise,sunset",
        "forecast_days": 2,
    }
    resp = requests.get(OPEN_METEO_WEATHER_URL, params=params, timeout=20)
    resp.raise_for_status()
    daily = resp.json().get("daily", {})
    return {
        "sunrise": [_extract_hhmm(v) for v in daily.get("sunrise", [])],
        "sunset": [_extract_hhmm(v) for v in daily.get("sunset", [])],
    }


def _empty_aq_hourly(times):
    n = len(times)
    return {
        "time": times,
        "pm10": [None] * n,
        "pm2_5": [None] * n,
        "dust": [None] * n,
        "us_aqi": [None] * n,
    }


# --- Open-Meteo (default, no API key) ---------------------------------

def _fetch_weather_open_meteo(cfg):
    units = cfg.get("units", "celsius")
    params = {
        "latitude": cfg["location"]["latitude"],
        "longitude": cfg["location"]["longitude"],
        "timezone": cfg["location"].get("timezone", "auto"),
        "hourly": "temperature_2m,precipitation_probability,precipitation,weathercode,windspeed_10m",
        "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,sunrise,sunset",
        "forecast_days": 2,
        "temperature_unit": units,
        "windspeed_unit": "mph" if units == "fahrenheit" else "kmh",
    }
    resp = requests.get(OPEN_METEO_WEATHER_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    daily = data.get("daily", {})
    if "sunrise" in daily:
        daily["sunrise"] = [_extract_hhmm(v) for v in daily["sunrise"]]
    if "sunset" in daily:
        daily["sunset"] = [_extract_hhmm(v) for v in daily["sunset"]]
    return data


def _fetch_air_quality_open_meteo(cfg):
    params = {
        "latitude": cfg["location"]["latitude"],
        "longitude": cfg["location"]["longitude"],
        "hourly": "pm10,pm2_5,dust,us_aqi",
        "forecast_days": 2,
    }
    resp = requests.get(OPEN_METEO_AIR_QUALITY_URL, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


# --- OpenWeatherMap -----------------------------------------------------
# Uses the free "5 day / 3 hour forecast" and "Air Pollution" endpoints
# (data/2.5/*), not One Call 3.0, which requires adding a billing method
# even on its free tier. These 2.5 endpoints work with any plain API key.

_OWM_CODE_TO_WMO = {
    200: 95, 201: 95, 202: 95, 210: 95, 211: 95, 212: 95, 221: 95, 230: 95, 231: 95, 232: 95,
    300: 51, 301: 53, 302: 55, 310: 51, 311: 53, 312: 55, 313: 55, 314: 55, 321: 53,
    500: 61, 501: 63, 502: 65, 503: 65, 504: 65, 511: 66, 520: 80, 521: 81, 522: 82, 531: 82,
    600: 71, 601: 73, 602: 75, 611: 66, 612: 66, 613: 67, 615: 66, 616: 67, 620: 85, 621: 86, 622: 86,
    701: 45, 711: 45, 721: 45, 731: 45, 741: 45, 751: 45, 761: 45, 762: 45, 771: 82, 781: 99,
    800: 0, 801: 1, 802: 2, 803: 3, 804: 3,
}


def _fetch_weather_openweathermap(cfg):
    units = cfg.get("units", "celsius")
    api_key = cfg["weather_provider"]["api_key"]
    params = {
        "lat": cfg["location"]["latitude"],
        "lon": cfg["location"]["longitude"],
        "appid": api_key,
        "units": "imperial" if units == "fahrenheit" else "metric",
    }
    resp = requests.get(OWM_FORECAST_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    times, temps, probs, codes, winds = [], [], [], [], []
    for entry in data.get("list", []):
        times.append(entry["dt_txt"].replace(" ", "T"))
        temps.append(entry["main"]["temp"])
        probs.append(round((entry.get("pop") or 0) * 100))
        weather = entry.get("weather") or [{}]
        codes.append(_OWM_CODE_TO_WMO.get(weather[0].get("id"), 3))
        winds.append(entry.get("wind", {}).get("speed", 0))

    hourly = {
        "time": times,
        "temperature_2m": temps,
        "precipitation_probability": probs,
        "precipitation": [0] * len(times),  # not directly provided per-step in a uniform field
        "weathercode": codes,
        "windspeed_10m": winds,
    }
    daily = _bucket_daily_from_hourly(times, temps, probs, codes)
    return {
        "timezone": cfg["location"].get("timezone", "UTC"),
        "hourly": hourly,
        "daily": daily,
    }


def _fetch_air_quality_openweathermap(cfg):
    api_key = cfg["weather_provider"]["api_key"]
    params = {
        "lat": cfg["location"]["latitude"],
        "lon": cfg["location"]["longitude"],
        "appid": api_key,
    }
    resp = requests.get(OWM_AIR_POLLUTION_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    times, pm10, pm2_5 = [], [], []
    for entry in data.get("list", []):
        times.append(entry["dt"])
        components = entry.get("components", {})
        pm10.append(components.get("pm10"))
        pm2_5.append(components.get("pm2_5"))

    n = len(times)
    return {
        "hourly": {
            "time": times,
            "pm10": pm10,
            "pm2_5": pm2_5,
            "dust": [None] * n,
            "us_aqi": [None] * n,  # OWM's own index is 1-5, not a comparable 0-500 scale
        }
    }


# --- WeatherAPI.com -------------------------------------------------------

_WEATHERAPI_CODE_TO_WMO = {
    1000: 0, 1003: 2, 1006: 3, 1009: 3,
    1030: 45, 1135: 45, 1147: 45,
    1063: 51, 1150: 51, 1153: 51, 1168: 56, 1171: 57,
    1180: 61, 1183: 61, 1186: 63, 1189: 63, 1192: 65, 1195: 65,
    1198: 66, 1201: 67, 1204: 66, 1207: 67,
    1066: 71, 1114: 75, 1117: 75, 1210: 71, 1213: 71, 1216: 73, 1219: 73,
    1222: 75, 1225: 75, 1237: 77, 1261: 77, 1264: 77,
    1240: 80, 1243: 81, 1246: 82, 1249: 66, 1252: 67, 1255: 85, 1258: 86,
    1069: 66, 1072: 56,
    1087: 95, 1273: 95, 1276: 95, 1279: 96, 1282: 96,
}


def _fetch_weather_weatherapi(cfg):
    units = cfg.get("units", "celsius")
    api_key = cfg["weather_provider"]["api_key"]
    params = {
        "key": api_key,
        "q": f"{cfg['location']['latitude']},{cfg['location']['longitude']}",
        "days": 2,
        "aqi": "yes",
        "alerts": "no",
    }
    resp = requests.get(WEATHERAPI_FORECAST_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    def c_to_unit(celsius):
        return celsius * 9 / 5 + 32 if units == "fahrenheit" else celsius

    def kph_to_unit(kph):
        return kph * 0.621371 if units == "fahrenheit" else kph

    forecast_days = data.get("forecast", {}).get("forecastday", [])

    hourly_time, hourly_temp, hourly_prob, hourly_precip, hourly_code, hourly_wind = [], [], [], [], [], []
    daily_time, daily_code, daily_max, daily_min, daily_prob = [], [], [], [], []
    daily_sunrise, daily_sunset = [], []

    for day in forecast_days:
        daily_time.append(day["date"])
        day_info = day["day"]
        daily_max.append(c_to_unit(day_info["maxtemp_c"]))
        daily_min.append(c_to_unit(day_info["mintemp_c"]))
        daily_prob.append(day_info.get("daily_chance_of_rain", 0))
        daily_code.append(_WEATHERAPI_CODE_TO_WMO.get(day_info["condition"]["code"], 3))
        astro = day.get("astro", {})
        daily_sunrise.append(_extract_hhmm(astro.get("sunrise")))
        daily_sunset.append(_extract_hhmm(astro.get("sunset")))

        for hour in day.get("hour", []):
            hourly_time.append(hour["time"].replace(" ", "T"))
            hourly_temp.append(c_to_unit(hour["temp_c"]))
            hourly_prob.append(hour.get("chance_of_rain", 0))
            hourly_precip.append(hour.get("precip_mm", 0))
            hourly_code.append(_WEATHERAPI_CODE_TO_WMO.get(hour["condition"]["code"], 3))
            hourly_wind.append(kph_to_unit(hour.get("wind_kph", 0)))

    return {
        "timezone": data.get("location", {}).get("tz_id") or cfg["location"].get("timezone", "UTC"),
        "hourly": {
            "time": hourly_time,
            "temperature_2m": hourly_temp,
            "precipitation_probability": hourly_prob,
            "precipitation": hourly_precip,
            "weathercode": hourly_code,
            "windspeed_10m": hourly_wind,
        },
        "daily": {
            "time": daily_time,
            "weathercode": daily_code,
            "temperature_2m_max": daily_max,
            "temperature_2m_min": daily_min,
            "precipitation_probability_max": daily_prob,
            "sunrise": daily_sunrise,
            "sunset": daily_sunset,
        },
    }


def _fetch_air_quality_weatherapi(cfg):
    api_key = cfg["weather_provider"]["api_key"]
    params = {
        "key": api_key,
        "q": f"{cfg['location']['latitude']},{cfg['location']['longitude']}",
        "days": 2,
        "aqi": "yes",
        "alerts": "no",
    }
    resp = requests.get(WEATHERAPI_FORECAST_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    times, pm10, pm2_5 = [], [], []
    for day in data.get("forecast", {}).get("forecastday", []):
        for hour in day.get("hour", []):
            times.append(hour["time"].replace(" ", "T"))
            aq = hour.get("air_quality", {})
            pm10.append(aq.get("pm10"))
            pm2_5.append(aq.get("pm2_5"))

    n = len(times)
    return {
        "hourly": {
            "time": times,
            "pm10": pm10,
            "pm2_5": pm2_5,
            "dust": [None] * n,
            "us_aqi": [None] * n,  # WeatherAPI gives a categorical us-epa-index (1-6), not 0-500
        }
    }


# --- Tomorrow.io ----------------------------------------------------------

_TOMORROWIO_CODE_TO_WMO = {
    1000: 0, 1100: 1, 1101: 2, 1102: 3, 1001: 3,
    2000: 45, 2100: 45,
    4000: 51, 4001: 61, 4200: 61, 4201: 65,
    5000: 71, 5001: 71, 5100: 71, 5101: 75,
    6000: 56, 6001: 66, 6200: 66, 6201: 67,
    7000: 77, 7101: 77, 7102: 77,
    8000: 95,
}


def _fetch_weather_tomorrowio(cfg):
    units = cfg.get("units", "celsius")
    api_key = cfg["weather_provider"]["api_key"]
    params = {
        "location": f"{cfg['location']['latitude']},{cfg['location']['longitude']}",
        "apikey": api_key,
        "units": "imperial" if units == "fahrenheit" else "metric",
        "timesteps": "1h,1d",
        "fields": "temperature,precipitationProbability,weatherCode,windSpeed,temperatureMax,temperatureMin,sunriseTime,sunsetTime",
    }
    resp = requests.get(TOMORROWIO_TIMELINES_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    timelines = {t["timestep"]: t["intervals"] for t in data["data"]["timelines"]}
    hourly_intervals = timelines.get("1h", [])[:48]
    daily_intervals = timelines.get("1d", [])[:2]

    hourly_time, hourly_temp, hourly_prob, hourly_code, hourly_wind = [], [], [], [], []
    for interval in hourly_intervals:
        values = interval["values"]
        hourly_time.append(interval["startTime"])
        hourly_temp.append(values.get("temperature"))
        hourly_prob.append(values.get("precipitationProbability", 0))
        hourly_code.append(_TOMORROWIO_CODE_TO_WMO.get(values.get("weatherCode"), 3))
        hourly_wind.append(values.get("windSpeed", 0))

    daily_time, daily_code, daily_max, daily_min, daily_prob = [], [], [], [], []
    daily_sunrise, daily_sunset = [], []
    for interval in daily_intervals:
        values = interval["values"]
        daily_time.append(interval["startTime"][:10])
        daily_code.append(_TOMORROWIO_CODE_TO_WMO.get(values.get("weatherCode"), 3))
        daily_max.append(values.get("temperatureMax"))
        daily_min.append(values.get("temperatureMin"))
        daily_prob.append(values.get("precipitationProbability", 0))
        daily_sunrise.append(_extract_hhmm(values.get("sunriseTime")))
        daily_sunset.append(_extract_hhmm(values.get("sunsetTime")))

    return {
        "timezone": cfg["location"].get("timezone", "UTC"),
        "hourly": {
            "time": hourly_time,
            "temperature_2m": hourly_temp,
            "precipitation_probability": hourly_prob,
            "precipitation": [0] * len(hourly_time),
            "weathercode": hourly_code,
            "windspeed_10m": hourly_wind,
        },
        "daily": {
            "time": daily_time,
            "weathercode": daily_code,
            "temperature_2m_max": daily_max,
            "temperature_2m_min": daily_min,
            "precipitation_probability_max": daily_prob,
            "sunrise": daily_sunrise,
            "sunset": daily_sunset,
        },
    }


def _fetch_air_quality_tomorrowio(cfg):
    api_key = cfg["weather_provider"]["api_key"]
    params = {
        "location": f"{cfg['location']['latitude']},{cfg['location']['longitude']}",
        "apikey": api_key,
        "timesteps": "1h",
        "fields": "particulateMatter10,particulateMatter25",
    }
    resp = requests.get(TOMORROWIO_TIMELINES_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    timelines = data["data"]["timelines"]
    intervals = timelines[0]["intervals"] if timelines else []

    times, pm10, pm2_5 = [], [], []
    for interval in intervals[:48]:
        values = interval["values"]
        times.append(interval["startTime"])
        pm10.append(values.get("particulateMatter10"))
        pm2_5.append(values.get("particulateMatter25"))

    n = len(times)
    return {
        "hourly": {
            "time": times,
            "pm10": pm10,
            "pm2_5": pm2_5,
            "dust": [None] * n,
            "us_aqi": [None] * n,  # Tomorrow.io gives a categorical epaIndex (1-6), not 0-500
        }
    }


# --- Registry / dispatch ---------------------------------------------------

PROVIDER_INFO = {
    "open-meteo": {
        "label": "Open-Meteo",
        "needs_api_key": False,
        "signup_url": None,
        "instructions": None,
    },
    "openweathermap": {
        "label": "OpenWeatherMap",
        "needs_api_key": True,
        "signup_url": "https://home.openweathermap.org/users/sign_up",
        "instructions": (
            "Sign up, then copy a key from the 'API keys' tab. Use a plain "
            "default key - no billing/credit card setup needed, since this "
            "only calls the free 5-day/3-hour forecast and Air Pollution "
            "endpoints, not the paid One Call 3.0 API. New keys can take up "
            "to ~2 hours to activate."
        ),
    },
    "weatherapi": {
        "label": "WeatherAPI.com",
        "needs_api_key": True,
        "signup_url": "https://www.weatherapi.com/signup.aspx",
        "instructions": "Sign up for the free plan; your API key is issued instantly, no billing required.",
    },
    "tomorrowio": {
        "label": "Tomorrow.io",
        "needs_api_key": True,
        "signup_url": "https://app.tomorrow.io/signup",
        "instructions": "Sign up for the free tier; your API key is issued instantly, no billing required.",
    },
}

_WEATHER_FETCHERS = {
    "open-meteo": _fetch_weather_open_meteo,
    "openweathermap": _fetch_weather_openweathermap,
    "weatherapi": _fetch_weather_weatherapi,
    "tomorrowio": _fetch_weather_tomorrowio,
}

_AIR_QUALITY_FETCHERS = {
    "open-meteo": _fetch_air_quality_open_meteo,
    "openweathermap": _fetch_air_quality_openweathermap,
    "weatherapi": _fetch_air_quality_weatherapi,
    "tomorrowio": _fetch_air_quality_tomorrowio,
}


def _provider_name(cfg):
    return (cfg.get("weather_provider") or {}).get("name", "open-meteo")


def _ensure_sunrise_sunset(cfg, data):
    """If the active provider's daily data is missing sunrise/sunset (only
    OpenWeatherMap's free endpoint lacks a real per-day value today), fill
    both days in from a single extra Open-Meteo call rather than mixing
    sources or approximating."""
    daily = data.get("daily") or {}
    sunrise = daily.get("sunrise")
    sunset = daily.get("sunset")
    has_valid = (
        sunrise and sunset
        and all(v is not None for v in sunrise)
        and all(v is not None for v in sunset)
    )
    if has_valid:
        return

    try:
        fallback = _fetch_sunrise_sunset_open_meteo(cfg)
    except requests.RequestException as e:
        log.warning("Could not fetch sunrise/sunset fallback from Open-Meteo: %s", e)
        return

    daily["sunrise"] = fallback["sunrise"]
    daily["sunset"] = fallback["sunset"]
    data["daily"] = daily


def fetch_weather(cfg):
    name = _provider_name(cfg)
    fetcher = _WEATHER_FETCHERS.get(name, _fetch_weather_open_meteo)
    data = fetcher(cfg)
    _ensure_sunrise_sunset(cfg, data)
    return data


def fetch_air_quality(cfg):
    name = _provider_name(cfg)
    fetcher = _AIR_QUALITY_FETCHERS.get(name, _fetch_air_quality_open_meteo)
    return fetcher(cfg)
