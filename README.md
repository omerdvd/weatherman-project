# weatherman-project

Monitors the weather forecast and air quality (dust/PM10/PM2.5) for a fixed
location using the free [Open-Meteo](https://open-meteo.com) API, and sends a
push notification via [ntfy](https://ntfy.sh) when conditions look bad
(rain/storms, extreme temperatures, strong wind, or poor air quality).

## Files

- `install.sh` — bootstrap script for a fresh Linux host. Detects your
  package manager (apt/dnf/yum/apk/pacman/zypper) and installs whatever's
  missing (Python 3, the `venv` module, pip, a cron daemon, CA certificates),
  creates a virtualenv, installs the Python requirements, then offers to
  launch `setup.py`. Safe to re-run — it skips anything already installed.
- `weatherman.py` — the check script. Fetches forecast + air quality, evaluates
  thresholds, sends an ntfy push if any are exceeded.
- `setup.py` — interactive installer. Prompts for your location (GPS
  coordinates or a Google Maps Plus Code), preferred units (Celsius/
  Fahrenheit), and ntfy settings (public ntfy.sh or a private server + topic),
  then writes `config.yaml` for you.
- `pluscode.py` — decodes Google Maps Plus Codes to GPS coordinates, used by
  `setup.py`. No external geocoding API needed for full codes; short codes
  (e.g. `V33Q+3Q5`) are resolved using a nearby reference city/coordinates.
- `config.example.yaml` — documents the config format if you'd rather write
  `config.yaml` by hand instead of using `setup.py`.
- `systemd/weatherman.service` + `systemd/weatherman.timer` — run the check
  every 30 minutes via systemd.

## Setup on the LXC

1. Deploy the code:
   ```bash
   mkdir -p /opt/weatherman
   # copy this repo's contents into /opt/weatherman, e.g.:
   git clone <this-repo-url> /opt/weatherman
   cd /opt/weatherman
   ```

2. Run the bootstrap script. On a bare/fresh LXC this installs every system
   dependency it needs (Python 3, `venv`, `pip`, a cron daemon, CA
   certificates) via your distro's package manager, then creates a
   `venv/` and installs the Python requirements into it:
   ```bash
   ./install.sh
   ```
   It'll ask at the end whether to launch the interactive setup immediately;
   say no here if you want to create a dedicated system user first (next
   step), then run setup manually afterwards.

3. Create a dedicated system user (optional but recommended, systemd-timer
   installs run as root otherwise):
   ```bash
   useradd --system --home /opt/weatherman --shell /usr/sbin/nologin weatherman
   chown -R weatherman:weatherman /opt/weatherman
   ```

4. Run the interactive installer to create `config.yaml` and (optionally) set
   up scheduling:
   ```bash
   sudo -u weatherman /opt/weatherman/venv/bin/python setup.py
   # or run as root/sudo directly if you want the systemd timer installed for you
   ```
   It will ask for:
   - **Location**: GPS coordinates (`lat, lon`), or a Google Maps Plus Code.
     Full plus codes (e.g. `8FVC9G8F+6X`) decode directly; short codes (e.g.
     `V33Q+3Q5`) also need a nearby city name or approximate coordinates to
     resolve unambiguously — you'll be prompted for one.
   - **Units**: Celsius or Fahrenheit — this sets both the units fetched from
     the weather API and which threshold keys are used.
   - **ntfy**: the public `https://ntfy.sh` service, or your own private
     server (you'll be asked for its `https://` URL and, optionally,
     token/username+password auth), plus the topic name to publish to.
   - **Scheduling**: how the periodic check should run —
     - *systemd timer* (needs root; if not run as root, prints the manual
       `systemctl`/unit-file steps instead of failing)
     - *cron* (no root needed, works via the current user's crontab; running
       setup again just replaces the previous cron entry instead of adding a
       duplicate)
     - *none* — skip scheduling entirely and run `weatherman.py` yourself
       (manually, via your own scheduler, etc.)

   Prefer to configure by hand instead? Copy `config.example.yaml` to
   `config.yaml` and edit it directly — see that file for the format. You can
   also install/manage scheduling separately at any time via `scheduler.py`'s
   `install_cron` / `install_systemd` / `remove_cron` / `remove_systemd`
   functions, or by re-running `setup.py`.

5. Test it manually:
   ```bash
   sudo -u weatherman /opt/weatherman/venv/bin/python /opt/weatherman/weatherman.py --config /opt/weatherman/config.yaml --dry-run
   ```
   This prints any triggered alerts without sending to ntfy. Drop `--dry-run`
   to actually send. Use `--force` to bypass the alert cooldown for testing.

6. Check scheduled runs:
   - systemd: `systemctl list-timers weatherman.timer` and
     `journalctl -u weatherman.service -f`
   - cron: `crontab -l` to see the installed entry, and check
     `weatherman.log` in the project directory for output

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

## Disclaimer

This software is provided "as is", without warranty of any kind, express or
implied. Use it at your own risk. This is a personal home-automation project,
not a certified weather or safety system — don't rely on it as your sole
source of severe-weather or air-quality warnings. See [LICENSE](LICENSE) for
the full MIT license text.

## Credits

- Omer David ([42729996+omerdvd@users.noreply.github.com](mailto:42729996+omerdvd@users.noreply.github.com))
- Claude ([Anthropic](https://claude.ai/code))

## License

[MIT](LICENSE)
