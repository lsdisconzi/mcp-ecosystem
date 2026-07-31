#!/usr/bin/env bash
# OCR — start backend service
# Standardized start script (compatible with ops-dashboard)
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Optional .env overrides
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a; source "$SCRIPT_DIR/.env"; set +a
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8098}"
APP_URL="${APP_URL:-http://${HOST}:${PORT}/docs}"
VENV_BIN="$SCRIPT_DIR/.venv/bin"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"
REQUIREMENTS_STAMP="$SCRIPT_DIR/.venv/.requirements-stamp"

# Source centralized logging
source "$SCRIPT_DIR/../.dev-logs/common-logging.sh"

mkdir -p "$(dirname "$(get_log_file "ocr" "main")")"

# ── stop any existing instance ───────────────────────────────────────────────
"$SCRIPT_DIR/stop.sh" --quiet || true

# ── python venv ──────────────────────────────────────────────────────────────
if [[ ! -x "$VENV_BIN/python" ]]; then
    echo "Creating Python venv…"
    python3 -m venv "$SCRIPT_DIR/.venv"
fi
if [[ -f "$REQUIREMENTS_FILE" ]]; then
    if [[ ! -f "$REQUIREMENTS_STAMP" || "$REQUIREMENTS_FILE" -nt "$REQUIREMENTS_STAMP" ]]; then
        echo "Installing Python dependencies…"
        "$VENV_BIN/pip" install -q --upgrade pip
        "$VENV_BIN/pip" install -q --prefer-binary -r "$REQUIREMENTS_FILE"
        touch "$REQUIREMENTS_STAMP"
    fi
fi

# ── start backend ────────────────────────────────────────────────────────────
echo "Starting OCR service on :${PORT}…"
start_logging "ocr" "main" env PYTHONUNBUFFERED=1 \
    "$VENV_BIN/uvicorn" ocr_server:app --host "$HOST" --port "$PORT"

# ── wait until backend is ready (up to 15 s) ─────────────────────────────────
echo "Waiting for backend…"
for i in $(seq 1 30); do
    if curl -sf "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

echo ""
echo "OCR service is running."
echo "  URL  : $APP_URL"
echo "  Logs : .dev-logs/ocr/"
echo "  Stop : ./stop.sh"