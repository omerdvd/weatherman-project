#!/usr/bin/env bash
# Bootstrap weatherman on a fresh Linux host: installs system dependencies
# (Python 3, venv, pip, cron), creates a virtualenv, installs Python
# requirements, then optionally launches the interactive setup.
#
# Usage: ./install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

log() { printf '\033[1;32m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m==>\033[0m %s\n' "$1"; }

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        warn "Not running as root and 'sudo' isn't available. System package installs may fail."
    fi
fi

PKG_MANAGER=""
if command -v apt-get >/dev/null 2>&1; then
    PKG_MANAGER="apt"
elif command -v dnf >/dev/null 2>&1; then
    PKG_MANAGER="dnf"
elif command -v yum >/dev/null 2>&1; then
    PKG_MANAGER="yum"
elif command -v apk >/dev/null 2>&1; then
    PKG_MANAGER="apk"
elif command -v pacman >/dev/null 2>&1; then
    PKG_MANAGER="pacman"
elif command -v zypper >/dev/null 2>&1; then
    PKG_MANAGER="zypper"
fi

PKG_UPDATED=0

pkg_update_once() {
    if [ "$PKG_UPDATED" -eq 1 ]; then
        return
    fi
    case "$PKG_MANAGER" in
        apt) $SUDO apt-get update -y ;;
        pacman) $SUDO pacman -Sy --noconfirm ;;
        *) ;;
    esac
    PKG_UPDATED=1
}

install_packages() {
    if [ -z "$PKG_MANAGER" ]; then
        warn "Couldn't detect a supported package manager (apt/dnf/yum/apk/pacman/zypper)."
        warn "Please install manually: $*"
        return 1
    fi
    log "Installing: $*"
    case "$PKG_MANAGER" in
        apt)
            pkg_update_once
            $SUDO apt-get install -y "$@"
            ;;
        dnf) $SUDO dnf install -y "$@" ;;
        yum) $SUDO yum install -y "$@" ;;
        apk) $SUDO apk add --no-cache "$@" ;;
        pacman)
            pkg_update_once
            $SUDO pacman -S --noconfirm "$@"
            ;;
        zypper) $SUDO zypper install -y "$@" ;;
    esac
}

# --- Python 3 ---
if ! command -v python3 >/dev/null 2>&1; then
    log "python3 not found, installing..."
    case "$PKG_MANAGER" in
        apt) install_packages python3 ;;
        dnf|yum) install_packages python3 ;;
        apk) install_packages python3 ;;
        pacman) install_packages python ;;
        zypper) install_packages python3 ;;
        *) install_packages python3 ;;
    esac
else
    log "python3 found: $(python3 --version)"
fi

# --- venv module ---
if ! python3 -m venv --help >/dev/null 2>&1; then
    log "python3 'venv' module not available, installing..."
    case "$PKG_MANAGER" in
        apt)
            PYVER="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
            install_packages "python3-venv" || install_packages "python${PYVER}-venv"
            ;;
        dnf|yum) install_packages python3-libs python3 ;;
        apk) install_packages py3-virtualenv ;;
        pacman) : ;; # bundled with python on Arch
        zypper) install_packages python3-venv ;;
        *) warn "Please ensure the Python 'venv' module is installed." ;;
    esac
fi

# --- pip (for ensurepip fallback / system pip) ---
if ! python3 -m pip --version >/dev/null 2>&1; then
    log "pip not available for python3, installing..."
    case "$PKG_MANAGER" in
        apt) install_packages python3-pip ;;
        dnf|yum) install_packages python3-pip ;;
        apk) install_packages py3-pip ;;
        pacman) install_packages python-pip ;;
        zypper) install_packages python3-pip ;;
        *) python3 -m ensurepip --upgrade || warn "Could not bootstrap pip automatically." ;;
    esac
fi

# --- cron (only needed if the user picks cron scheduling in setup.py) ---
if ! command -v crontab >/dev/null 2>&1; then
    log "crontab not found, installing a cron daemon (needed only if you choose cron scheduling)..."
    case "$PKG_MANAGER" in
        apt) install_packages cron ;;
        dnf|yum) install_packages cronie ;;
        apk) install_packages cronie ;;
        pacman) install_packages cronie ;;
        zypper) install_packages cronie ;;
        *) warn "Install a cron daemon manually if you plan to use cron scheduling." ;;
    esac
fi

# --- CA certificates (needed for HTTPS calls to Open-Meteo / ntfy) ---
case "$PKG_MANAGER" in
    apt) install_packages ca-certificates >/dev/null 2>&1 || true ;;
    *) ;;
esac

# --- virtualenv + Python deps ---
if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtualenv at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
else
    log "Virtualenv already exists at $VENV_DIR"
fi

log "Installing Python requirements"
"$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

log "Dependencies installed."
echo
echo "Next: run the interactive setup to configure location, units, ntfy, and scheduling:"
echo "  $VENV_DIR/bin/python $SCRIPT_DIR/setup.py"
echo

read -r -p "Run setup now? [Y/n] " REPLY
REPLY="${REPLY:-Y}"
if [[ "$REPLY" =~ ^[Yy] ]]; then
    exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/setup.py"
fi
