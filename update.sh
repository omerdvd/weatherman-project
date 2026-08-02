#!/usr/bin/env bash
# Check for and apply updates from GitHub, using git tags as release
# versions. Always shows a changelog preview and asks for confirmation
# before touching anything - never auto-applies.
#
# Usage: ./update.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
LOCK_FILE="$SCRIPT_DIR/.update.lock"

log() { printf '\033[1;32m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m==>\033[0m %s\n' "$1"; }
err() { printf '\033[1;31m==>\033[0m %s\n' "$1" >&2; }

cd "$SCRIPT_DIR"

if [ ! -d .git ]; then
    err "This doesn't look like a git checkout (no .git directory)."
    err "update.sh only works on installs created via 'git clone'."
    exit 1
fi

# Prevent overlapping runs (e.g. a scheduled check firing mid-update).
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    err "Another update is already in progress (lock: $LOCK_FILE)."
    exit 1
fi

log "Fetching tags from origin..."
git fetch origin --tags --quiet

LATEST_TAG="$(git tag --list 'v*' --sort=-version:refname | head -n1)"
if [ -z "$LATEST_TAG" ]; then
    err "No release tags (vX.Y.Z) found on origin. Nothing to update to."
    exit 1
fi

CURRENT_REF="$(git describe --tags --exact-match 2>/dev/null || true)"
if [ -z "$CURRENT_REF" ]; then
    CURRENT_REF="$(git rev-parse --short HEAD)"
    warn "Current checkout isn't exactly on a release tag (at $CURRENT_REF)."
fi

log "Current: $CURRENT_REF"
log "Latest release: $LATEST_TAG"

if [ "$CURRENT_REF" = "$LATEST_TAG" ]; then
    log "Already up to date."
    exit 0
fi

echo
log "Changes between $CURRENT_REF and $LATEST_TAG:"
git log "${CURRENT_REF}..${LATEST_TAG}" --oneline || true
echo

CONFIG_DIFF="$(git diff "${CURRENT_REF}" "${LATEST_TAG}" -- config.example.yaml || true)"
if [ -n "$CONFIG_DIFF" ]; then
    warn "config.example.yaml has changed in this release. Your config.yaml is"
    warn "NOT modified automatically - review the diff below and add any new"
    warn "options to config.yaml yourself if you want them:"
    echo "$CONFIG_DIFF"
    echo
fi

REQS_CHANGED=0
if ! git diff --quiet "${CURRENT_REF}" "${LATEST_TAG}" -- requirements.txt 2>/dev/null; then
    REQS_CHANGED=1
    warn "requirements.txt has changed - Python dependencies will be reinstalled after updating."
fi

read -r -p "Update from $CURRENT_REF to $LATEST_TAG? [y/N] " REPLY
REPLY="${REPLY:-N}"
if [[ ! "$REPLY" =~ ^[Yy] ]]; then
    log "Aborted, no changes made."
    exit 0
fi

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    err "You have uncommitted changes to tracked files:"
    git status --porcelain --untracked-files=no >&2
    err "Commit, stash, or discard them before updating (config.yaml and"
    err "state.json are git-ignored and are never affected by this)."
    exit 1
fi

log "Checking out $LATEST_TAG..."
git checkout --quiet "$LATEST_TAG"

if [ "$REQS_CHANGED" -eq 1 ]; then
    if [ -x "$VENV_DIR/bin/pip" ]; then
        log "Reinstalling Python requirements..."
        "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
    else
        warn "No venv found at $VENV_DIR - install requirements.txt manually,"
        warn "or run ./install.sh again."
    fi
fi

echo
log "Updated to $LATEST_TAG."
log "Nothing needs restarting: systemd/cron both run weatherman.py fresh on"
log "each scheduled check, so the new code takes effect on the next run."

if [ -n "$CONFIG_DIFF" ] && [ -f "$SCRIPT_DIR/config.yaml" ]; then
    PYTHON_BIN="$VENV_DIR/bin/python"
    [ -x "$PYTHON_BIN" ] || PYTHON_BIN="python3"

    OLD_EXAMPLE_TMP="$(mktemp)"
    NEW_EXAMPLE_TMP="$(mktemp)"
    trap 'rm -f "$OLD_EXAMPLE_TMP" "$NEW_EXAMPLE_TMP"' EXIT
    git show "${CURRENT_REF}:config.example.yaml" > "$OLD_EXAMPLE_TMP" 2>/dev/null || true
    git show "${LATEST_TAG}:config.example.yaml" > "$NEW_EXAMPLE_TMP" 2>/dev/null || true

    NEW_KEYS="$("$PYTHON_BIN" "$SCRIPT_DIR/merge_config.py" \
        --old-example "$OLD_EXAMPLE_TMP" --new-example "$NEW_EXAMPLE_TMP" \
        --config "$SCRIPT_DIR/config.yaml" 2>&1)" && MERGE_RC=0 || MERGE_RC=$?

    if [ "$MERGE_RC" -eq 0 ]; then
        echo
        log "New config.yaml option(s) available in this release:"
        echo "$NEW_KEYS" | sed 's/^/    /'
        read -r -p "Add these to your config.yaml (a backup will be made first)? [y/N] " CONFIG_REPLY
        CONFIG_REPLY="${CONFIG_REPLY:-N}"
        if [[ "$CONFIG_REPLY" =~ ^[Yy] ]]; then
            BACKUP_PATH="$SCRIPT_DIR/config.yaml.bak.${CURRENT_REF}.$(date +%Y%m%d%H%M%S)"
            cp "$SCRIPT_DIR/config.yaml" "$BACKUP_PATH"
            log "Backed up config.yaml to $BACKUP_PATH"
            "$PYTHON_BIN" "$SCRIPT_DIR/merge_config.py" \
                --old-example "$OLD_EXAMPLE_TMP" --new-example "$NEW_EXAMPLE_TMP" \
                --config "$SCRIPT_DIR/config.yaml" --apply >/dev/null
            log "Added the new option(s) to config.yaml."
        else
            log "Skipped - config.yaml left unchanged."
        fi
    elif [ "$MERGE_RC" -ne 1 ]; then
        warn "Couldn't check for new config options: $NEW_KEYS"
        warn "Review the config.example.yaml diff above manually if needed."
    fi

    rm -f "$OLD_EXAMPLE_TMP" "$NEW_EXAMPLE_TMP"
    trap - EXIT
elif [ -n "$CONFIG_DIFF" ]; then
    warn "Remember to review the config.example.yaml diff above."
fi
