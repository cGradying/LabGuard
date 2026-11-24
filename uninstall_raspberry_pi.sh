#!/usr/bin/env bash
# ==============================================================================
# LabGuard+ — Raspberry Pi Uninstaller
#
# Stops and removes labguard.service, Chromium kiosk autostart files, and
# /opt/labguard. Preserves /var/lib/labguard/labguard.db and /etc/default/labguard
# unless --purge-data is passed (or confirmed interactively).
#
# Usage:
#   sudo bash uninstall_raspberry_pi.sh [--purge-data] [-y|--yes]
# ==============================================================================

set -euo pipefail

PURGE_DATA=0
ASSUME_YES=0

usage() {
  cat <<'EOF'
LabGuard+ Raspberry Pi Uninstaller

Usage:
  sudo bash uninstall_raspberry_pi.sh [OPTIONS]

Options:
  --purge-data   Also delete /var/lib/labguard (SQLite database) and
                 /etc/default/labguard without prompting.
  -y, --yes      Non-interactive mode (keeps database unless --purge-data is set).
  -h, --help     Show this help message and exit.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge-data)
      PURGE_DATA=1
      shift
      ;;
    -y|--yes)
      ASSUME_YES=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[!] Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "[!] Please run this uninstaller as root:"
  echo "    sudo bash uninstall_raspberry_pi.sh"
  exit 1
fi

resolve_target_user() {
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]] && id "${SUDO_USER}" >/dev/null 2>&1; then
    echo "${SUDO_USER}"
    return 0
  fi
  local uid1000
  uid1000="$(awk -F: '$3 == 1000 { print $1; exit }' /etc/passwd || true)"
  if [[ -n "$uid1000" ]] && id "$uid1000" >/dev/null 2>&1; then
    echo "$uid1000"
    return 0
  fi
  if id pi >/dev/null 2>&1; then
    echo "pi"
    return 0
  fi
  return 1
}

TARGET_USER="$(resolve_target_user || true)"
USER_HOME=""
if [[ -n "$TARGET_USER" ]]; then
  USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6 || true)"
fi

APP_DIR="/opt/labguard"
DATA_DIR="/var/lib/labguard"
ENV_FILE="/etc/default/labguard"

echo "=================================================================="
echo "  LabGuard+ — Raspberry Pi Uninstaller"
echo "=================================================================="

# 1. Stop and disable systemd services
echo "[1/4] Stopping and removing systemd service..."
for svc in labguard.service au-inventory.service; do
  if systemctl list-unit-files 2>/dev/null | grep -q "^${svc}" || [[ -f "/etc/systemd/system/${svc}" ]]; then
    systemctl stop "$svc" >/dev/null 2>&1 || true
    systemctl disable "$svc" >/dev/null 2>&1 || true
    rm -f "/etc/systemd/system/${svc}"
    echo "    Removed /etc/systemd/system/${svc}"
  fi
done
systemctl daemon-reload

# 2. Remove kiosk autostart entries and launcher script
echo "[2/4] Removing kiosk autostart files..."
if [[ -n "$USER_HOME" && -d "$USER_HOME" ]]; then
  for f in \
    "${USER_HOME}/.config/autostart/labguard-kiosk.desktop" \
    "${USER_HOME}/.config/autostart/kiosk.desktop" \
    "${USER_HOME}/labguard_kiosk.sh" \
    "${USER_HOME}/kiosk_startup.sh"; do
    if [[ -f "$f" ]]; then
      rm -f "$f"
      echo "    Removed $f"
    fi
  done
else
  echo "    [i] Could not determine user home directory — skipped autostart cleanup."
fi

# 3. Remove application directory
echo "[3/4] Removing application directory ($APP_DIR)..."
if [[ -d "$APP_DIR" ]]; then
  rm -rf "$APP_DIR"
  echo "    Removed $APP_DIR"
else
  echo "    [i] $APP_DIR not found — already removed."
fi

# 4. Handle persistent database & config
echo "[4/4] Handling database ($DATA_DIR) and config ($ENV_FILE)..."
DELETE_DATA=$PURGE_DATA
if (( DELETE_DATA == 0 && ASSUME_YES == 0 )) && [[ -t 0 ]] && [[ -d "$DATA_DIR" || -f "$ENV_FILE" ]]; then
  echo ""
  read -r -p "    Also permanently delete ${DATA_DIR}/labguard.db and ${ENV_FILE}? [y/N]: " REPLY
  case "${REPLY:-N}" in
    y|Y|yes|YES)
      DELETE_DATA=1
      ;;
    *)
      DELETE_DATA=0
      ;;
  esac
fi

if (( DELETE_DATA == 1 )); then
  rm -rf "$DATA_DIR"
  rm -f "$ENV_FILE"
  echo "    Purged $DATA_DIR and $ENV_FILE."
else
  echo "    Preserved database and settings:"
  [[ -d "$DATA_DIR" ]] && echo "      - $DATA_DIR"
  [[ -f "$ENV_FILE" ]] && echo "      - $ENV_FILE"
  echo "    (Re-run with --purge-data if you want to remove them too.)"
fi

echo ""
echo "=================================================================="
echo "  LabGuard+ has been uninstalled."
echo "=================================================================="
