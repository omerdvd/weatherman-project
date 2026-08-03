#!/usr/bin/env python3
"""Interactive installer: prompts for location, units, and ntfy settings,
then writes config.yaml.

Run this once when installing the service:
    python3 setup.py
"""

import os
import sys
from pathlib import Path

import requests
import yaml

import providers
import scheduler
import timezones
from pluscode import PlusCodeError, resolve

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
CONFIG_PATH = Path(__file__).parent / "config.yaml"
EXAMPLE_PATH = Path(__file__).parent / "config.example.yaml"

DEFAULT_THRESHOLDS_CELSIUS = {
    "precipitation_probability_percent": 50,
    "precipitation_mm": 1.0,
    "thunderstorm": True,
    "temp_high_celsius": 35.0,
    "temp_low_celsius": 5.0,
    "wind_speed_kmh": 60.0,
    "pm10": 100.0,
    "pm2_5": 50.0,
    "us_aqi": 100,
    "dust": 50.0,
}

DISCLAIMER = """\
==============================================================================
 weatherman - weather & air quality monitor with ntfy alerts
==============================================================================
This software is provided "AS IS", without warranty of any kind, express or
implied, including but not limited to warranties of merchantability, fitness
for a particular purpose, and noninfringement. Use it at your own risk. The
authors accept no liability for missed, delayed, or incorrect alerts, or for
any damages arising from the use of this software. This is a personal
home-automation project, not a certified weather or safety system - do not
rely on it as your sole source of severe-weather or air-quality warnings.

Credits:
  Omer David (42729996+omerdvd@users.noreply.github.com)
  Claude (Anthropic) - https://claude.ai/code
==============================================================================

By continuing with this setup process, you agree to the above terms and
conditions.
"""


def prompt(msg, default=None):
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"{msg}{suffix}: ").strip()
    return val or default


def geocode_city(name):
    resp = requests.get(GEOCODING_URL, params={"name": name, "count": 1}, timeout=20)
    resp.raise_for_status()
    results = resp.json().get("results")
    if not results:
        return None
    return results[0]["latitude"], results[0]["longitude"]


def geocode_city_candidates(name, count=10):
    """Look up a city via Open-Meteo's geocoding API (GeoNames-backed, so it
    covers virtually every populated place worldwide, not just capitals).
    Each result includes a 'timezone' field directly, so it doubles as a
    timezone lookup with no separate database needed."""
    resp = requests.get(
        GEOCODING_URL,
        params={"name": name, "count": count, "language": "en", "format": "json"},
        timeout=20,
    )
    resp.raise_for_status()
    results = resp.json().get("results") or []
    return [r for r in results if r.get("timezone")]


def describe_geocode_result(result):
    parts = [result["name"]]
    admin1 = result.get("admin1")
    if admin1 and admin1 != result["name"]:
        parts.append(admin1)
    country = result.get("country")
    if country:
        parts.append(country)
    label = ", ".join(parts)
    population = result.get("population")
    if population:
        label += f" (pop. {population:,})"
    return label


# Common alternate names/abbreviations for countries whose Open-Meteo
# "country" field wouldn't otherwise substring-match them.
COUNTRY_ALIASES = {
    "usa": "united states",
    "us": "united states",
    "u.s.": "united states",
    "u.s.a.": "united states",
    "america": "united states",
    "uk": "united kingdom",
    "u.k.": "united kingdom",
    "britain": "united kingdom",
    "great britain": "united kingdom",
    "england": "united kingdom",
    "scotland": "united kingdom",
    "wales": "united kingdom",
    "uae": "united arab emirates",
    "south korea": "korea",
    "north korea": "korea",
    "russia": "russian federation",
    "vietnam": "viet nam",
    "laos": "lao people's democratic republic",
    "syria": "syrian arab republic",
    "iran": "iran, islamic republic of",
    "bolivia": "bolivia, plurinational state of",
    "venezuela": "venezuela, bolivarian republic of",
    "tanzania": "united republic of tanzania",
    "moldova": "republic of moldova",
    "czechia": "czech republic",
    "ivory coast": "cote d'ivoire",
    "cape verde": "cabo verde",
    "swaziland": "eswatini",
    "burma": "myanmar",
}


def _normalize_country(text):
    q = text.strip().lower()
    return COUNTRY_ALIASES.get(q, q)


def _country_matches(candidate, country_query):
    q = _normalize_country(country_query)
    country = _normalize_country(candidate.get("country") or "")
    code = (candidate.get("country_code") or "").strip().lower()
    if not q:
        return False
    return q == country or q == code or q in country or country in q


def _pick_location_from_geocode(city, country, candidates):
    """Filter geocoding candidates to the given country and let the user pick
    one. Returns (lat, lon) tuple, or None to signal 'ask again'."""
    matches = [c for c in candidates if _country_matches(c, country)]

    if not matches:
        found_countries = sorted({c.get("country") for c in candidates if c.get("country")})
        if found_countries:
            print(f"No match for '{city}' in '{country}'. '{city}' was found in: "
                  f"{', '.join(found_countries)}.")
        else:
            print(f"No results for '{city}, {country}'.")
        print("Try again, e.g. 'Paris, France'.")
        return None

    if len(matches) == 1:
        result = matches[0]
        confirm = prompt(f"Use '{describe_geocode_result(result)}'? (Y/n)", "Y")
        if not confirm.strip().lower().startswith("n"):
            return result["latitude"], result["longitude"]
        return None

    shown = matches[:10]
    print(f"Multiple places matched '{city}, {country}':")
    for i, result in enumerate(shown, 1):
        print(f"  {i}) {describe_geocode_result(result)}")
    if len(matches) > len(shown):
        print(f"  ...and {len(matches) - len(shown)} more. Try adding a state/region if yours isn't listed.")
    choice = prompt("Pick a number, or press Enter to search again", "")
    if choice.isdigit() and 1 <= int(choice) <= len(shown):
        result = shown[int(choice) - 1]
        return result["latitude"], result["longitude"]
    return None


def ask_location_city_country():
    while True:
        text = prompt("Enter 'City, Country' (e.g. 'Paris, France')")
        if not text or "," not in text:
            print("Please enter both a city and country, separated by a comma, "
                  "e.g. 'Paris, France'.")
            continue
        city, _, country = text.partition(",")
        city = city.strip()
        country = country.strip()
        if not city or not country:
            print("Please enter both a city and country, separated by a comma, "
                  "e.g. 'Paris, France'.")
            continue

        try:
            candidates = geocode_city_candidates(city)
        except requests.RequestException as e:
            print(f"Couldn't reach the geocoding service ({e}). Try again, or use "
                  f"GPS coordinates / a Plus Code instead.")
            continue

        if not candidates:
            print(f"No results for '{city}'. Try again, e.g. 'Paris, France'.")
            continue

        latlon = _pick_location_from_geocode(city, country, candidates)
        if latlon:
            return latlon


def parse_latlon(text):
    parts = [p.strip() for p in text.replace(",", " ").split()]
    if len(parts) != 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def ask_location():
    print("\n--- Location ---")
    print("How do you want to provide your location?")
    print("  1) GPS coordinates (e.g. 40.68922388147081, -74.04448846124427)")
    print("  2) Google Maps Plus Code (e.g. MXQ4+M5 New York, USA)")
    print("  3) City name and country (e.g. 'Paris, France')")
    choice = prompt("Enter 1, 2, or 3", "1")

    if choice == "1":
        while True:
            text = prompt("Enter GPS coordinates as 'lat, lon'")
            latlon = parse_latlon(text)
            if latlon:
                return latlon
            print("Couldn't parse that. Example: 40.68922388147081, -74.04448846124427")

    if choice == "3":
        return ask_location_city_country()

    # Plus code path
    while True:
        code = prompt("Enter the Plus Code (optionally followed by a city, e.g. 'MXQ4+M5 New York, USA')")
        if not code:
            continue
        parts = code.split(None, 1)
        raw_code = parts[0]
        locality = parts[1] if len(parts) > 1 else None
        try:
            if "+" in raw_code and raw_code.index("+") < 8:
                # short code: needs a reference location
                if not locality:
                    locality = prompt(
                        "This is a short Plus Code. Enter a nearby city name "
                        "(or 'lat, lon') to resolve it"
                    )
                ref = parse_latlon(locality) if locality else None
                if ref is None and locality:
                    try:
                        ref = geocode_city(locality)
                    except requests.RequestException as e:
                        print(f"Geocoding failed ({e}); please enter reference coordinates instead.")
                        ref = None
                if ref is None:
                    print("Couldn't resolve a reference location, try again.")
                    continue
                lat, lon = resolve(raw_code, ref_lat=ref[0], ref_lon=ref[1])
            else:
                lat, lon = resolve(raw_code)
        except PlusCodeError as e:
            print(f"Error: {e}")
            continue
        print(f"Resolved to: {lat:.4f}, {lon:.4f}")
        return lat, lon


def ask_units():
    print("\n--- Units ---")
    choice = prompt("Use (C)elsius or (F)ahrenheit?", "C").strip().upper()
    return "fahrenheit" if choice.startswith("F") else "celsius"


def _pick_timezone_from_geocode(query, candidates):
    """Show geocoding candidates and let the user pick one. Returns the chosen
    timezone string, or None to signal 'search again' (ambiguous/declined)."""
    if len(candidates) == 1:
        result = candidates[0]
        tz = result["timezone"]
        confirm = prompt(f"Use timezone '{tz}' ({describe_geocode_result(result)})? (Y/n)", "Y")
        if not confirm.strip().lower().startswith("n"):
            return tz
        return None

    shown = candidates[:10]
    print(f"Multiple places matched '{query}':")
    for i, result in enumerate(shown, 1):
        print(f"  {i}) {describe_geocode_result(result)} -> {result['timezone']}")
    if len(candidates) > len(shown):
        print(f"  ...and {len(candidates) - len(shown)} more. Try a more specific search "
              f"(e.g. add a state/country) if yours isn't listed.")
    choice = prompt("Pick a number, or press Enter to search again", "")
    if choice.isdigit() and 1 <= int(choice) <= len(shown):
        return shown[int(choice) - 1]["timezone"]
    return None


def _pick_timezone_offline(city):
    """Fallback used when the geocoding API can't be reached. Matches against
    a local, curated list of major cities and IANA zone names."""
    matches = timezones.search(city)
    if not matches:
        return None, False

    if len(matches) == 1:
        tz = matches[0]
        confirm = prompt(f"Use timezone '{tz}'? (Y/n)", "Y")
        if not confirm.strip().lower().startswith("n"):
            return tz, True
        return None, True

    shown = matches[:15]
    print(f"Multiple timezones matched '{city}':")
    for i, tz in enumerate(shown, 1):
        print(f"  {i}) {tz}")
    if len(matches) > len(shown):
        print(f"  ...and {len(matches) - len(shown)} more. Try a more specific city name if yours isn't listed.")
    choice = prompt("Pick a number, or press Enter to search again", "")
    if choice.isdigit() and 1 <= int(choice) <= len(shown):
        return shown[int(choice) - 1], True
    return None, True


def ask_timezone():
    print("\n--- Timezone ---")
    print("Enter a nearby city (any size - e.g. New York, Buffalo, San Diego,")
    print("Milan, Tel Aviv) and we'll look up its timezone. Just press Enter to")
    print("auto-detect it from your GPS coordinates instead.")
    while True:
        city = prompt("City", "")
        if not city:
            return "auto"

        try:
            candidates = geocode_city_candidates(city)
        except requests.RequestException as e:
            print(f"Couldn't reach the geocoding service ({e}); searching a local city list instead.")
            candidates = None

        if candidates:
            tz = _pick_timezone_from_geocode(city, candidates)
            if tz:
                return tz
            continue

        if candidates is not None:
            # Geocoding worked but found nothing - fall back to the offline
            # list too, in case it's a well-known city the API didn't return.
            print(f"No results for '{city}' from the online lookup; trying a local city list.")

        tz, handled = _pick_timezone_offline(city)
        if tz:
            return tz
        if not handled:
            print(f"No timezone found for '{city}'. Try a different (usually "
                  f"larger/nearby) city, or press Enter with no city to auto-detect.")


def _parse_time_24h(text):
    text = text.strip()
    parts = text.split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def _parse_time_12h(text):
    import datetime as _datetime

    text = text.strip().upper().replace(".", "")
    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p"):
        try:
            parsed = _datetime.datetime.strptime(text, fmt)
            return parsed.strftime("%H:%M")
        except ValueError:
            continue
    return None


def ask_daily_digest():
    print("\n--- Daily forecast digest ---")
    print("Get a single push each day with today's and tomorrow's forecast")
    print("(weather emoji, high/low temp, chance of rain, sunrise/sunset),")
    print("sent to the same ntfy topic as alerts.")
    enable = prompt("Enable the daily forecast digest? (Y/n)", "Y").strip().lower()
    if enable.startswith("n"):
        return {"enabled": False, "time": "07:00", "time_format": "24h"}

    fmt = prompt("Enter the time in (1) 24-hour or (2) 12-hour format?", "1").strip()
    use_12h = fmt == "2"
    time_format = "12h" if use_12h else "24h"

    while True:
        if use_12h:
            text = prompt("What time should it be sent? (e.g. '7:30 AM')")
            parsed = _parse_time_12h(text) if text else None
            example = "7:30 AM"
        else:
            text = prompt("What time should it be sent? (e.g. '07:30')")
            parsed = _parse_time_24h(text) if text else None
            example = "07:30"
        if parsed:
            return {"enabled": True, "time": parsed, "time_format": time_format}
        print(f"Couldn't parse that. Example: '{example}'")


def ask_quiet_hours():
    print("\n--- Quiet hours ---")
    print("Suppress non-critical alerts during a window (e.g. overnight) so a")
    print("worsening forecast doesn't push at 3 AM. Thunderstorms still get")
    print("through regardless - everything else just re-checks on the next")
    print("scheduled run once quiet hours end. The daily digest isn't affected.")
    enable = prompt("Enable quiet hours? (y/N)", "N").strip().lower()
    if not enable.startswith("y"):
        return {"enabled": False, "start": "23:00", "end": "07:00"}

    fmt = prompt("Enter times in (1) 24-hour or (2) 12-hour format?", "1").strip()
    use_12h = fmt == "2"

    def ask_time(label, example_24h, example_12h):
        while True:
            if use_12h:
                text = prompt(f"{label} (e.g. '{example_12h}')")
                parsed = _parse_time_12h(text) if text else None
                example = example_12h
            else:
                text = prompt(f"{label} (e.g. '{example_24h}')")
                parsed = _parse_time_24h(text) if text else None
                example = example_24h
            if parsed:
                return parsed
            print(f"Couldn't parse that. Example: '{example}'")

    start = ask_time("Quiet hours start", "23:00", "11:00 PM")
    end = ask_time("Quiet hours end", "07:00", "7:00 AM")
    return {"enabled": True, "start": start, "end": end}


def convert_thresholds(units):
    t = dict(DEFAULT_THRESHOLDS_CELSIUS)
    if units == "fahrenheit":
        high_c = t.pop("temp_high_celsius")
        low_c = t.pop("temp_low_celsius")
        t["temp_high_fahrenheit"] = round(high_c * 9 / 5 + 32, 1)
        t["temp_low_fahrenheit"] = round(low_c * 9 / 5 + 32, 1)
        t["wind_speed_mph"] = round(t.pop("wind_speed_kmh") * 0.621371, 1)
    return t


def print_ntfy_setup_guide(username, topic):
    print(f"""
--- ntfy server setup guide ---
Run these commands ON YOUR NTFY SERVER (not this LXC), in this order,
as root/sudo:

  1) Create a dedicated user for this service:
       sudo ntfy user add {username}
     (you'll be prompted to set a password - you can just press enter/pick
     anything, since we'll use a token below instead of the password)

  2) Grant that user write access to the topic:
       sudo ntfy access {username} {topic} write

  3) Generate an access token for that user:
       sudo ntfy token add {username}
     Copy the token it prints (starts with 'tk_') - you'll paste it in below.

  4) Verify the permissions took effect:
       sudo ntfy access
     You should see '{username} ... write-only access to topic {topic}'.
--------------------------------
""")


def ask_weather_provider():
    print("\n--- Weather provider ---")
    print("Which weather data provider should be used?")
    names = list(providers.PROVIDER_INFO.keys())
    for i, name in enumerate(names, 1):
        info = providers.PROVIDER_INFO[name]
        suffix = " (needs a free API key)" if info["needs_api_key"] else " (current default, no API key needed)"
        print(f"  {i}) {info['label']}{suffix}")
    choice = prompt(f"Enter 1-{len(names)}", "1")
    try:
        index = int(choice) - 1
        name = names[index]
    except (ValueError, IndexError):
        name = "open-meteo"

    info = providers.PROVIDER_INFO[name]
    if not info["needs_api_key"]:
        return {"name": name}

    print(f"\n{info['label']} requires a free API key:")
    print(f"  Sign up: {info['signup_url']}")
    print(f"  {info['instructions']}")
    api_key = prompt(f"Enter your {info['label']} API key")
    while not api_key:
        api_key = prompt("An API key is required for this provider. Enter it now")
    return {"name": name, "api_key": api_key}


def ask_ntfy():
    print("\n--- ntfy notifications ---")
    print("  1) Public ntfy.sh service")
    print("  2) Private/self-hosted ntfy server")
    choice = prompt("Enter 1 or 2", "1")

    if choice == "1":
        server = "https://ntfy.sh"
    else:
        while True:
            server = prompt("Enter your private ntfy server URL (e.g. https://ntfy.example.com)")
            if server and server.startswith("https://"):
                break
            print("Please enter a full https:// URL.")

    topic = prompt("Enter the ntfy topic name to use", "weather-alerts")

    auth = {}
    if choice == "2":
        want_help = prompt(
            "Do you want help setting up the user/permissions/token on your "
            "private ntfy server? (Y/n)", "Y"
        ).strip().lower()
        if want_help.startswith("y"):
            ntfy_username = prompt(
                "What username should be created on the ntfy server for this service?",
                "weatherman",
            )
            print_ntfy_setup_guide(ntfy_username, topic)
            input("Press Enter once you've run those commands and have your token ready...")

        needs_auth = prompt("Does this server require authentication? (Y/n)", "Y").strip().lower()
        if not needs_auth.startswith("n"):
            auth_type = prompt("Use (T)oken or (U)sername/password?", "T").strip().upper()
            if auth_type.startswith("T"):
                auth["token"] = prompt("Enter ntfy access token")
            else:
                auth["username"] = prompt("Enter username")
                auth["password"] = prompt("Enter password")

    return server, topic, auth


def ask_scheduler(config_path):
    print("\n--- Scheduling ---")
    print("How should periodic checks be run?")
    print("  1) systemd timer (recommended if this is a dedicated LXC/systemd host;")
    print("     needs root, auto-restarts, logs to journalctl)")
    print("  2) cron job (no root needed, works on any Linux host)")
    print("  3) Don't install a scheduler (I'll run it manually or manage scheduling myself)")
    choice = prompt("Enter 1, 2, or 3", "1")

    if choice == "3":
        print("Skipping scheduler install. Run checks manually with: python3 weatherman.py")
        return

    interval = prompt("How often should it check, in minutes?", "30")
    try:
        interval = int(interval)
    except ValueError:
        interval = 30

    if choice == "2":
        scheduler.install_cron(interval, config_path)
    else:
        scheduler.install_systemd(interval, config_path)


def clear_screen():
    if not sys.stdout.isatty():
        return
    os.system("cls" if os.name == "nt" else "clear")


def print_recap(recap):
    """Clear the screen and reprint what's been set so far, before starting
    the next section. Never called mid-section - a section's own retries/
    error messages (bad input, disambiguation, etc.) stay fully visible."""
    clear_screen()
    for line in recap:
        print(f"✓ {line}")
    if recap:
        print()


def _provider_label(name):
    return providers.PROVIDER_INFO.get(name, {}).get("label", name)


def main():
    clear_screen()
    print(DISCLAIMER)
    input("Press Enter to continue, or Ctrl+C to exit...")

    if CONFIG_PATH.exists():
        overwrite = prompt(f"{CONFIG_PATH.name} already exists. Overwrite? (y/N)", "N")
        if not overwrite.strip().lower().startswith("y"):
            print("Aborted.")
            sys.exit(0)

    recap = []

    print_recap(recap)
    lat, lon = ask_location()
    recap.append(f"Location: {lat:.4f}, {lon:.4f}")

    print_recap(recap)
    units = ask_units()
    recap.append(f"Units: {'Fahrenheit' if units == 'fahrenheit' else 'Celsius'}")

    print_recap(recap)
    weather_provider = ask_weather_provider()
    recap.append(f"Weather provider: {_provider_label(weather_provider['name'])}")

    print_recap(recap)
    server, topic, auth = ask_ntfy()
    server_desc = "public ntfy.sh" if server == "https://ntfy.sh" else "private server"
    recap.append(f"ntfy: {server_desc}, topic '{topic}'")

    print_recap(recap)
    location_name = prompt("Enter a short name for this location (used in alert titles)", "Home")
    timezone = ask_timezone()
    recap.append(f"Location name: {location_name}")
    recap.append(f"Timezone: {timezone}")

    print_recap(recap)
    daily_digest = ask_daily_digest()
    if daily_digest.get("enabled"):
        recap.append(f"Daily digest: enabled, {daily_digest['time']} ({daily_digest.get('time_format', '24h')})")
    else:
        recap.append("Daily digest: disabled")

    print_recap(recap)
    quiet_hours = ask_quiet_hours()
    if quiet_hours.get("enabled"):
        recap.append(f"Quiet hours: enabled, {quiet_hours['start']}–{quiet_hours['end']}")
    else:
        recap.append("Quiet hours: disabled")

    config = {
        "location": {
            "name": location_name,
            "latitude": lat,
            "longitude": lon,
            "timezone": timezone,
        },
        "units": units,
        "weather_provider": weather_provider,
        "ntfy": {
            "server": server,
            "topic": topic,
            **auth,
        },
        "thresholds": convert_thresholds(units),
        "forecast_hours": 24,
        "alert_cooldown_minutes": 180,
        "daily_digest": daily_digest,
        "quiet_hours": quiet_hours,
    }

    with open(CONFIG_PATH, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)

    print(f"\nWrote {CONFIG_PATH}")
    print("Test it with: python3 weatherman.py --dry-run")
    recap.append(f"Config written to {CONFIG_PATH.name}")

    print_recap(recap)
    ask_scheduler(CONFIG_PATH)


if __name__ == "__main__":
    main()
