# weatherman-project

Monitors the weather forecast and air quality (dust/PM10/PM2.5) for a fixed
location, and sends a push notification via [ntfy](https://ntfy.sh) when
conditions look bad (rain/storms, extreme temperatures, strong wind, or poor
air quality). Can also send a daily forecast digest — today's and tomorrow's
weather with an emoji for conditions at a glance — at a time of your
choosing. Weather data comes from a pluggable provider: the free
[Open-Meteo](https://open-meteo.com) API by default (no key needed), or
OpenWeatherMap/WeatherAPI.com/Tomorrow.io if you'd rather use one of those
(free API key required) — see [Weather providers](#weather-providers) below.

## Files

- `install.sh` — bootstrap script for a fresh Linux host. Detects your
  package manager (apt/dnf/yum/apk/pacman/zypper) and installs whatever's
  missing (Python 3, the `venv` module, pip, a cron daemon, CA certificates),
  creates a virtualenv, installs the Python requirements, then offers to
  launch `setup.py`. Safe to re-run — it skips anything already installed.
- `weatherman.py` — the check script. Fetches forecast + air quality (via
  whichever provider is configured), evaluates thresholds, sends an ntfy push
  if any are exceeded, and (if enabled) sends the daily forecast digest once
  it's past the configured time each day.
- `providers.py` — the weather-provider abstraction. Each provider (Open-Meteo,
  OpenWeatherMap, WeatherAPI.com, Tomorrow.io) has its own fetch function that
  normalizes that provider's response into the same shape, so the rest of the
  app doesn't need to know which one is active. See
  [Weather providers](#weather-providers) below.
- `setup.py` — interactive installer. Prompts for your location (GPS
  coordinates, a Google Maps Plus Code, or a city + country), preferred units
  (Celsius/Fahrenheit), which weather provider to use, ntfy settings (public
  ntfy.sh or a private server + topic), and the daily digest (on/off, and
  what time to send it, in either 12-hour or 24-hour format), then writes
  `config.yaml` for you.
- `pluscode.py` — decodes Google Maps Plus Codes to GPS coordinates, used by
  `setup.py`. No external geocoding API needed for full codes; short codes
  (e.g. `V33Q+3Q5`) are resolved using a nearby reference city/coordinates.
- `config.example.yaml` — documents the config format if you'd rather write
  `config.yaml` by hand instead of using `setup.py`.
- `systemd/weatherman.service` + `systemd/weatherman.timer` — run the check
  every 30 minutes via systemd.
- `update.sh` — checks GitHub for a newer tagged release, shows a changelog
  and any `config.example.yaml` changes, and updates the local checkout on
  confirmation. See [Updating](#updating) below.
- `merge_config.py` — helper invoked by `update.sh` that finds newly
  introduced `config.yaml` options and, on confirmation, adds them in place
  using `ruamel.yaml` (preserves comments/formatting) after backing up the
  original file.

## Setup on the LXC

1. Deploy the code:
   ```bash
   mkdir -p /opt/weatherman
   # copy this repo's contents into /opt/weatherman, e.g.:
   git clone https://github.com/omerdvd/weatherman-project.git /opt/weatherman
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
   - **Weather provider**: Open-Meteo (default, no API key), or
     OpenWeatherMap/WeatherAPI.com/Tomorrow.io if you provide a free API key —
     see [Weather providers](#weather-providers) below for signup links and
     what each one supports.
   - **ntfy**: the public `https://ntfy.sh` service, or your own private
     server (you'll be asked for its `https://` URL and, optionally,
     token/username+password auth), plus the topic name to publish to.
   - **Daily digest**: whether to also send a daily push with today's and
     tomorrow's forecast (with a weather emoji), and what time to send it —
     enter the time in either 12-hour (`7:30 AM`) or 24-hour (`07:30`)
     format, whichever you prefer.
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
- If `daily_digest.enabled` is set, every run also checks whether it's past
  `daily_digest.time` (in the location's timezone) and today's digest hasn't
  been sent yet; if so, it pushes today's and tomorrow's forecast — high/low
  temp, chance of rain, and a weather emoji (☀️🌧️⛈️❄️ etc.) per day — to the
  same ntfy topic as alerts. Since this is only checked on the regular
  schedule, actual delivery can lag the configured time by up to your
  scheduling interval (e.g. up to ~30 minutes with the default). Use
  `--force` to send it immediately regardless of time/already-sent, for
  testing.
- State (last alert timestamp, last digest date) is kept in `state.json`
  next to the script.

## Weather providers

`weather_provider.name` in `config.yaml` selects the data source. All four
return the same alert/digest behavior — the difference is API key
requirements and air-quality coverage:

| Provider | API key | Signup | PM10/PM2.5 | Dust | US AQI (0-500) |
|---|---|---|---|---|---|
| `open-meteo` (default) | Not needed | — | ✅ | ✅ | ✅ |
| `openweathermap` | Free | [Sign up](https://home.openweathermap.org/users/sign_up) | ✅ | ❌ | ❌ |
| `weatherapi` | Free | [Sign up](https://www.weatherapi.com/signup.aspx) | ✅ | ❌ | ❌ |
| `tomorrowio` | Free | [Sign up](https://app.tomorrow.io/signup) | ✅ | ❌ | ❌ |

Only Open-Meteo provides a real "dust" concentration and a numeric 0-500 US
AQI; the other three give raw PM10/PM2.5 concentrations (so those threshold
checks keep working) but their own air-quality indices use different scales,
so `dust`/`us_aqi` alerts are silently skipped — not faked — when using them.

For OpenWeatherMap specifically: use a plain API key from the "API keys" tab
after signup, not a One Call 3.0 subscription — this project only calls the
free `data/2.5/forecast` and `data/2.5/air_pollution` endpoints, which need
no billing/credit card setup. New OpenWeatherMap keys can take up to ~2
hours to activate after creation.

`setup.py` walks you through all of this interactively (including printing
the right signup link) — the table above is mainly useful if you're editing
`config.yaml` by hand or switching providers later.

## Updating

The local install is a git checkout, and releases are git tags (`v1.0.0`,
`v1.1.0`, ...), so updating just means fetching new tags and checking one
out:

```bash
./update.sh
```

It will:
1. `git fetch` tags from GitHub and compare your current checkout against
   the latest `vX.Y.Z` tag.
2. If there's a newer one, show the changelog (`git log old..new --oneline`)
   and, if `config.example.yaml` changed, a diff of what's new.
3. Ask for confirmation before changing anything.
4. On yes: refuse to proceed if you have uncommitted local edits to tracked
   files (to avoid clobbering them), otherwise check out the new tag and
   reinstall `requirements.txt` if it changed.
5. If new `config.yaml` options were introduced, list them (with their
   default values) and offer to add them to your `config.yaml`. Your
   existing values are never touched or removed — only genuinely missing
   keys get added. If you say yes, it backs up your current `config.yaml`
   first (as `config.yaml.bak.<old-version>.<timestamp>`, never
   overwritten) and merges the new keys in using `ruamel.yaml`, which
   preserves your comments and formatting. Say no and it's left completely
   unchanged, same as before.

Nothing needs restarting afterward — systemd and cron both run
`weatherman.py` fresh on every scheduled check, so the update takes effect
on the next run.

Integrity note: this intentionally doesn't do a separate SHA256/checksum
step. Git commits are content-addressed (a Merkle tree over the full file
tree), so comparing the local commit/tag against GitHub's already gives the
same guarantee a manual checksum would - any tampering changes the hash.

### Cutting a new release (for maintainers)

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

Optionally create a matching GitHub Release from that tag for release notes.
`update.sh` only looks at `v*` tags, not raw commits on `main`, so nothing
is "released" until it's tagged.

## Security

See [SECURITY.md](SECURITY.md) for notes on secrets handling and network
exposure.

## Disclaimer

This software is provided "as is", without warranty of any kind, express or
implied. Use it at your own risk. This is a personal home-automation project,
not a certified weather or safety system — don't rely on it as your sole
source of severe-weather or air-quality warnings. See [LICENSE](LICENSE) for
the full license text.

## Credits

- Omer David ([42729996+omerdvd@users.noreply.github.com](mailto:42729996+omerdvd@users.noreply.github.com))
- Claude ([Anthropic](https://claude.ai/code))

## License

[PolyForm Noncommercial License 1.0.0](LICENSE) — free for noncommercial use
(personal, educational, research, hobby, nonprofit, etc.). Commercial use
requires a separate license — contact
[42729996+omerdvd@users.noreply.github.com](mailto:42729996+omerdvd@users.noreply.github.com)
to request one.
