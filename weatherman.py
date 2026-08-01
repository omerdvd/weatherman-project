#!/usr/bin/env python3
"""Check the weather/air-quality forecast and push an ntfy alert if conditions are bad."""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import requests
import yaml

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
THUNDERSTORM_CODES = {95, 96, 99}

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
    params = {
        "latitude": cfg["location"]["latitude"],
        "longitude": cfg["location"]["longitude"],
        "timezone": cfg["location"].get("timezone", "auto"),
        "hourly": "temperature_2m,precipitation_probability,precipitation,weathercode,windspeed_10m",
        "forecast_days": 2,
    }
    resp = requests.get(WEATHER_URL, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def fetch_air_quality(cfg):
    params = {
        "latitude": cfg["location"]["latitude"],
        "longitude": cfg["location"]["longitude"],
        "hourly": "pm10,pm2_5,dust,us_aqi",
        "forecast_days": 2,
    }
    resp = requests.get(AIR_QUALITY_URL, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def evaluate(cfg, weather, air_quality):
    """Return a list of alert message strings, or an empty list if all clear."""
    hours = cfg.get("forecast_hours", 24)
    t = cfg["thresholds"]
    alerts = []

    w_hourly = weather["hourly"]
    n = min(hours, len(w_hourly["time"]))

    max_temp = max(w_hourly["temperature_2m"][:n])
    min_temp = min(w_hourly["temperature_2m"][:n])
    max_precip_prob = max(w_hourly["precipitation_probability"][:n])
    max_precip_mm = max(w_hourly["precipitation"][:n])
    max_wind = max(w_hourly["windspeed_10m"][:n])
    codes = w_hourly["weathercode"][:n]
    has_storm = any(c in THUNDERSTORM_CODES for c in codes)

    if max_precip_prob >= t["precipitation_probability_percent"] or max_precip_mm >= t["precipitation_mm"]:
        alerts.append(
            f"Rain expected: up to {max_precip_prob:.0f}% chance, {max_precip_mm:.1f}mm/h"
        )
    if t.get("thunderstorm") and has_storm:
        alerts.append("Thunderstorms forecast")
    if max_temp >= t["temp_high_celsius"]:
        alerts.append(f"High temperature: {max_temp:.1f}°C")
    if min_temp <= t["temp_low_celsius"]:
        alerts.append(f"Low temperature: {min_temp:.1f}°C")
    if max_wind >= t["wind_speed_kmh"]:
        alerts.append(f"Strong wind: {max_wind:.0f} km/h")

    aq_hourly = air_quality["hourly"]
    n_aq = min(hours, len(aq_hourly["time"]))

    max_pm10 = max(v for v in aq_hourly["pm10"][:n_aq] if v is not None)
    max_pm2_5 = max(v for v in aq_hourly["pm2_5"][:n_aq] if v is not None)
    max_dust = max(v for v in aq_hourly["dust"][:n_aq] if v is not None)
    max_us_aqi = max(v for v in aq_hourly["us_aqi"][:n_aq] if v is not None)

    if max_pm10 >= t["pm10"]:
        alerts.append(f"Poor air quality: PM10 up to {max_pm10:.0f} µg/m³")
    if max_pm2_5 >= t["pm2_5"]:
        alerts.append(f"Poor air quality: PM2.5 up to {max_pm2_5:.0f} µg/m³")
    if max_dust >= t["dust"]:
        alerts.append(f"Dust alert: dust concentration up to {max_dust:.0f} µg/m³")
    if max_us_aqi >= t["us_aqi"]:
        alerts.append(f"Poor air quality: US AQI up to {max_us_aqi:.0f}")

    return alerts


def send_ntfy(cfg, alerts):
    ntfy = cfg["ntfy"]
    url = f"{ntfy['server'].rstrip('/')}/{ntfy['topic']}"
    body = "\n".join(f"- {a}" for a in alerts)
    location_name = cfg["location"].get("name", "your area")

    headers = {
        "Title": f"Weather/AQI alert: {location_name}".encode("utf-8"),
        "Priority": "high",
        "Tags": "warning,partly_sunny",
    }
    auth = None
    if ntfy.get("token"):
        headers["Authorization"] = f"Bearer {ntfy['token']}"
    elif ntfy.get("username") and ntfy.get("password"):
        auth = (ntfy["username"], ntfy["password"])

    resp = requests.post(url, data=body.encode("utf-8"), headers=headers, auth=auth, timeout=20)
    resp.raise_for_status()
    log.info("Sent ntfy alert: %s", alerts)


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
        help="Ignore the alert cooldown and send even if a recent alert was already sent",
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
        return

    cooldown = cfg.get("alert_cooldown_minutes", 180) * 60
    last_sent = state.get("last_alert_sent", 0)
    if not args.force and time.time() - last_sent < cooldown:
        log.info("Alert conditions met but still within cooldown; skipping send. Alerts: %s", alerts)
        return

    log.info("Alert conditions met: %s", alerts)
    if args.dry_run:
        print("\n".join(alerts))
        return

    send_ntfy(cfg, alerts)
    state["last_alert_sent"] = time.time()
    save_state(state)


if __name__ == "__main__":
    main()
