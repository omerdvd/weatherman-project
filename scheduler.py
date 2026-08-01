"""Install/remove periodic scheduling for weatherman.py, via systemd or cron."""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()
SCRIPT_PATH = PROJECT_DIR / "weatherman.py"
CRON_MARKER = "# weatherman-managed"
SYSTEMD_SERVICE_NAME = "weatherman.service"
SYSTEMD_TIMER_NAME = "weatherman.timer"
SYSTEMD_UNIT_DIR = Path("/etc/systemd/system")


def _python_bin():
    venv_python = PROJECT_DIR / "venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def install_cron(interval_minutes, config_path):
    python_bin = _python_bin()
    log_path = PROJECT_DIR / "weatherman.log"
    cmd = (
        f"{python_bin} {SCRIPT_PATH} --config {config_path} "
        f">> {log_path} 2>&1 {CRON_MARKER}"
    )
    line = f"*/{interval_minutes} * * * * {cmd}"

    existing = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True
    )
    current_lines = existing.stdout.splitlines() if existing.returncode == 0 else []
    kept_lines = [l for l in current_lines if CRON_MARKER not in l]
    kept_lines.append(line)

    new_crontab = "\n".join(kept_lines) + "\n"
    result = subprocess.run(["crontab", "-"], input=new_crontab, text=True)
    if result.returncode != 0:
        raise RuntimeError("Failed to install crontab entry")
    print(f"Installed cron job: runs every {interval_minutes} minute(s).")
    print(f"Logs will be written to {log_path}")
    print("View/edit it later with: crontab -e")


def remove_cron():
    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if existing.returncode != 0:
        return
    kept_lines = [l for l in existing.stdout.splitlines() if CRON_MARKER not in l]
    new_crontab = "\n".join(kept_lines) + ("\n" if kept_lines else "")
    subprocess.run(["crontab", "-"], input=new_crontab, text=True)


def install_systemd(interval_minutes, config_path):
    if os.geteuid() != 0:
        print(
            "\nInstalling the systemd timer requires root. Run these commands "
            "manually (as root / with sudo):\n"
        )
        _print_systemd_manual_steps(interval_minutes, config_path)
        return False

    python_bin = _python_bin()
    service_content = (
        "[Unit]\n"
        "Description=Weatherman - weather/air quality alert check\n"
        "Wants=network-online.target\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"WorkingDirectory={PROJECT_DIR}\n"
        f"ExecStart={python_bin} {SCRIPT_PATH} --config {config_path}\n"
    )
    timer_content = (
        "[Unit]\n"
        "Description=Run weatherman check periodically\n\n"
        "[Timer]\n"
        "OnBootSec=2min\n"
        f"OnUnitActiveSec={interval_minutes}min\n"
        "Persistent=true\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )

    (SYSTEMD_UNIT_DIR / SYSTEMD_SERVICE_NAME).write_text(service_content)
    (SYSTEMD_UNIT_DIR / SYSTEMD_TIMER_NAME).write_text(timer_content)

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", SYSTEMD_TIMER_NAME], check=True)
    print(f"Installed and started {SYSTEMD_TIMER_NAME} (every {interval_minutes} minute(s)).")
    print(f"Check status with: systemctl list-timers {SYSTEMD_TIMER_NAME}")
    print(f"View logs with: journalctl -u {SYSTEMD_SERVICE_NAME} -f")
    return True


def _print_systemd_manual_steps(interval_minutes, config_path):
    python_bin = _python_bin()
    print(f"  ExecStart should be: {python_bin} {SCRIPT_PATH} --config {config_path}")
    print(f"  OnUnitActiveSec should be: {interval_minutes}min")
    print("  See systemd/weatherman.service and systemd/weatherman.timer for templates, e.g.:")
    print("    sudo cp systemd/weatherman.service systemd/weatherman.timer /etc/systemd/system/")
    print("    sudo systemctl daemon-reload")
    print("    sudo systemctl enable --now weatherman.timer")


def remove_systemd():
    if os.geteuid() != 0:
        print("Removing the systemd timer requires root; run as sudo.")
        return
    subprocess.run(["systemctl", "disable", "--now", SYSTEMD_TIMER_NAME], check=False)
    (SYSTEMD_UNIT_DIR / SYSTEMD_SERVICE_NAME).unlink(missing_ok=True)
    (SYSTEMD_UNIT_DIR / SYSTEMD_TIMER_NAME).unlink(missing_ok=True)
    subprocess.run(["systemctl", "daemon-reload"], check=False)
