#!/usr/bin/env bash
# Discovery fresh-start helper:
# - clears session ingestion data under documents_scanned/sessions
# - clears generated artifacts under documents_scanned
# - restarts services cleanly
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DOCS_ROOT="$ROOT/documents_scanned"
SESSIONS_DIR="$DOCS_ROOT/sessions"
BOOT_WORKSPACE="$SESSIONS_DIR/_server_boot/workspace"
ASSUME_YES=false

for arg in "$@"; do
  case "$arg" in
    --yes|-y)
      ASSUME_YES=true
      ;;
    *)
      echo "Unknown option: $arg"
      echo "Usage: ./start-fresh.sh [--yes]"
      exit 2
      ;;
  esac
done

if [[ ! -d "$DOCS_ROOT" ]]; then
  echo "documents_scanned directory not found at: $DOCS_ROOT"
  exit 1
fi

if [[ "$ASSUME_YES" != true ]]; then
  echo "This will permanently remove user/session ingestion data:"
  echo "  - $SESSIONS_DIR/*"
  echo "  - generated artifacts in $DOCS_ROOT (_intelligence, .discovery, pipeline_store.json)"
  printf "Continue? [y/N] "
  read -r reply
  if [[ ! "$reply" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
  fi
fi

echo "Stopping services..."
"$ROOT/stop.sh"

echo "Cleaning sessions..."
mkdir -p "$SESSIONS_DIR"
find "$SESSIONS_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +

echo "Cleaning generated artifacts in documents_scanned..."
rm -rf "$DOCS_ROOT/_intelligence" "$DOCS_ROOT/.discovery"
rm -f "$DOCS_ROOT/pipeline_store.json"

# Recreate default isolated workspace expected by start.sh
echo "Recreating fresh workspace..."
mkdir -p "$BOOT_WORKSPACE"

echo "Starting services fresh..."
"$ROOT/start.sh"
