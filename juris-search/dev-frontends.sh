#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

TJRS_FRONTEND_DIR="$SCRIPT_DIR/tjrs-frontend"

DEV_HOST="${JURIS_SEARCH_DEV_HOST:-0.0.0.0}"
TJRS_DEV_PORT="${TJRS_FRONTEND_DEV_PORT:-5178}"

require_frontend() {
    local frontend_dir="$1"
    local frontend_name="$2"

    if [[ ! -d "$frontend_dir" ]]; then
        echo "missing $frontend_name directory: $frontend_dir" >&2
        exit 1
    fi

    if [[ ! -f "$frontend_dir/package.json" ]]; then
        echo "missing $frontend_name package.json: $frontend_dir/package.json" >&2
        exit 1
    fi
}

ensure_node_deps() {
    local frontend_dir="$1"
    local frontend_name="$2"

    if [[ ! -d "$frontend_dir/node_modules" ]]; then
        echo "[$frontend_name] installing dependencies..."
        (cd "$frontend_dir" && npm install)
    fi
}

if ! command -v npm >/dev/null 2>&1; then
    echo "npm is required to run frontend dev servers" >&2
    exit 1
fi

require_frontend "$TJRS_FRONTEND_DIR" "tjrs-frontend"

ensure_node_deps "$TJRS_FRONTEND_DIR" "tjrs-frontend"

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM
    if [[ -n "${TJRS_PID:-}" ]]; then
        kill "$TJRS_PID" 2>/dev/null || true
    fi
    wait 2>/dev/null || true
    exit "$exit_code"
}

trap cleanup EXIT INT TERM

echo "starting frontend with hot reload"
echo "- tjrs-frontend: http://$DEV_HOST:$TJRS_DEV_PORT"

(
    cd "$TJRS_FRONTEND_DIR"
    npm run dev -- --host "$DEV_HOST" --port "$TJRS_DEV_PORT" --strictPort
) &
TJRS_PID=$!

wait "$TJRS_PID"
