#!/usr/bin/env bash
#
# redownload_corrupted_pdfs.sh
# Re-downloads corrupted/truncated PDFs from tribunal websites,
# then triggers JSON rebuild and master-index rebuild.
#
# Usage:
#   chmod +x redownload_corrupted_pdfs.sh
#   ./redownload_corrupted_pdfs.sh            # dry-run by default
#   ./redownload_corrupted_pdfs.sh --run      # actually download
#
set -euo pipefail

# === CONFIGURATION ===
BASE_DIR="/home/disconzi1986_gmail_com/juris-search-VPS"
INDEX_FILE="${BASE_DIR}/json_jurisprudence/index.json"
API_URL="http://localhost:8000"
MCP_URL="http://localhost:8116/mcp"
MAX_RETRIES=3
DOWNLOAD_TIMEOUT=60
DELAY_BETWEEN_DOWNLOADS=1.0
BACKUP_SUFFIX=".corrupted.bak"
USER_AGENT="Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"

RUN=false
if [[ "${1:-}" == "--run" ]]; then
    RUN=true
    echo ">>> MODE: LIVE (will download files)"
else
    echo ">>> MODE: DRY-RUN (no changes will be made, pass --run to execute)"
fi

# === HELPERS ===
log() { echo "[$(date '+%H:%M:%S')] $*"; }

# MCP session handshake, returns session ID
mcp_session() {
    local headers
    headers=$(curl -si -X POST "$MCP_URL" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"redownload-script","version":"1.0"}}}' 2>/dev/null)
    echo "$headers" | grep -i 'mcp-session-id' | awk '{print $2}' | tr -d '\r\n'
}

mcp_notify() {
    curl -s -X POST "$MCP_URL" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -H "Mcp-Session-Id: $1" \
        -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' >/dev/null 2>&1
}

mcp_call() {
    local session=$1 tool=$2 args=$3
    curl -s -X POST "$MCP_URL" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -H "Mcp-Session-Id: $session" \
        -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"$tool\",\"arguments\":$args}}" 2>/dev/null
}

# === STEP 1: EXTRACT FAILED ENTRIES ===
log "Reading index: $INDEX_FILE"

if [[ ! -f "$INDEX_FILE" ]]; then
    echo "ERROR: Index file not found: $INDEX_FILE"
    exit 1
fi

# Build a list of: sidecar_path|download_url|pdf_path
ENTRIES=$(python3 -c "
import json, os, sys

with open('$INDEX_FILE') as f:
    data = json.load(f)

failed = [e for e in data.get('entries', [])
          if e.get('status') == 'failed'
          and 'EOF' in e.get('error', '')]

print(f'Total failed entries with EOF error: {len(failed)}', file=sys.stderr)

for e in failed:
    sidecar = e.get('source_sidecar_path', '')
    if not sidecar:
        continue

    # Derive PDF path: strip .metadata.json from sidecar
    pdf_path = sidecar
    if pdf_path.endswith('.metadata.json'):
        pdf_path = pdf_path[:-len('.metadata.json')]

    # Read download URL from sidecar
    url = ''
    try:
        with open(sidecar) as sf:
            meta = json.load(sf)
            url = meta.get('source_url', '') or meta.get('download_url', '')
    except Exception:
        pass

    if url:
        # sidecar_path|url|pdf_path
        print(f'{sidecar}|{url}|{pdf_path}')
" 2>&1)

# Separate stderr summary from data lines
SUMMARY=$(echo "$ENTRIES" | head -1)
DATA=$(echo "$ENTRIES" | tail -n +2 | grep '|')
TOTAL=$(echo "$DATA" | grep -c '|' || true)

log "$SUMMARY"
log "Entries with download URLs: $TOTAL"

if [[ "$TOTAL" -eq 0 ]]; then
    log "Nothing to do. All failed entries lack download URLs."
    exit 0
fi

# === DRY-RUN: SHOW WHAT WOULD BE DONE ===
if [[ "$RUN" == "false" ]]; then
    log "Dry-run: would re-download $TOTAL files"
    echo "$DATA" | head -5 | while IFS='|' read -r sidecar url pdf; do
        echo "  $pdf"
        echo "    <- $url"
    done
    if [[ "$TOTAL" -gt 5 ]]; then
        echo "  ... and $((TOTAL - 5)) more"
    fi
    echo ""
    log "Run with --run to execute."
    exit 0
fi

# === STEP 2: RE-DOWNLOAD FILES ===
log "Starting re-download of $TOTAL files..."
SUCCESS=0
FAILED_DL=0
SKIPPED=0

while IFS='|' read -r sidecar url pdf_path; do
    [[ -z "$url" || -z "$pdf_path" ]] && continue

    # Check if already valid
    if [[ -f "$pdf_path" ]]; then
        HEADER=$(head -c 4 "$pdf_path" 2>/dev/null || true)
        if [[ "$HEADER" == "%PDF" ]]; then
            # Check if it ends with %%EOF
            TAIL=$(tail -c 6 "$pdf_path" 2>/dev/null || true)
            if [[ "$TAIL" == *"%%EOF"* ]]; then
                SKIPPED=$((SKIPPED + 1))
                continue
            fi
        fi
    fi

    # Back up corrupted file
    if [[ -f "$pdf_path" ]]; then
        cp "$pdf_path" "${pdf_path}${BACKUP_SUFFIX}"
    fi

    # Download with retries
    DOWNLOADED=false
    for attempt in $(seq 1 $MAX_RETRIES); do
        HTTP_CODE=$(curl -s -L -o "$pdf_path" -w "%{http_code}" \
            --connect-timeout 15 \
            --max-time "$DOWNLOAD_TIMEOUT" \
            -H "User-Agent: $USER_AGENT" \
            "$url" 2>/dev/null || echo "000")

        if [[ "$HTTP_CODE" == "200" ]]; then
            # Validate PDF
            HEADER=$(head -c 4 "$pdf_path" 2>/dev/null || true)
            SIZE=$(stat -c%s "$pdf_path" 2>/dev/null || echo 0)
            if [[ "$HEADER" == "%PDF" && "$SIZE" -gt 1000 ]]; then
                DOWNLOADED=true
                break
            fi
        fi

        if [[ "$attempt" -lt "$MAX_RETRIES" ]]; then
            sleep 2
        fi
    done

    if [[ "$DOWNLOADED" == "true" ]]; then
        SUCCESS=$((SUCCESS + 1))
        # Remove backup on success
        rm -f "${pdf_path}${BACKUP_SUFFIX}"
        if [[ $((SUCCESS % 25)) -eq 0 ]]; then
            log "Progress: $((SUCCESS + FAILED_DL))/$TOTAL (success: $SUCCESS, failed: $FAILED_DL)"
        fi
    else
        FAILED_DL=$((FAILED_DL + 1))
        # Restore backup
        if [[ -f "${pdf_path}${BACKUP_SUFFIX}" ]]; then
            mv "${pdf_path}${BACKUP_SUFFIX}" "$pdf_path"
        fi
    fi

    sleep "$DELAY_BETWEEN_DOWNLOADS"

done <<< "$DATA"

log "Re-download complete: success=$SUCCESS failed=$FAILED_DL skipped=$SKIPPED"

# === STEP 3: TRIGGER JSON REBUILD ===
log "Triggering JSON rebuild via API..."

SESSION=$(mcp_session)
if [[ -z "$SESSION" ]]; then
    log "WARNING: Could not establish MCP session. Run JSON rebuild manually:"
    log "  cd $BASE_DIR && ./start.sh  (or call juris_json_rebuild)"
    exit 0
fi
mcp_notify "$SESSION"

RESULT=$(mcp_call "$SESSION" "juris_json_rebuild" '{}')
log "JSON rebuild result: $(echo "$RESULT" | grep -o '"text":"[^"]*"' | head -1)"

# === STEP 4: TRIGGER MASTER INDEX REBUILD ===
log "Triggering master-index rebuild..."

RESULT=$(mcp_call "$SESSION" "juris_master_index_rebuild" '{}')
log "Master-index rebuild result: $(echo "$RESULT" | grep -o '"text":"[^"]*"' | head -1)"

# === STEP 5: SYNC SHARE LINKS ===
log "Syncing share links..."
mcp_call "$SESSION" "juris_share_links_sync" '{}' >/dev/null 2>&1

log "Done."
log ""
log "=== SUMMARY ==="
log "  Files re-downloaded:  $SUCCESS"
log "  Downloads failed:     $FAILED_DL"
log "  Already valid:        $SKIPPED"
log "  JSON rebuild:         triggered"
log "  Master-index rebuild: triggered"
