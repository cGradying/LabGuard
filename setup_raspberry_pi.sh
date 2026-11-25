#!/usr/bin/env bash
# ==============================================================================
# LabGuard+ — Raspberry Pi Automated Installer
# Arellano University - Jose Rizal Campus (SHS & General Science Laboratory)
#
# Tested for Raspberry Pi OS Bullseye, Bookworm, and Trixie (32-bit & 64-bit)
# Compatible with Raspberry Pi 2B, Pi 3B/3B+, Pi 4B, Pi 5, and Pi Zero 2 W
# Optimized for 1GB RAM models (Pi 2 Model B & Pi 3 Model B/B+, 32-bit) as well
# as Pi 4B, Pi 5, and Pi Zero 2 W
#
# Usage:
#   sudo bash setup_raspberry_pi.sh [--no-kiosk] [--port 5000] [--app-url URL]
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# Parse CLI arguments
# ------------------------------------------------------------------------------
NO_KIOSK=0
PORT=5000
PORT_EXPLICIT=0
APP_URL=""
APP_URL_EXPLICIT=0

usage() {
  cat <<'EOF'
LabGuard+ Raspberry Pi Installer

Usage:
  sudo bash setup_raspberry_pi.sh [OPTIONS]

Options:
  --no-kiosk         Install backend service only (headless/server mode; skips
                     Chromium kiosk package install and desktop autostart).
  --port <PORT>      TCP port for the LabGuard+ server (default: 5000).
  --app-url <URL>    Fixed public base URL for Checkout QR codes
                     (e.g. http://labguard.local:5000). Leave unset for
                     automatic LAN IP detection.
  -h, --help         Show this help message and exit.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-kiosk)
      NO_KIOSK=1
      shift
      ;;
    --port)
      if [[ $# -lt 2 ]]; then
        echo "[!] Error: --port requires a value." >&2
        exit 1
      fi
      PORT="$2"
      PORT_EXPLICIT=1
      shift 2
      ;;
    --port=*)
      PORT="${1#*=}"
      PORT_EXPLICIT=1
      shift
      ;;
    --app-url)
      if [[ $# -lt 2 ]]; then
        echo "[!] Error: --app-url requires a value." >&2
        exit 1
      fi
      APP_URL="$2"
      APP_URL_EXPLICIT=1
      shift 2
      ;;
    --app-url=*)
      APP_URL="${1#*=}"
      APP_URL_EXPLICIT=1
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

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "[!] Error: --port must be a valid TCP port number (1-65535), got: $PORT" >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# Require root & resolve target user / directories
# ------------------------------------------------------------------------------
if [[ "${EUID}" -ne 0 ]]; then
  echo "[!] Please run this installer as root:"
  echo "    sudo bash setup_raspberry_pi.sh"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="/opt/labguard"
DATA_DIR="/var/lib/labguard"
ENV_FILE="/etc/default/labguard"
SERVICE_FILE="/etc/systemd/system/labguard.service"

if [[ ! -f "$SCRIPT_DIR/app.py" || ! -f "$SCRIPT_DIR/requirements.txt" ]]; then
  echo "[!] Error: app.py or requirements.txt not found in $SCRIPT_DIR" >&2
  echo "    Please run this script from the LabGuard repository directory." >&2
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
if [[ -z "$TARGET_USER" ]]; then
  echo "[!] Error: Could not determine a non-root Raspberry Pi user." >&2
  echo "    Run with: sudo bash setup_raspberry_pi.sh (from your regular Pi user account)." >&2
  exit 1
fi

USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
if [[ -z "$USER_HOME" || ! -d "$USER_HOME" ]]; then
  echo "[!] Error: Home directory for user '$TARGET_USER' could not be resolved." >&2
  exit 1
fi

# Helper: check whether an apt package has an installable candidate
apt_has_candidate() {
  local pkg="$1"
  local candidate
  candidate="$(apt-cache policy "$pkg" 2>/dev/null | awk '/Candidate:/ { print $2; exit }')"
  [[ -n "$candidate" && "$candidate" != "(none)" ]]
}

# Helper: install packages that exist in apt without failing on optional ones
apt_install_optional() {
  local available=()
  local pkg
  for pkg in "$@"; do
    if apt_has_candidate "$pkg"; then
      available+=("$pkg")
    else
      echo "    [i] Optional package '$pkg' not available on this OS release — skipping."
    fi
  done
  if (( ${#available[@]} > 0 )); then
    if ! DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${available[@]}"; then
      echo "    [i] Batch optional install encountered a package conflict — retrying individually..."
      for pkg in "${available[@]}"; do
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$pkg" || \
          echo "    [!] Warning: Could not install optional package: $pkg"
      done
    fi
  fi
}

# ------------------------------------------------------------------------------
# Detect Raspberry Pi hardware model, CPU architecture, RAM, and Swap
# ------------------------------------------------------------------------------
PI_MODEL="Unknown (non-Raspberry Pi host)"
if [[ -r /proc/device-tree/model ]]; then
  RAW_MODEL="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null | sed 's/[[:space:]]*$//' || true)"
  if [[ -n "$RAW_MODEL" ]]; then
    PI_MODEL="$RAW_MODEL"
  fi
fi

CPU_ARCH="$(uname -m 2>/dev/null || echo 'unknown')"

MEM_MB="$(LC_ALL=C free -m 2>/dev/null | awk '/^Mem:/ { print $2; exit }' || true)"
if ! [[ "$MEM_MB" =~ ^[0-9]+$ ]]; then
  MEM_MB="$(awk '/^MemTotal:/ { printf "%d", $2/1024; exit }' /proc/meminfo 2>/dev/null || echo 0)"
fi

SWAP_MB="$(LC_ALL=C free -m 2>/dev/null | awk '/^Swap:/ { print $2; exit }' || true)"
if ! [[ "$SWAP_MB" =~ ^[0-9]+$ ]]; then
  SWAP_MB="$(awk '/^SwapTotal:/ { printf "%d", $2/1024; exit }' /proc/meminfo 2>/dev/null || echo 0)"
fi

LOW_RAM_PI=0
RAM_NOTE=""
if [[ "$MEM_MB" =~ ^[0-9]+$ ]] && (( MEM_MB > 0 && MEM_MB <= 1100 )); then
  LOW_RAM_PI=1
  RAM_NOTE=" (low-RAM Pi 2/3/Zero 2 W optimization enabled)"
fi

KIOSK_LABEL="Enabled (Chromium fullscreen)"
if (( NO_KIOSK == 1 )); then
  KIOSK_LABEL="Disabled (--no-kiosk)"
fi

ID_PHOTOS_DIR="${DATA_DIR}/id_photos"

echo "=================================================================="
echo "  LabGuard+ — Raspberry Pi Automated Setup"
echo "  Arellano University - Jose Rizal Campus"
echo "=================================================================="
echo "  Board model : $PI_MODEL"
echo "  CPU arch    : $CPU_ARCH"
echo "  Memory      : ${MEM_MB} MB RAM / ${SWAP_MB} MB Swap${RAM_NOTE}"
echo "  Target user : $TARGET_USER ($USER_HOME)"
echo "  Install dir : $APP_DIR"
echo "  Data dir    : $DATA_DIR (ID photos: $ID_PHOTOS_DIR)"
echo "  Kiosk mode  : $KIOSK_LABEL"
echo "  Default port: $PORT"
echo "=================================================================="

# ------------------------------------------------------------------------------
# 1. Install system packages (Bullseye / Bookworm / Trixie compatible)
# ------------------------------------------------------------------------------
echo ""
echo "[1/7] Updating apt cache and installing system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y

CORE_PKGS=(
  python3
  python3-venv
  python3-pip
  python3-pil
  python3-gpiozero
  curl
  rsync
  avahi-daemon
)
apt-get install -y "${CORE_PKGS[@]}"

# Optional GPIO backends:
#   - python3-rpi.gpio  : Pi 2/3 Bullseye (RPi.GPIO)
#   - python3-rpi-lgpio : Pi 2/3/4 Bookworm/Trixie (lgpio-backed RPi.GPIO shim)
#   - python3-lgpio     : Pi 5 & Bookworm/Trixie native lgpio
apt_install_optional python3-rpi.gpio python3-rpi-lgpio python3-lgpio

if (( NO_KIOSK == 0 )); then
  echo "    Installing Chromium kiosk & display utilities..."
  if apt_has_candidate chromium; then
    apt-get install -y chromium
  elif apt_has_candidate chromium-browser; then
    apt-get install -y chromium-browser
  else
    echo "    [!] Warning: Neither 'chromium' nor 'chromium-browser' found in apt."
    echo "        Install Chromium manually if you plan to use Touchscreen Kiosk mode."
  fi
  apt_install_optional unclutter x11-xserver-utils
fi

# ------------------------------------------------------------------------------
# 2. Sync application files & create persistent data directory
# ------------------------------------------------------------------------------
echo ""
echo "[2/7] Deploying application files to $APP_DIR and preparing $DATA_DIR..."
mkdir -p "$APP_DIR" "$DATA_DIR" "$ID_PHOTOS_DIR"

REAL_SRC="$(readlink -f "$SCRIPT_DIR")"
REAL_DST="$(readlink -f "$APP_DIR")"
if [[ "$REAL_SRC" != "$REAL_DST" ]]; then
  rsync -a --delete \
    --exclude '.git' \
    --exclude 'node_modules' \
    --exclude '.venv' \
    --exclude 'id_photos' \
    --exclude 'labguard.db' \
    --exclude 'labguard.db-wal' \
    --exclude 'labguard.db-shm' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    "$SCRIPT_DIR/" "$APP_DIR/"
else
  echo "    [i] Running directly from $APP_DIR — skipping rsync."
fi

chown -R "${TARGET_USER}:${TARGET_USER}" "$APP_DIR" "$DATA_DIR"
chmod 750 "$ID_PHOTOS_DIR"

if getent group gpio >/dev/null 2>&1; then
  usermod -aG gpio "$TARGET_USER"
  echo "    Added '$TARGET_USER' to 'gpio' group."
else
  echo "    [i] 'gpio' group not present on this host — skipping group assignment."
fi

# ------------------------------------------------------------------------------
# 3. Create Python virtual environment (--system-site-packages for PEP 668 + GPIO)
# ------------------------------------------------------------------------------
echo ""
echo "[3/7] Setting up Python virtual environment at $APP_DIR/.venv..."
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  python3 -m venv --system-site-packages "$APP_DIR/.venv"
fi

"$APP_DIR/.venv/bin/pip" install --disable-pip-version-check --no-cache-dir \
  -r "$APP_DIR/requirements.txt"

chown -R "${TARGET_USER}:${TARGET_USER}" "$APP_DIR/.venv"

# ------------------------------------------------------------------------------
# 4. Create /etc/default/labguard (preserve existing settings on re-runs)
# ------------------------------------------------------------------------------
echo ""
echo "[4/7] Configuring $ENV_FILE..."
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<EOF
# LabGuard+ Raspberry Pi Service Configuration
# After editing this file, restart the service:
#   sudo systemctl restart labguard

# HTTP server port
PORT=${PORT}

# Optional fixed public base URL for Checkout/Return/Registration QR codes
# Leave blank to auto-detect the Raspberry Pi's active LAN IPv4 address.
# Example: APP_URL=http://labguard.local:${PORT}
APP_URL=${APP_URL}

# Persistent data directory (SQLite database + student School ID photos)
LABGUARD_DATA_DIR=${DATA_DIR}
LABGUARD_DB_PATH=${DATA_DIR}/labguard.db

# Laboratory Admin Credentials (CHANGE LABGUARD_ADMIN_PASSWORD before school deployment!)
LABGUARD_ADMIN_EMAIL=lara.puertollano@arellano.edu.ph
LABGUARD_ADMIN_PASSWORD=au-jrc-2026
LABGUARD_ADMIN_NAME="Ms. Lara Marie A. Puertollano"

# Raspberry Pi GPIO Control (Pi 2B, Pi 3B/3B+, Pi 4B, Pi 5, Pi Zero 2 W)
# NOTE: All 12 Locker GPIO lock pins, polarity (Active-LOW/Active-HIGH), unlock
#       pulse duration, 3 Safety Status LEDs, and Buzzer are live-configurable
#       inside /admin -> GPIO & Locker Hardware (persisted in SQLite) with zero
#       code edits or reboots.
# LABGUARD_GPIO_ENABLED: auto (real GPIO on Pi, simulate elsewhere), 1 (force on), 0 (disable)
LABGUARD_GPIO_ENABLED=auto

# Initial fallback LED & Buzzer BCM GPIO defaults (overridden once saved in /admin)
LABGUARD_LED_GREEN_PIN=17
LABGUARD_LED_YELLOW_PIN=27
LABGUARD_LED_RED_PIN=22
LABGUARD_BUZZER_PIN=23
LABGUARD_BUZZER_ENABLED=1
LABGUARD_LED_ACTIVE_HIGH=1
EOF
  chown "root:${TARGET_USER}" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
  echo "    Created $ENV_FILE (permissions 640, root:${TARGET_USER})"
else
  chown "root:${TARGET_USER}" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
  echo "    [i] $ENV_FILE already exists — preserving your existing settings (permissions 640)."
  EXISTING_PORT="$(grep -E '^[[:space:]]*PORT=' "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '[:space:]"'\''' || true)"
  if [[ -n "$EXISTING_PORT" && "$EXISTING_PORT" =~ ^[0-9]+$ ]]; then
    if (( PORT_EXPLICIT == 1 )) && [[ "$EXISTING_PORT" != "$PORT" ]]; then
      echo "    [!] Note: --port $PORT was passed, but $ENV_FILE already sets PORT=$EXISTING_PORT."
      echo "        Edit $ENV_FILE and run 'sudo systemctl restart labguard' to change the port."
    fi
    PORT="$EXISTING_PORT"
  fi
  if (( APP_URL_EXPLICIT == 1 )); then
    echo "    [!] Note: --app-url was passed, but $ENV_FILE already exists and was preserved."
    echo "        Edit APP_URL in $ENV_FILE and run 'sudo systemctl restart labguard' to change it."
  fi
fi

# ------------------------------------------------------------------------------
# 5. Configure Avahi (mDNS) and systemd service
# ------------------------------------------------------------------------------
echo ""
echo "[5/7] Enabling avahi-daemon and creating labguard.service..."

systemctl enable avahi-daemon >/dev/null 2>&1 || true
systemctl restart avahi-daemon >/dev/null 2>&1 || true

# Disable legacy au-inventory.service if present
if systemctl list-unit-files 2>/dev/null | grep -q '^au-inventory\.service' || [[ -f /etc/systemd/system/au-inventory.service ]]; then
  echo "    Disabling legacy au-inventory.service..."
  systemctl stop au-inventory.service >/dev/null 2>&1 || true
  systemctl disable au-inventory.service >/dev/null 2>&1 || true
fi

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=LabGuard+ Smart Science Laboratory Safety Station & QR Kiosk
After=network-online.target avahi-daemon.service
Wants=network-online.target

[Service]
Type=simple
User=${TARGET_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=-${ENV_FILE}
Environment=PYTHONUNBUFFERED=1
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/app.py
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable labguard.service
systemctl restart labguard.service

echo "    Waiting for LabGuard+ backend on http://localhost:${PORT}/api/health..."
HEALTH_OK=0
for _ in $(seq 1 25); do
  if curl -fsS "http://localhost:${PORT}/api/health" >/dev/null 2>&1; then
    HEALTH_OK=1
    break
  fi
  sleep 1
done

if (( HEALTH_OK == 1 )); then
  echo "    [OK] Backend is healthy and responding on port ${PORT}."
else
  echo "    [!] Warning: http://localhost:${PORT}/api/health did not respond within 25s."
  echo "        Inspect service logs with: journalctl -u labguard -n 50 --no-pager"
fi

# ------------------------------------------------------------------------------
# 6. Configure Touchscreen Kiosk Autostart (Wayland labwc/wayfire + X11 LXDE)
# ------------------------------------------------------------------------------
if (( NO_KIOSK == 0 )); then
  echo ""
  echo "[6/7] Configuring Chromium Touchscreen Kiosk autostart..."

  KIOSK_SCRIPT="${USER_HOME}/labguard_kiosk.sh"
  AUTOSTART_DIR="${USER_HOME}/.config/autostart"
  DESKTOP_FILE="${AUTOSTART_DIR}/labguard-kiosk.desktop"

  cat > "$KIOSK_SCRIPT" <<'EOF'
#!/usr/bin/env bash
# ==============================================================================
# LabGuard+ Touchscreen Kiosk Launcher (Wayland & X11 compatible)
# ==============================================================================

set -u

PORT=5000
if [[ -r /etc/default/labguard ]]; then
  CFG_PORT="$(grep -E '^[[:space:]]*PORT=' /etc/default/labguard | tail -n1 | cut -d= -f2- | tr -d '[:space:]"'\''' || true)"
  if [[ -n "$CFG_PORT" && "$CFG_PORT" =~ ^[0-9]+$ ]]; then
    PORT="$CFG_PORT"
  fi
fi

KIOSK_URL="http://localhost:${PORT}/kiosk?kiosk=1"
HEALTH_URL="http://localhost:${PORT}/api/health"

# Avoid duplicate kiosk launches
LOCK_FILE="/tmp/labguard-kiosk-${USER:-pi}.lock"
exec 9>"$LOCK_FILE"
if command -v flock >/dev/null 2>&1; then
  if ! flock -n 9; then
    exit 0
  fi
fi

# Wait up to 45 seconds for LabGuard+ backend to be ready
for _ in $(seq 1 45); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Detect Chromium binary across Bullseye (chromium-browser) and Bookworm/Trixie (chromium)
CHROMIUM_BIN=""
if command -v chromium >/dev/null 2>&1; then
  CHROMIUM_BIN="$(command -v chromium)"
elif command -v chromium-browser >/dev/null 2>&1; then
  CHROMIUM_BIN="$(command -v chromium-browser)"
else
  echo "[LabGuard+] Error: Neither 'chromium' nor 'chromium-browser' is installed." >&2
  exit 1
fi

# On X11 sessions, disable screen blanking and auto-hide the mouse cursor
if [[ -n "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" && "${XDG_SESSION_TYPE:-}" != "wayland" ]]; then
  if command -v xset >/dev/null 2>&1; then
    xset s off || true
    xset -dpms || true
    xset s noblank || true
  fi
  if command -v unclutter >/dev/null 2>&1; then
    pkill -x unclutter >/dev/null 2>&1 || true
    unclutter -idle 0.5 -root >/dev/null 2>&1 &
  fi
fi

# Clear Chromium crash flags so "Restore pages?" bubble never appears
PREFS_FILE="${HOME}/.config/chromium/Default/Preferences"
if [[ -f "$PREFS_FILE" ]]; then
  sed -i 's/"exited_cleanly":false/"exited_cleanly":true/g' "$PREFS_FILE" || true
  sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/g' "$PREFS_FILE" || true
fi

CHROMIUM_FLAGS=(
  --ozone-platform-hint=auto
  --touch-events=enabled
  --kiosk
  --noerrdialogs
  --disable-infobars
  --disable-session-crashed-bubble
  --no-first-run
  --disable-pinch
  --overscroll-history-navigation=0
  --check-for-update-interval=31536000
  --password-store=basic
)

# Detect total RAM and append low-memory flags on 1GB / 512MB Raspberry Pis
# (Pi 2B, Pi 3B/3B+, Pi Zero 2 W) so Chromium stays responsive without OOM crashes
MEM_MB=$(awk '/MemTotal:/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo 2048)
if [[ "$MEM_MB" =~ ^[0-9]+$ ]] && (( MEM_MB <= 1100 )); then
  CHROMIUM_FLAGS+=(
    --disable-background-networking
    --disable-sync
    --disable-extensions
    --disable-default-apps
    --no-default-browser-check
    --disable-translate
    --js-flags=--max-old-space-size=256
  )
fi

exec "$CHROMIUM_BIN" "${CHROMIUM_FLAGS[@]}" "$KIOSK_URL"
EOF

  chmod +x "$KIOSK_SCRIPT"
  chown "${TARGET_USER}:${TARGET_USER}" "$KIOSK_SCRIPT"

  mkdir -p "$AUTOSTART_DIR"

  # Remove legacy kiosk.desktop if present to avoid launching old script
  if [[ -f "${AUTOSTART_DIR}/kiosk.desktop" ]]; then
    rm -f "${AUTOSTART_DIR}/kiosk.desktop"
  fi

  cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=LabGuard+ Touchscreen Kiosk
Comment=Start LabGuard+ Science Laboratory Kiosk in fullscreen Chromium
Exec=/bin/bash ${KIOSK_SCRIPT}
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

  chown "${TARGET_USER}:${TARGET_USER}" "${USER_HOME}/.config"
  chown -R "${TARGET_USER}:${TARGET_USER}" "$AUTOSTART_DIR"

  # Disable screen blanking system-wide when raspi-config is available
  if command -v raspi-config >/dev/null 2>&1; then
    echo "    Disabling display screen blanking via raspi-config..."
    raspi-config nonint do_blanking 1 >/dev/null 2>&1 || true
  fi
else
  echo ""
  echo "[6/7] Skipping Chromium kiosk autostart (--no-kiosk selected)."
fi

# ------------------------------------------------------------------------------
# 7. Print completion banner
# ------------------------------------------------------------------------------
echo ""
echo "[7/7] Finalizing setup..."

LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
if [[ -z "$LAN_IP" ]]; then
  LAN_IP="<pi-ip-address>"
fi
HOST_SHORT="$(hostname -s 2>/dev/null || hostname || echo 'labguard')"
MDNS_HOST="${HOST_SHORT}.local"

echo ""
echo "=================================================================="
echo "  LABGUARD+ RASPBERRY PI SETUP COMPLETE!"
echo "=================================================================="
echo "  Board / Memory  : ${PI_MODEL} (${CPU_ARCH}, ${MEM_MB} MB RAM / ${SWAP_MB} MB Swap)"
echo "  Backend Service : labguard.service (active on port ${PORT})"
echo "  Database Path   : ${DATA_DIR}/labguard.db"
echo "  ID Photos Dir   : ${ID_PHOTOS_DIR} (chmod 750)"
echo "  Config File     : ${ENV_FILE} (chmod 640)"
echo ""
echo "  Access URLs:"
echo "    Kiosk (local) : http://localhost:${PORT}/kiosk?kiosk=1"
echo "    LAN URL       : http://${LAN_IP}:${PORT}"
echo "    mDNS URL      : http://${MDNS_HOST}:${PORT}"
echo "    Student Reg.  : http://${LAN_IP}:${PORT}/student/register"
echo "    Student Portal: http://${LAN_IP}:${PORT}/student/account"
echo "    Admin Console : http://${LAN_IP}:${PORT}/admin"
echo "                    http://${MDNS_HOST}:${PORT}/admin"
echo "    Health Check  : http://localhost:${PORT}/api/health"
echo "    Hardware API  : http://localhost:${PORT}/api/hardware/status"
echo ""
echo "  Default Demo Admin Login:"
echo "    Email         : lara.puertollano@arellano.edu.ph"
echo "    Password      : au-jrc-2026"
echo "    [!] SECURITY  : Change LABGUARD_ADMIN_PASSWORD in ${ENV_FILE}"
echo "                    and run 'sudo systemctl restart labguard' before"
echo "                    school deployment!"
echo ""
echo "  GPIO & Locker Hardware:"
echo "    Configure and test all 12 locker lock pins, polarity (Active-LOW /"
echo "    Active-HIGH), unlock pulse duration, LEDs, and buzzer live in:"
echo "      /admin -> GPIO & Locker Hardware (saved to SQLite, no coding needed)"
if (( LOW_RAM_PI == 1 )) && [[ "$SWAP_MB" =~ ^[0-9]+$ ]] && (( SWAP_MB < 512 )); then
  echo ""
  echo "  [!] Low-Swap Tip for Raspberry Pi 2/3 (${MEM_MB} MB RAM, ${SWAP_MB} MB Swap):"
  echo "      If Chromium feels slow on your 1GB Raspberry Pi, bump swap to 1024 MB:"
  echo "        sudo dphys-swapfile swapoff"
  echo "        sudo sed -i 's/^#\?CONF_SWAPSIZE=.*/CONF_SWAPSIZE=1024/' /etc/dphys-swapfile"
  echo "        sudo dphys-swapfile setup && sudo dphys-swapfile swapon"
fi
echo ""
echo "  Useful Commands:"
echo "    Service status: sudo systemctl status labguard"
echo "    Restart app   : sudo systemctl restart labguard"
echo "    Live logs     : journalctl -u labguard -f"
echo "    Edit settings : sudo nano ${ENV_FILE}"
if (( NO_KIOSK == 0 )); then
  echo ""
  echo "  Reboot now to launch the fullscreen Touchscreen Kiosk:"
  echo "    sudo reboot"
fi
echo "=================================================================="
