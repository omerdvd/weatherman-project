#!/usr/bin/env python3
"""Check the weather/air-quality forecast and push an ntfy alert if conditions are bad."""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

import providers

THUNDERSTORM_CODES = {95, 96, 99}

# WMO weather interpretation codes (used by Open-Meteo) -> (emoji, description)
WEATHER_CODE_INFO = {
    0: ("☀️", "Clear sky"),
    1: ("🌤️", "Mainly clear"),
    2: ("⛅", "Partly cloudy"),
    3: ("☁️", "Overcast"),
    45: ("🌫️", "Fog"),
    48: ("🌫️", "Depositing rime fog"),
    51: ("🌦️", "Light drizzle"),
    53: ("🌦️", "Moderate drizzle"),
    55: ("🌦️", "Dense drizzle"),
    56: ("🌧️", "Light freezing drizzle"),
    57: ("🌧️", "Dense freezing drizzle"),
    61: ("🌧️", "Slight rain"),
    63: ("🌧️", "Moderate rain"),
    65: ("🌧️", "Heavy rain"),
    66: ("🌧️", "Light freezing rain"),
    67: ("🌧️", "Heavy freezing rain"),
    71: ("❄️", "Slight snow fall"),
    73: ("❄️", "Moderate snow fall"),
    75: ("❄️", "Heavy snow fall"),
    77: ("❄️", "Snow grains"),
    80: ("🌦️", "Slight rain showers"),
    81: ("🌧️", "Moderate rain showers"),
    82: ("🌧️", "Violent rain showers"),
    85: ("🌨️", "Slight snow showers"),
    86: ("🌨️", "Heavy snow showers"),
    95: ("⛈️", "Thunderstorm"),
    96: ("⛈️", "Thunderstorm with slight hail"),
    99: ("⛈️", "Thunderstorm with heavy hail"),
}


def describe_weathercode(code):
    return WEATHER_CODE_INFO.get(code, ("🌡️", "Unknown"))

STATE_FILE = Path(__file__).parent / "state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("weatherman")


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


def fetch_weather(cfg):
    return providers.fetch_weather(cfg)


def fetch_air_quality(cfg):
    return providers.fetch_air_quality(cfg)


def evaluate(cfg, weather, air_quality):
    """Return a list of alert message strings, or an empty list if all clear."""
    hours = cfg.get("forecast_hours", 24)
    t = cfg["thresholds"]
    units = cfg.get("units", "celsius")
    is_fahrenheit = units == "fahrenheit"
    temp_symbol = "°F" if is_fahrenheit else "°C"
    wind_unit = "mph" if is_fahrenheit else "km/h"
    temp_high_key = "temp_high_fahrenheit" if is_fahrenheit else "temp_high_celsius"
    temp_low_key = "temp_low_fahrenheit" if is_fahrenheit else "temp_low_celsius"
    wind_key = "wind_speed_mph" if is_fahrenheit else "wind_speed_kmh"
    alerts = []

    def _max_or_none(values):
        present = [v for v in values if v is not None]
        return max(present) if present else None

    def _min_or_none(values):
        present = [v for v in values if v is not None]
        return min(present) if present else None

    w_hourly = weather["hourly"]
    n = min(hours, len(w_hourly["time"]))

    max_temp = _max_or_none(w_hourly["temperature_2m"][:n])
    min_temp = _min_or_none(w_hourly["temperature_2m"][:n])
    max_precip_prob = _max_or_none(w_hourly["precipitation_probability"][:n])
    max_precip_mm = _max_or_none(w_hourly["precipitation"][:n])
    max_wind = _max_or_none(w_hourly["windspeed_10m"][:n])
    codes = [c for c in w_hourly["weathercode"][:n] if c is not None]
    has_storm = any(c in THUNDERSTORM_CODES for c in codes)

    # An empty/missing hourly window (e.g. a provider hiccup) skips these
    # checks rather than crashing - same spirit as the air-quality checks
    # below, which already tolerate providers missing individual metrics.
    if max_precip_prob is not None and max_precip_mm is not None and (
        max_precip_prob >= t["precipitation_probability_percent"] or max_precip_mm >= t["precipitation_mm"]
    ):
        alerts.append(
            f"Rain expected: up to {max_precip_prob:.0f}% chance, {max_precip_mm:.1f}mm/h"
        )
    if t.get("thunderstorm") and has_storm:
        alerts.append("Thunderstorms forecast")
    if max_temp is not None and max_temp >= t[temp_high_key]:
        alerts.append(f"High temperature: {max_temp:.1f}{temp_symbol}")
    if min_temp is not None and min_temp <= t[temp_low_key]:
        alerts.append(f"Low temperature: {min_temp:.1f}{temp_symbol}")
    if max_wind is not None and max_wind >= t[wind_key]:
        alerts.append(f"Strong wind: {max_wind:.0f} {wind_unit}")

    aq_hourly = air_quality["hourly"]
    n_aq = min(hours, len(aq_hourly["time"]))

    def _max_or_none(values):
        present = [v for v in values if v is not None]
        return max(present) if present else None

    max_pm10 = _max_or_none(aq_hourly["pm10"][:n_aq])
    max_pm2_5 = _max_or_none(aq_hourly["pm2_5"][:n_aq])
    max_dust = _max_or_none(aq_hourly["dust"][:n_aq])
    max_us_aqi = _max_or_none(aq_hourly["us_aqi"][:n_aq])

    # dust and us_aqi aren't available from every provider (see providers.py) -
    # skip those checks entirely rather than crash or falsely alert on None.
    if max_pm10 is not None and max_pm10 >= t["pm10"]:
        alerts.append(f"Poor air quality: PM10 up to {max_pm10:.0f} µg/m³")
    if max_pm2_5 is not None and max_pm2_5 >= t["pm2_5"]:
        alerts.append(f"Poor air quality: PM2.5 up to {max_pm2_5:.0f} µg/m³")
    if max_dust is not None and max_dust >= t["dust"]:
        alerts.append(f"Dust alert: dust concentration up to {max_dust:.0f} µg/m³")
    if max_us_aqi is not None and max_us_aqi >= t["us_aqi"]:
        alerts.append(f"Poor air quality: US AQI up to {max_us_aqi:.0f}")

    return alerts


def send_ntfy_message(cfg, title, body, tags="", priority="default"):
    ntfy = cfg["ntfy"]
    url = f"{ntfy['server'].rstrip('/')}/{ntfy['topic']}"

    headers = {
        "Title": title.encode("utf-8"),
        "Priority": priority,
        "Tags": tags,
    }
    auth = None
    if ntfy.get("token"):
        headers["Authorization"] = f"Bearer {ntfy['token']}"
    elif ntfy.get("username") and ntfy.get("password"):
        auth = (ntfy["username"], ntfy["password"])

    resp = requests.post(url, data=body.encode("utf-8"), headers=headers, auth=auth, timeout=20)
    resp.raise_for_status()


def send_ntfy(cfg, alerts):
    body = "\n".join(f"- {a}" for a in alerts)
    location_name = cfg["location"].get("name", "your area")
    send_ntfy_message(
        cfg,
        title=f"Weather/AQI alert: {location_name}",
        body=body,
        tags="warning,partly_sunny",
        priority="high",
    )
    log.info("Sent ntfy alert: %s", alerts)


def _get_local_now(cfg, weather):
    tz_name = weather.get("timezone") or cfg["location"].get("timezone") or "UTC"
    try:
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        return datetime.utcnow()


def in_quiet_hours(cfg, now_local):
    """True if `now_local` falls within the configured quiet_hours window.
    Handles a window that spans midnight (e.g. start=23:00, end=07:00)."""
    qh = cfg.get("quiet_hours") or {}
    if not qh.get("enabled"):
        return False

    start = qh.get("start", "23:00")
    end = qh.get("end", "07:00")
    now_str = now_local.strftime("%H:%M")

    if start <= end:
        return start <= now_str < end
    return now_str >= start or now_str < end


def _is_critical_alert(alert):
    """Alerts severe enough to bypass quiet hours. Currently just
    thunderstorms - routine threshold alerts (temp/wind/AQI/rain) are
    suppressed during quiet hours and simply re-evaluated on the next
    scheduled run once quiet hours end, rather than queued for delivery."""
    return alert == "Thunderstorms forecast"


def _format_display_time(hhmm, time_format):
    """Format an internal 24h 'HH:MM' string per the user's chosen display
    format ('12h' or '24h'), matching the format they entered the daily
    digest send time in during setup."""
    if not hhmm:
        return None
    if time_format == "12h":
        return datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0")
    return hhmm


def build_daily_digest(cfg, weather):
    daily = weather["daily"]
    units = cfg.get("units", "celsius")
    temp_symbol = "°F" if units == "fahrenheit" else "°C"
    day_labels = ["Today", "Tomorrow"]
    time_format = (cfg.get("daily_digest") or {}).get("time_format", "24h")
    n_days = len(daily["time"])
    sunrises = daily.get("sunrise") or [None] * n_days
    sunsets = daily.get("sunset") or [None] * n_days

    lines = []
    for i, label in enumerate(day_labels):
        if i >= len(daily["time"]):
            break
        emoji, desc = describe_weathercode(daily["weathercode"][i])
        hi = daily["temperature_2m_max"][i]
        lo = daily["temperature_2m_min"][i]
        hi_str = f"H:{hi:.0f}{temp_symbol}" if hi is not None else "H:?"
        lo_str = f"L:{lo:.0f}{temp_symbol}" if lo is not None else "L:?"
        line = f"{emoji} {label} ({daily['time'][i]}): {desc}, {hi_str} {lo_str}"
        precip_prob = daily.get("precipitation_probability_max", [None] * len(daily["time"]))[i]
        if precip_prob is not None:
            line += f", {precip_prob:.0f}% chance of rain"

        sunrise = _format_display_time(sunrises[i] if i < len(sunrises) else None, time_format)
        sunset = _format_display_time(sunsets[i] if i < len(sunsets) else None, time_format)
        if sunrise:
            line += f", 🌅 {sunrise}"
        if sunset:
            line += f" 🌇 {sunset}"
        lines.append(line)

    return "\n".join(lines)


def handle_daily_digest(cfg, weather, state, args):
    digest_cfg = cfg.get("daily_digest") or {}
    if not digest_cfg.get("enabled"):
        return

    now_local = _get_local_now(cfg, weather)

    today_str = now_local.strftime("%Y-%m-%d")
    digest_time = digest_cfg.get("time", "07:00")
    already_sent_today = state.get("last_digest_date") == today_str
    time_reached = now_local.strftime("%H:%M") >= digest_time

    if not args.force:
        if already_sent_today:
            return
        if not time_reached:
            return

    body = build_daily_digest(cfg, weather)
    location_name = cfg["location"].get("name", "your area")
    title = f"Daily forecast: {location_name}"

    log.info("Sending daily digest.")
    if args.dry_run:
        print(body)
        return

    send_ntfy_message(cfg, title=title, body=body, tags="calendar", priority="default")
    state["last_digest_date"] = today_str
    save_state(state)
    log.info("Sent daily digest.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-c", "--config", default=str(Path(__file__).parent / "config.yaml"),
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Evaluate conditions and print alerts without sending to ntfy",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Ignore the alert cooldown/daily-digest schedule and send anyway",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    state = load_state()

    try:
        weather = fetch_weather(cfg)
        air_quality = fetch_air_quality(cfg)
    except requests.RequestException as e:
        log.error("Failed to fetch forecast data: %s", e)
        sys.exit(1)

    alerts = evaluate(cfg, weather, air_quality)

    if not alerts:
        log.info("No alert conditions met.")
    else:
        alerts_to_send = alerts
        if not args.force and in_quiet_hours(cfg, _get_local_now(cfg, weather)):
            alerts_to_send = [a for a in alerts if _is_critical_alert(a)]
            suppressed = [a for a in alerts if a not in alerts_to_send]
            if suppressed:
                log.info("Quiet hours active; suppressing non-critical alerts: %s", suppressed)

        if not alerts_to_send:
            pass
        else:
            cooldown = cfg.get("alert_cooldown_minutes", 180) * 60
            last_sent = state.get("last_alert_sent", 0)
            if not args.force and time.time() - last_sent < cooldown:
                log.info("Alert conditions met but still within cooldown; skipping send. Alerts: %s", alerts_to_send)
            else:
                log.info("Alert conditions met: %s", alerts_to_send)
                if args.dry_run:
                    print("\n".join(alerts_to_send))
                else:
                    send_ntfy(cfg, alerts_to_send)
                    state["last_alert_sent"] = time.time()
                    save_state(state)

    handle_daily_digest(cfg, weather, state, args)


if __name__ == "__main__":
    main()
