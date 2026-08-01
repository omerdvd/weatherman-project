# weatherman-project

Monitors the weather forecast and air quality (dust/PM10/PM2.5) for a fixed
location using the free [Open-Meteo](https://open-meteo.com) API, and sends a
push notification via [ntfy](https://ntfy.sh) when conditions look bad
(rain/storms, extreme temperatures, strong wind, or poor air quality).

## Files

- `weatherman.py` — the check script. Fetches forecast + air quality, evaluates
  thresholds, sends an ntfy push if any are exceeded.
- `config.example.yaml` — copy to `config.yaml` and edit (location, ntfy
  server/topic, thresholds).
- `systemd/weatherman.service` + `systemd/weatherman.timer` — run the check
  every 30 minutes via systemd.

## Setup on the LXC

1. Install Python 3 and venv:
   ```bash
   apt update && apt install -y python3 python3-venv
   ```

2. Deploy the code:
   ```bash
   mkdir -p /opt/weatherman
   # copy this repo's contents into /opt/weatherman, e.g.:
   git clone <this-repo-url> /opt/weatherman
   cd /opt/weatherman
   cp config.example.yaml config.yaml
   ```

3. Edit `config.yaml`:
   - `location.latitude` / `location.longitude` are already set to Kiryat
     Motzkin (32.8526, 35.0895) — adjust if needed.
   - `ntfy.server` is set to `https://ntfy.omeruthi.online`, topic
     `weather-alerts`. Add `token` or `username`/`password` under `ntfy:` if
     your server requires auth.
   - Tune `thresholds:` to taste.

4. Create a venv and install deps:
   ```bash
   python3 -m venv /opt/weatherman/venv
   /opt/weatherman/venv/bin/pip install -r /opt/weatherman/requirements.txt
   ```

5. Create a dedicated system user (optional but recommended):
   ```bash
   useradd --system --home /opt/weatherman --shell /usr/sbin/nologin weatherman
   chown -R weatherman:weatherman /opt/weatherman
   ```

6. Install and enable the systemd timer:
   ```bash
   cp systemd/weatherman.service systemd/weatherman.timer /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable --now weatherman.timer
   ```

7. Test it manually first:
   ```bash
   sudo -u weatherman /opt/weatherman/venv/bin/python /opt/weatherman/weatherman.py --config /opt/weatherman/config.yaml --dry-run
   ```
   This prints any triggered alerts without sending to ntfy. Drop `--dry-run`
   to actually send. Use `--force` to bypass the alert cooldown for testing.

8. Check timer status / logs:
   ```bash
   systemctl list-timers weatherman.timer
   journalctl -u weatherman.service -f
   ```

## How it works

- Runs every 30 minutes (`OnUnitActiveSec=30min` in the timer).
- Looks at the next `forecast_hours` (default 24) of hourly forecast data.
- Alerts if any of: precipitation probability/amount, thunderstorm codes,
  max/min temperature, wind speed, PM10, PM2.5, dust concentration, or US AQI
  exceed the configured thresholds.
- To avoid notification spam, it won't re-send while conditions remain bad
  within `alert_cooldown_minutes` (default 180) of the last alert. Once
  conditions clear and re-trigger later, a new alert fires immediately.
- State (last alert timestamp) is kept in `state.json` next to the script.

## Security

See [SECURITY.md](SECURITY.md) for notes on secrets handling and network
exposure.

## License

[MIT](LICENSE)
