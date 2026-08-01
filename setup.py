#!/usr/bin/env python3
"""Interactive installer: prompts for location, units, and ntfy settings,
then writes config.yaml.

Run this once when installing the service:
    python3 setup.py
"""

import sys
from pathlib import Path

import requests
import yaml

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
    print("  1) GPS coordinates (e.g. 32.8526, 35.0895)")
    print("  2) Google Maps Plus Code (e.g. V33Q+3Q5 Kiryat Motzkin)")
    choice = prompt("Enter 1 or 2", "1")

    if choice == "1":
        while True:
            text = prompt("Enter GPS coordinates as 'lat, lon'")
            latlon = parse_latlon(text)
            if latlon:
                return latlon
            print("Couldn't parse that. Example: 32.8526, 35.0895")

    # Plus code path
    while True:
        code = prompt("Enter the Plus Code (optionally followed by a city, e.g. 'V33Q+3Q5 Kiryat Motzkin')")
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


def convert_thresholds(units):
    t = dict(DEFAULT_THRESHOLDS_CELSIUS)
    if units == "fahrenheit":
        high_c = t.pop("temp_high_celsius")
        low_c = t.pop("temp_low_celsius")
        t["temp_high_fahrenheit"] = round(high_c * 9 / 5 + 32, 1)
        t["temp_low_fahrenheit"] = round(low_c * 9 / 5 + 32, 1)
        t["wind_speed_mph"] = round(t.pop("wind_speed_kmh") * 0.621371, 1)
    return t


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
        needs_auth = prompt("Does this server require authentication? (y/N)", "N").strip().lower()
        if needs_auth.startswith("y"):
            auth_type = prompt("Use (T)oken or (U)sername/password?", "T").strip().upper()
            if auth_type.startswith("T"):
                auth["token"] = prompt("Enter ntfy access token")
            else:
                auth["username"] = prompt("Enter username")
                auth["password"] = prompt("Enter password")

    return server, topic, auth


def main():
    if CONFIG_PATH.exists():
        overwrite = prompt(f"{CONFIG_PATH.name} already exists. Overwrite? (y/N)", "N")
        if not overwrite.strip().lower().startswith("y"):
            print("Aborted.")
            sys.exit(0)

    lat, lon = ask_location()
    units = ask_units()
    server, topic, auth = ask_ntfy()

    location_name = prompt("Enter a short name for this location (used in alert titles)", "Home")
    timezone = prompt("Enter an IANA timezone", "auto")

    config = {
        "location": {
            "name": location_name,
            "latitude": lat,
            "longitude": lon,
            "timezone": timezone,
        },
        "units": units,
        "ntfy": {
            "server": server,
            "topic": topic,
            **auth,
        },
        "thresholds": convert_thresholds(units),
        "forecast_hours": 24,
        "alert_cooldown_minutes": 180,
    }

    with open(CONFIG_PATH, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)

    print(f"\nWrote {CONFIG_PATH}")
    print("Test it with: python3 weatherman.py --dry-run")


if __name__ == "__main__":
    main()
