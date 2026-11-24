#!/usr/bin/env bash
# ==============================================================================
# LabGuard+ — Local PC Launcher (macOS / Linux)
# Runs the Raspberry Pi Python Flask backend (app.py) inside a local .venv
# ==============================================================================

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Load optional .env file if present
if [[ -f "$DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$DIR/.env"
  set +a
fi

PORT="${PORT:-5000}"
export PORT

echo "=================================================================="
echo "  LabGuard+ Smart Science Laboratory Kiosk — Local Runner"
echo "  Arellano University - Jose Rizal Campus"
echo "=================================================================="

if ! command -v python3 >/dev/null 2>&1; then
  echo "[!] Error: python3 is not installed on this system." >&2
  echo "    Please install Python 3.9+ from https://www.python.org" >&2
  exit 1
fi

echo "[+] Detected: $(python3 --version)"

# Auto-create local virtual environment if missing
if [[ ! -x "$DIR/.venv/bin/python" ]]; then
  echo "[+] Creating local virtual environment in .venv..."
  python3 -m venv "$DIR/.venv"
fi

# Install dependencies if missing or requirements.txt changed
if ! "$DIR/.venv/bin/python" -c "import flask, flask_sock, qrcode" >/dev/null 2>&1; then
  echo "[+] Installing Python dependencies from requirements.txt..."
  "$DIR/.venv/bin/pip" install --disable-pip-version-check -r "$DIR/requirements.txt"
fi

echo "[+] Starting LabGuard+ Python server on http://localhost:${PORT}"
echo "    Kiosk UI  : http://localhost:${PORT}/kiosk"
echo "    Admin UI  : http://localhost:${PORT}/admin"
echo "    Health API: http://localhost:${PORT}/api/health"
echo "    Press Ctrl+C to stop."
echo ""

# Open default browser once the server is ready
(
  for _ in $(seq 1 20); do
    if command -v curl >/dev/null 2>&1 && curl -fsS "http://localhost:${PORT}/api/health" >/dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done
  if command -v open >/dev/null 2>&1; then
    open "http://localhost:${PORT}/kiosk" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://localhost:${PORT}/kiosk" >/dev/null 2>&1 || true
  fi
) &

exec "$DIR/.venv/bin/python" "$DIR/app.py"
