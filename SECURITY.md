# Security Policy

This is a small personal home-automation project (a weather/air-quality
monitor that pushes ntfy notifications). It has a minimal attack surface, but
here's what to know:

## Secrets and configuration

- `config.yaml` is git-ignored and never committed. It's where your ntfy
  server URL/topic and any ntfy auth credentials (`token` or
  `username`/`password`), plus a weather-provider `api_key` if you've
  configured one (OpenWeatherMap/WeatherAPI.com/Tomorrow.io), live — keep it
  local to the host running the service. `config.yaml.bak.*` backup files
  created by `update.sh`'s config-merge feature contain the same secrets and
  are git-ignored too.
- Never commit real credentials to `config.example.yaml` or anywhere else in
  the repo. That file should only ever contain placeholder/example values.
- If you accidentally commit a secret, treat it as compromised: rotate the
  ntfy token/password or weather-provider API key immediately, then remove it
  from git history (e.g. with `git filter-repo` or by force-pushing a
  rewritten history), not just delete it in a new commit.

## Network exposure

- The service makes outbound HTTPS requests to your configured weather
  provider (`api.open-meteo.com`/`air-quality-api.open-meteo.com` by
  default, or `api.openweathermap.org`/`api.weatherapi.com`/
  `api.tomorrow.io` if configured) and your configured ntfy server. It does
  not open any listening ports or accept inbound connections.
- If your ntfy server is exposed to the internet, make sure the topic name
  isn't easily guessable and consider enabling authentication
  (token/username+password) on the ntfy server itself, since anyone who knows
  the topic can otherwise read or publish to it.
- Run the service as a dedicated unprivileged system user (see README), not
  as root, and keep the host LXC's OS packages up to date.

## Reporting an issue

This is a personal repository without a formal disclosure process. If you
spot a security issue, please open a GitHub issue or contact the repository
owner directly.
