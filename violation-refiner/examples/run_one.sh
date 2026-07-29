#!/usr/bin/env bash
# Interactive single-violation pipeline runner.
#
# Asks for jurisdiction + violation id, then runs the full pipeline:
#   1. stage_cl_batch.py  (legacy bundle -> canonical layout)
#   2. refine_batch.py    (Layers 1-5 + validation, writes refined JSON)
#   3. wire_extensions.py (upsert into Qdrant + Neo4j)
#
# Usage:
#   ./examples/run_one.sh                              # fully interactive
#   ./examples/run_one.sh CL-016                       # jurisdiction inferred from prefix
#   ./examples/run_one.sh CL 016                       # explicit jurisdiction + number
#   JURISDICTION=CL ID=016 ./examples/run_one.sh       # via env vars
#
# Same-VID provider comparison (writes to a sibling bundle dir, skips upsert):
#   ./examples/run_one.sh CL-005 --suffix=__claude
#   LLM_PROVIDER=openrouter LLM_PROVIDER_OVERRIDE=1 \
#       ./examples/run_one.sh CL-005 --suffix __gpt
#   SUFFIX=__deepseek ./examples/run_one.sh CL-005
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
[ -f .venv/bin/activate ] && source .venv/bin/activate

# ---- argument parsing -----------------------------------------------------
JURISDICTION="${JURISDICTION:-}"
NUMBER="${ID:-}"
SUFFIX="${SUFFIX:-}"
NO_ENRICH=0
ENRICH_STAGES=""

# Collect positional args while stripping --suffix=... / --suffix <value>.
positional=()
while [ $# -gt 0 ]; do
    case "$1" in
        --suffix=*) SUFFIX="${1#--suffix=}"; shift ;;
        --suffix)   SUFFIX="${2:-}"; shift 2 ;;
        --no-enrich) NO_ENRICH=1; shift ;;
        --enrich-stages=*) ENRICH_STAGES="${1#--enrich-stages=}"; shift ;;
        --enrich-stages) ENRICH_STAGES="${2:-}"; shift 2 ;;
        --)         shift; while [ $# -gt 0 ]; do positional+=("$1"); shift; done ;;
        *)          positional+=("$1"); shift ;;
    esac
done
set -- "${positional[@]:-}"

if [ $# -ge 1 ] && [ -n "${1:-}" ]; then
    arg1="$1"
    if [[ "$arg1" == *-* ]]; then
        JURISDICTION="${arg1%%-*}"
        NUMBER="${arg1#*-}"
    else
        JURISDICTION="$arg1"
        NUMBER="${2:-$NUMBER}"
    fi
fi

# ---- interactive prompts (if anything is missing) -------------------------
if [ -z "$JURISDICTION" ]; then
    echo "Jurisdictions available: CL  BR  INT"
    read -r -p "Jurisdiction [CL]: " JURISDICTION
    JURISDICTION="${JURISDICTION:-CL}"
fi
JURISDICTION="$(echo "$JURISDICTION" | tr '[:lower:]' '[:upper:]')"

if [ -z "$NUMBER" ]; then
    read -r -p "Violation number (e.g. 5, 016, 7): " NUMBER
fi

# Normalize number to 3-digit zero-padded if it's purely numeric ------------
# Force base-10 interpretation so '016' is not parsed as octal (= 14).
if [[ "$NUMBER" =~ ^[0-9]+$ ]]; then
    NUMBER=$(printf "%03d" "$((10#$NUMBER))")
fi
VID="${JURISDICTION}-${NUMBER}"

# Normalise suffix (allow user to omit the leading separator).
if [ -n "$SUFFIX" ] && [[ "$SUFFIX" != __* ]] && [[ "$SUFFIX" != -* ]] && [[ "$SUFFIX" != .* ]]; then
    SUFFIX="__${SUFFIX}"
fi
# TARGET_VID = bundle directory name actually written to. When SUFFIX is
# empty this stays equal to VID (canonical run). When set, refine_batch
# operates on a sibling copy so multiple providers can be compared without
# overwriting each other's output for the same violation.
TARGET_VID="${VID}${SUFFIX}"

if [ "$NO_ENRICH" -eq 1 ] && [ -n "$ENRICH_STAGES" ]; then
    echo "Cannot combine --no-enrich with --enrich-stages." >&2
    exit 2
fi

# ---- LLM provider selection ----------------------------------------------
# Prompt for provider unless one was forced via env. Honours LLM_PROVIDER
# from .env as the default offered. Non-interactive runs (no stdin) skip
# the prompt and use whatever .env / env vars define.
PROVIDER_DEFAULT="${LLM_PROVIDER:-deepseek}"
if [ -t 0 ] && [ -z "${LLM_PROVIDER_OVERRIDE:-}" ] && [ "$NO_ENRICH" -ne 1 ]; then
    echo
    echo "LLM provider:"
    echo "  1) deepseek    (DeepSeek API — fast, low-cost)"
    echo "  2) openrouter  (OpenRouter — any model, e.g. Claude Opus 4.7)"
    read -r -p "Choose [1=deepseek, 2=openrouter] (default=${PROVIDER_DEFAULT}): " choice
    case "${choice:-}" in
        1|deepseek|DEEPSEEK)   export LLM_PROVIDER="deepseek" ;;
        2|openrouter|OPENROUTER) export LLM_PROVIDER="openrouter" ;;
        "")                    export LLM_PROVIDER="${PROVIDER_DEFAULT}" ;;
        *)                     export LLM_PROVIDER="${choice}" ;;
    esac
    # Optional one-shot model override.
    if [ "$LLM_PROVIDER" = "openrouter" ]; then
        DEFAULT_OR_MODEL="${OPENROUTER_MODEL:-anthropic/claude-opus-4.7}"
        read -r -p "OpenRouter model [${DEFAULT_OR_MODEL}]: " or_model
        export OPENROUTER_MODEL="${or_model:-${DEFAULT_OR_MODEL}}"
    fi
    # Clear LLM_BASE_URL / LLM_MODEL so provider defaults apply unless the
    # user explicitly set them in this shell session.
    if [ -z "${LLM_BASE_URL_EXPLICIT:-}" ]; then unset LLM_BASE_URL || true; fi
    if [ -z "${LLM_MODEL_EXPLICIT:-}" ]; then unset LLM_MODEL || true; fi
fi
LLM_PROVIDER="${LLM_PROVIDER:-$PROVIDER_DEFAULT}"
export LLM_PROVIDER

echo
echo "================================================================"
echo "  Running pipeline for: $VID"
if [ "$TARGET_VID" != "$VID" ]; then
    echo "  Output bundle:        $TARGET_VID  (comparison run)"
fi
echo "  LLM provider: $LLM_PROVIDER"
if [ "$NO_ENRICH" -eq 1 ]; then
    echo "  Enrichment mode: validation-only (--no-enrich)"
elif [ -n "$ENRICH_STAGES" ]; then
    echo "  Enrichment mode: subset (${ENRICH_STAGES})"
else
    echo "  Enrichment mode: auto (default)"
fi
echo "================================================================"
echo

# ---- server path detection ------------------------------------------------
# The staging script hardcodes macOS developer paths as defaults.  When
# running on the server, override them to point at the vault/shared trees.
STAGE_EXTRA_ARGS=()
if [ -d /awareness/shared ]; then
    STAGE_EXTRA_ARGS+=(
        --source /awareness/shared/violations
        --framework-md-root /awareness/shared/source_laws/law_md
    )
    # Map jurisdiction to the rendered-transcript incident directory.
    case "$JURISDICTION" in
        CL) STAGE_EXTRA_ARGS+=(--rendered /awareness/shared/transcripts_rendered/I-002) ;;
        BR) STAGE_EXTRA_ARGS+=(--rendered /awareness/shared/transcripts_rendered/I-001) ;;
        *)  STAGE_EXTRA_ARGS+=(--rendered /awareness/shared/transcripts_rendered/I-002) ;;  # default to I-002
    esac
    echo "    Server paths detected: ${STAGE_EXTRA_ARGS[*]}"
fi

# ---- 1. stage -------------------------------------------------------------
# Clear stale refine artefacts. refine_batch._load_violation prefers
# <id>.json.bak over the live JSON when present, which would silently mask
# any stager changes (e.g. verbatim-body hydration) on re-runs.
BUNDLE_DIR="build/cl_batch/${VID}"
rm -f "${BUNDLE_DIR}/${VID}.json" "${BUNDLE_DIR}/${VID}.json.bak"

# Per-run temp file so multiple parallel run_one.sh invocations (different
# VIDs / different providers) do not clobber each other's staging output.
STAGE_TMP="$(mktemp -t "run_one_stage.${TARGET_VID}.XXXXXX.json")"
trap 'rm -f "$STAGE_TMP"' EXIT

echo "── [1/3] Staging legacy bundle ─────────────────────────────────"
python3 examples/stage_cl_batch.py --jurisdiction "$JURISDICTION" --ids "$VID" \
    ${STAGE_EXTRA_ARGS[@]+"${STAGE_EXTRA_ARGS[@]}"} \
    | tee "$STAGE_TMP" | tail -30

# Bail if staging failed
if ! python3 -c "
import json,sys
d=json.load(open('${STAGE_TMP}'))
r=d['results'][0]
sys.exit(0 if r.get('ok') else 1)
"; then
    echo "Staging failed for $VID — aborting." >&2
    exit 1
fi

# If a suffix is in play, mirror the canonical bundle to the suffixed dir
# so refine_batch operates on an independent copy. We rename the inner
# violation JSON so refine_batch._find_violation_json picks it up by the
# bundle-dir name. The JSON's `violation_id` field stays equal to VID,
# which is fine for output comparison.
TARGET_BUNDLE="build/cl_batch/${TARGET_VID}"
if [ "$TARGET_VID" != "$VID" ]; then
    rm -rf "$TARGET_BUNDLE"
    cp -R "$BUNDLE_DIR" "$TARGET_BUNDLE"
    if [ -f "${TARGET_BUNDLE}/${VID}.json" ]; then
        mv "${TARGET_BUNDLE}/${VID}.json" "${TARGET_BUNDLE}/${TARGET_VID}.json"
    fi
    if [ -f "${TARGET_BUNDLE}/${VID}.json.bak" ]; then
        mv "${TARGET_BUNDLE}/${VID}.json.bak" "${TARGET_BUNDLE}/${TARGET_VID}.json.bak"
    fi
    rm -rf "${TARGET_BUNDLE}/Validation"
fi

# ---- 2. refine ------------------------------------------------------------
echo
echo "── [2/3] Refining (Layers 1–5 + validation) ───────────────────"
# Report resolved LLM status using Settings (supports provider-specific keys).
python3 - <<'PY'
from violation_pack.config import Settings

s = Settings.from_env()
provider = (s.llm_provider or "").strip().lower()
enabled = bool(s.llm_api_key) or provider == "ollama"
if enabled:
    print(f"    LLM enrichment: ON  (provider={provider}, model={s.llm_model or 'default'})")
else:
    print("    LLM enrichment: OFF (configure provider key in .env, e.g. DEEPSEEK_API_KEY)")
PY
REFINE_CMD=(python3 examples/refine_batch.py --input build/cl_batch --only "$TARGET_VID" --include-extra)
if [ "$NO_ENRICH" -eq 1 ]; then
    REFINE_CMD+=(--no-enrich)
elif [ -n "$ENRICH_STAGES" ]; then
    REFINE_CMD+=(--enrich --enrich-stages "$ENRICH_STAGES")
fi
"${REFINE_CMD[@]}"

# ---- 3. upsert ------------------------------------------------------------
JSON_PATH="build/cl_batch/${TARGET_VID}/${TARGET_VID}.json"
if [ ! -f "$JSON_PATH" ]; then
    echo "Refined JSON not found at $JSON_PATH — aborting." >&2
    exit 1
fi

if [ "$NO_ENRICH" -eq 1 ]; then
    echo
    echo "── [3/3] Upsert SKIPPED for validation-only run (--no-enrich) ───"
    echo "    No Qdrant/Neo4j writes for validation-only mode."
elif [ "$TARGET_VID" != "$VID" ]; then
    echo
    echo "── [3/3] Upsert SKIPPED for comparison run ('$TARGET_VID') ──────"
    echo "    Qdrant + Neo4j are namespaced by violation_id; re-run without"
    echo "    --suffix to publish the canonical version."
else
    echo
    echo "── [3/3] Upserting into Qdrant + Neo4j ────────────────────────"
    python3 examples/wire_extensions.py --violation-json "$JSON_PATH" 2>&1 \
        | grep -v -E "UserWarning|show_warning|Qdrant client" || true
fi

echo
echo "================================================================"
echo "  Done: $TARGET_VID"
echo "  Refined JSON: $JSON_PATH"
echo "  Validation:   build/cl_batch/${TARGET_VID}/Validation/validation_report.md"
echo "================================================================"
