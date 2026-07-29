# Project Audit Report: audio

## 1. Executive Summary
- **Status**: NEEDS ATTENTION
- **% Complete**: ~85% of declared functionality is working
- **Key Risk**: Frontend fallback API URL hardcoded to MCP port (8765) instead of webapp port (8777), causing connection failures when `window.location.origin` is falsy; also the startup script uses two different venvs which can fail to import the `webapp` module when launched from `.venv-mcp`

## 2. Declared Purpose & Requirements

### 2.1 What this project IS
This is a **service wrapper** around the [PyTorch torchaudio](https://github.com/pytorch/audio) library (version 2.11.0a0), providing:

1. **A FastAPI web application** (`webapp/`) that exposes torchaudio's audio processing features via REST API endpoints, with a browser-based UI (single-page HTML/JS app).
2. **An MCP server** (`mcp/`) that exposes torchaudio tools (audio inspection, resampling, feature extraction, ASR transcription) over the Model Context Protocol (stdio, SSE, or streamable-http transport).
3. **The full torchaudio library** (`src/`) as the underlying engine — datasets, models (wav2vec2, HuBERT, WavLM, Emformer, Tacotron2, WaveRNN, HDemucs, ConvTasNet, etc.), functional transforms, biquad filters, I/O, compliance interfaces.
4. **Start/stop lifecycle scripts** (`start.sh`, `stop.sh`) that launch both services as nohup background processes.

### 2.2 Declared features (from README, docstrings, comments)
- Audio I/O: upload, inspect, download (WAV base64)
- Parametric biquad filters: lowpass, highpass, bandpass, bandreject, allpass, bass, treble, equalizer
- Audio effects: gain, dither, dcshift, overdrive, contrast, flanger, phaser, convolution reverb
- Voice enhancement: pitch shift, speed change, time stretch, pre/de-emphasis, volume, fade, noise injection
- Spectral analysis: spectrogram, mel-spectrogram, MFCC, loudness (LUFS), spectral centroid, pitch detection
- Source separation: HDemucs (drums, bass, other, vocals)
- Voice activity detection
- Resampling
- ASR transcription (greedy decoding via Wav2Vec2 pipelines, via MCP)
- Audio slicing and resampling (via MCP)
- Session-based audio state (in-memory, not persisted)

### 2.3 External services/APIs
- **torchcodec** (required for audio I/O since torchaudio 2.9)
- **torch** (PyTorch)
- **numpy**
- **fastapi** + **uvicorn** (web server)
- **mcp[cli]** (FastMCP for MCP server)
- Model checkpoints downloaded on-demand (via torch.hub / pipeline bundles)

### 2.4 Interface/API surface
| Interface | Port | Transport | Description |
|-----------|------|-----------|-------------|
| Webapp API | 8777 (default) | HTTP (FastAPI) | REST endpoints for audio processing |
| Webapp UI | 8777 | HTTP | Single-page browser app |
| MCP server | 8765 (default) | stdio/SSE/streamable-http | MCP tools for automation |

**Webapp API endpoints** (24 total):
`POST /api/upload`, `POST /api/upload-session`, `GET /api/audio/{session_id}`, `POST /api/filter`, `POST /api/filter-chain`, `POST /api/effects/gain`, `POST /api/effects/dither`, `POST /api/effects/dcshift`, `POST /api/effects/overdrive`, `POST /api/effects/contrast`, `POST /api/effects/flanger`, `POST /api/effects/phaser`, `POST /api/effects/convolve`, `POST /api/effects/ir-convolve`, `POST /api/enhance/pitch-shift`, `POST /api/enhance/speed`, `POST /api/enhance/preemphasis`, `POST /api/enhance/deemphasis`, `POST /api/enhance/volume`, `POST /api/enhance/fade`, `POST /api/enhance/add-noise`, `POST /api/enhance/time-stretch`, `POST /api/analysis/spectrogram`, `POST /api/analysis/mel-spectrogram`, `POST /api/analysis/mfcc`, `POST /api/analysis/loudness`, `POST /api/analysis/spectral-centroid`, `POST /api/analysis/pitch`, `POST /api/separate`, `POST /api/vad`, `POST /api/resample`, `GET /api/info`, `GET /`

**MCP tools** (8 total):
`transcription_healthcheck`, `transcription_audio_info`, `transcription_resample_audio`, `transcription_slice_audio`, `transcription_extract_features`, `transcription_list_asr_bundles`, `transcription_transcribe_greedy`, `transcription_list_project_paths`

## 3. Feature Completeness Matrix

| Feature | Declared | Implemented | Working? | Notes |
|---------|----------|-------------|----------|-------|
| Audio upload & inspect | Webapp UI + API | `webapp/server.py:85-101` | YES | Verified in logs (line 374: 200 OK) |
| Session-based audio storage | Webapp API | `webapp/server.py:104-133` | YES | In-memory only, lost on restart |
| Biquad filter chain | Webapp API | `webapp/server.py:140-228` | YES | All 8 filter types verified exist in source |
| Single filter application | Webapp API | `webapp/server.py:163-199` | YES | Verified in logs (line 391-401) |
| Audio effects (8 types) | Webapp UI + API | `webapp/server.py:235-341` | YES | Flanger, phaser, overdrive, contrast, dither, dcshift, gain, reverb |
| Voice enhancement | Webapp UI + API | `webapp/server.py:348-445` | YES | Pitch shift, speed, preemphasis verified in logs (line 382-389) |
| Spectral analysis | Webapp UI + API | `webapp/server.py:452-566` | YES | Heatmap rendering in frontend JS |
| Source separation | Webapp API | `webapp/server.py:573-651` | PARTIAL | Verified 200 OK in logs (line 378). Model selection logic is fragile (see 5.2) |
| Voice activity detection | Webapp API | `webapp/server.py:658-670` | LIKELY | Function exists in source, not verified in logs |
| Time stretch | Webapp API | `webapp/server.py:731-748` | LIKELY | Function exists in source |
| Custom IR convolution | Webapp API | `webapp/server.py:713-724` | LIKELY | Requires second file upload |
| MCP health check | MCP server | `mcp/server.py:53-60` | YES | Verified in logs |
| MCP audio info | MCP server | `mcp/server.py:63-73` | YES | |
| MCP resample | MCP server | `mcp/server.py:76-95` | YES | |
| MCP slice audio | MCP server | `mcp/server.py:98-142` | YES | |
| MCP extract features | MCP server | `mcp/server.py:145-200` | YES | |
| MCP list ASR bundles | MCP server | `mcp/server.py:203-214` | LIKELY | |
| MCP transcribe greedy | MCP server | `mcp/server.py:217-257` | LIKELY | Downloads model on first use |
| MCP list project paths | MCP server | `mcp/server.py:260-275` | YES | |
| Frontend UI | `index.html` | Complete | YES | All 8 sections implemented with JS handlers |
| Waveform visualization | Frontend JS | `/webapp/static/index.html:718-744` | YES | Placeholder (sin+random) — not real waveform data |
| `/api/info` endpoint | Webapp API | `webapp/server.py:755-811` | YES | Verified 200 OK in logs (line 372) |
| Download processed audio | Frontend JS | `webapp/static/index.html:790-792` | YES | |

## 4. Implementation Details

### 4.1 Architecture Overview
The project has three distinct layers:

**Layer 1: torchaudio core library** (`src/`)
- The upstream PyTorch torchaudio library, version 2.11.0a0
- Python package: `src/torchaudio/`
- C++/CUDA extensions: `src/libtorchaudio/` (custom ops for CUDA CTC decoder, RNNT, forced alignment, IIR filters)
- Built via `setup.py` using `setuptools` with custom extension helpers (`tools/setup_helpers/`)
- Key submodules: `functional/` (signal processing), `transforms/` (torch.nn.Module wrappers), `models/` (pre-trained architectures), `pipelines/` (bundled weights), `datasets/` (22 dataset loaders), `compliance/` (Kaldi interface)

**Layer 2: FastAPI webapp** (`webapp/server.py`, 850 lines)
- Single-file FastAPI app with 24 endpoints
- All audio processing stateless except for in-memory sessions dict (`sessions: dict[str, dict]`)
- Returns processed audio as base64-encoded WAV in JSON responses
- Serves a single-page HTML frontend from `webapp/static/index.html` (~1164 lines)
- Frontend has 8 sections: Upload, Filters, Effects, Voice, Spectral, Separation, VAD, Resample

**Layer 3: MCP server** (`mcp/torchaudio_mcp/server.py`, 314 lines)
- Uses `FastMCP` from `mcp` package
- Exposes 8 tools with type annotations for safe parameter handling
- Supports 3 transports: stdio (for Claude Desktop), SSE, streamable-http (for networked use)
- Configurable via environment variables: `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`

### 4.2 File size concerns
| File | Lines | Concern |
|------|-------|---------|
| `webapp/static/index.html` | 1164 | Very large - HTML, CSS, and JS all in one file |
| `src/torchaudio/functional/functional.py` | ~2500+ | Very large - core signal processing monolith |
| `src/torchaudio/functional/filtering.py` | ~1500+ | Large - all audio effects/filters |
| `webapp/server.py` | 850 | Manageable but single-file, no separation of concerns |

### 4.3 Key file roles
- `start.sh`: Launches both services via nohup, with PID tracking in `.run/`
- `stop.sh`: Kills processes by PID file + port scan + pkill fallback
- `mcp/mcpo.json`: Configuration for running MCP server via MCPO proxy (stdio mode)
- `.venv/`: Python venv for webapp (contains torchaudio, fastapi, uvicorn)
- `.venv-mcp/`: Python venv for MCP server (contains mcp, torchaudio)
- `.logs/api.log`, `.logs/mcp.log`: Service logs (not in .gitignore)
- `.run/`: PID files for running services (not in .gitignore)
- `package-lock.json`: Empty npm lock file (no node packages, likely vestigial)

## 5. Issues Found

### 5.1 Critical (broken functionality, security)

#### C1. Frontend API URL hardcoded to wrong port
- **File**: `/awareness/services/audio/webapp/static/index.html`
- **Lines**: 633, 710, 765
- **Issue**: `const API = window.location.origin || 'http://localhost:8765';` — the fallback URL uses port **8765** (the MCP server port), not **8777** (the actual webapp API port). When the page is opened from a file:// URL or if `window.location.origin` is empty for any reason, ALL API requests will be sent to the MCP server, which will return 404 for all of them.
- **Impact**: Frontend unusable in any context where `window.location.origin` is not the webapp. Error messages on lines 710 and 765 also reference the wrong port.

#### C2. Startup fragility with two venvs
- **File**: `/awareness/services/audio/start.sh`, lines 25-34
- **Issue**: The script tries `.venv-mcp/bin/uvicorn` as a fallback for the webapp (line 33), but `.venv-mcp` may not have `webapp` in its Python path. The api.log shows 5 startup failures with `ModuleNotFoundError: No module named 'webapp'` before finally finding a working interpreter. This is because `uvicorn webapp.server:app` fails when run from a venv that doesn't have the project root on `sys.path`.
- **Impact**: Unreliable startup, confusing log output, potential silent failure.

### 5.2 Important (bugs, missing features, reliability)

#### I1. Source separation model selection is fragile
- **File**: `/awareness/services/audio/webapp/server.py`, lines 586-597
- **Issue**: For "medium" model size, it sets `bundle = torchaudio.pipelines.HDEMUCS_HIGH_MUSDB` (note: the name says HIGH but it's used as medium). For "low", it falls back to `hdemucs_low()` directly. The variable `bundle` is set to `None` for "low" mode but later referenced at line 628 (`expected_sr = getattr(bundle, 'sample_rate', 44100) if bundle else 44100`). This works but is fragile — if the model objects have different interfaces, this could break.

#### I2. In-memory session storage is unbounded
- **File**: `/awareness/services/audio/webapp/server.py`, line 31
- **Issue**: `sessions: dict[str, dict] = {}` stores waveform tensors in memory indefinitely. No TTL, no size limit, no eviction policy. A long-running server with many sessions will exhaust memory.

#### I3. No input validation on uploaded files
- **File**: `/awareness/services/audio/webapp/server.py`, lines 85-101
- **Issue**: Files are passed directly to `torchaudio.load()` without checking file size, type, or content. Large files or malformed data can crash the server with unhandled exceptions (though caught by generic `except Exception`).

#### I4. Generic exception handling masks real errors
- **File**: `/awareness/services/audio/webapp/server.py`
- **Issue**: Nearly every endpoint wraps its logic in `try/except Exception as e: return JSONResponse({"error": str(e)}, status_code=400)`. This masks programming errors (e.g., `AttributeError`, `TypeError`) as 400 Bad Request. The only exception is `/api/separate` (line 648-651) which uses 500 and prints a traceback — inconsistent.

#### I5. Waveform visualization is fake
- **File**: `/awareness/services/audio/webapp/static/index.html`, lines 718-744
- **Issue**: The `drawWaveform()` function generates a sine wave with random noise instead of rendering actual waveform data. The comment on line 727 says "Simple placeholder waveform visualization". Users see misleading data.

#### I6. No .env.example file
- **Issue**: `start.sh` sources `.env` if present (line 7-10), with defaults for `HOST`, `PORT`, `APP_URL`, `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`. But there is no `.env.example` documenting these variables.

#### I7. CORS misconfiguration risk
- **File**: `/awareness/services/audio/webapp/server.py`, lines 22-28
- **Issue**: `allow_origins=["*"]` with `allow_credentials=True` is a known insecure combination. While this is a local development tool, it would be flagged by any security scanner.

### 5.3 Minor (cleanup, style, optimization)

#### M1. Stale log files
- **Directory**: `/awareness/services/audio/.logs/`
- **Files**: `api.log` (470 lines, 128KB+), `mcp.log` (275 lines)
- **Issue**: These are runtime artifacts from previous service runs. Should be in .gitignore and cleaned between restarts.

#### M2. `.run/` directory not clean
- **Directory**: `/awareness/services/audio/.run/`
- **Issue**: Empty directory present but no PID files (services not currently running). Should be in .gitignore.

#### M3. `__pycache__` in webapp
- **Directory**: `/awareness/services/audio/webapp/__pycache__/`
- **File**: `server.cpython-312.pyc` (38KB)
- **Issue**: Compiled bytecode committed or left over. The root `.gitignore` has `__pycache__/` which should cover this, but it still exists on disk.

#### M4. Empty/vestigial `package-lock.json`
- **File**: `/awareness/services/audio/package-lock.json`
- **Issue**: Contains `{"name": "audio", "lockfileVersion": 3, "requires": true, "packages": {}}` — no dependencies. No `package.json` exists. Likely created accidentally.

#### M5. `_array_to_b64` is a redundant alias
- **File**: `/awareness/services/audio/webapp/server.py`, lines 825-826
- **Issue**: `_array_to_b64` simply calls `_tensor_to_b64`. Only used once at line 131. Redundant indirection.

#### M6. `setup.py` contains a TODO comment
- **File**: `/awareness/services/audio/setup.py`, line 92
- **Issue**: `# TODO: revisit if needed. Maybe it's needed for nightlies. Unsure.` — unresolved decision about PyTorch version pinning.

#### M7. `.gitmodules` is empty
- **File**: `/awareness/services/audio/.gitmodules`
- **Issue**: File exists but is empty (0 bytes). Should be removed.

#### M8. `third_party/` contains only a license file
- **Directory**: `/awareness/services/audio/third_party/`
- **File**: `LICENSES_BUNDLED.txt` only
- **Issue**: The directory name suggests bundled third-party code, but only licenses are present. No actual third-party source.

#### M9. Large virtual environments
- **Directories**: `.venv/` and `.venv-mcp/`
- **Issue**: Two separate venvs with significant overlap (both have torchaudio, torch, etc.). The `.venv-mcp` venv appears to duplicate much of `.venv`. Combined size likely >2GB.

## 6. Directory Cleanups Needed

- [ ] **Delete** `/awareness/services/audio/.logs/api.log` — stale runtime log (470 lines, includes download progress bars)
- [ ] **Delete** `/awareness/services/audio/.logs/mcp.log` — stale runtime log (275 lines)
- [ ] **Delete** `/awareness/services/audio/webapp/__pycache__/` — compiled bytecode
- [ ] **Delete** `/awareness/services/audio/package-lock.json` — empty, vestigial, no corresponding package.json
- [ ] **Delete** `/awareness/services/audio/.gitmodules` — empty file
- [ ] **Add to `.gitignore`**: `.logs/`, `.run/`
- [ ] **Consider deleting** `.venv-mcp/` if its dependencies can be consolidated into `.venv/`

## 7. Improvement Proposals

### 7.1 Fix frontend API port (CRITICAL)
**File**: `/awareness/services/audio/webapp/static/index.html`
Change line 633 from:
```javascript
const API = window.location.origin || 'http://localhost:8765';
```
to:
```javascript
const API = window.location.origin || 'http://localhost:8777';
```
Also fix error messages on lines 710 and 765 from "8765" to "8777".

### 7.2 Fix startup script to prevent venv confusion (IMPORTANT)
**File**: `/awareness/services/audio/start.sh`
- Remove the `.venv-mcp/bin/uvicorn` fallback for the webapp API (lines 33-34). The webapp should always run from `.venv` which has fastapi and the project root accessible.
- OR add `export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"` before launching either service so that the `webapp` package is always importable regardless of venv.

### 7.3 Add session TTL or size limit (IMPORTANT)
**File**: `/awareness/services/audio/webapp/server.py`
- Add a maximum number of sessions (e.g., 100)
- Add a TTL per session (e.g., 30 minutes)
- Evict oldest sessions when limit is reached

### 7.4 Add .env.example
Create `/awareness/services/audio/.env.example` documenting:
```
HOST=0.0.0.0
PORT=8777
APP_URL=http://127.0.0.1:8777/
MCP_TRANSPORT=streamable-http
MCP_HOST=127.0.0.1
MCP_PORT=8765
```

### 7.5 Fix source separation model selection
**File**: `/awareness/services/audio/webapp/server.py`, lines 586-597
Replace the fragile if/elif/else with a proper dispatch table:
```python
SEPARATION_MODELS = {
    "low": torchaudio.models.hdemucs_low,
    "medium": torchaudio.pipelines.HDEMUCS_HIGH_MUSDB,
    "high": torchaudio.pipelines.HDEMUCS_HIGH_MUSDB_PLUS,
}
```
And handle the `bundle` attribute consistently instead of checking `if bundle else`.

### 7.6 Improve error handling consistency
**File**: `/awareness/services/audio/webapp/server.py`
- Use 500 for unexpected errors, 400 for user errors
- Add structured logging instead of bare `traceback.print_exc()`
- Consider a FastAPI exception handler middleware

### 7.7 Replace fake waveform visualization
**File**: `/awareness/services/audio/webapp/static/index.html`, lines 718-744
- Add an API endpoint to return waveform samples (downsampled envelope)
- Replace the sin+random placeholder with actual waveform data

### 7.8 Consolidate virtual environments
Consider using a single `.venv` with all dependencies (webapp + MCP), reducing disk usage by ~1GB+. The `requirements.txt`, `webapp/requirements.txt`, and `mcp/requirements.txt` could be merged.

### 7.9 Add webapp/__init__.py
**File**: `/awareness/services/audio/webapp/__init__.py` (does not exist)
Adding this file would make `webapp` a proper Python package, ensuring it's importable from any venv when the project root is on PYTHONPATH.

### 7.10 Fix CORS configuration
**File**: `/awareness/services/audio/webapp/server.py`, line 25
Remove `allow_credentials=True` when using `allow_origins=["*"]`, or restrict origins to specific domains.

## 8. Dependency Audit

### 8.1 Used but undeclared
- `json` (stdlib, used in webapp/server.py — no issue)
- `traceback` (stdlib, used in webapp/server.py — no issue)
- `base64` (stdlib, used in webapp/server.py — no issue)
- `io` (stdlib — no issue)
- `tempfile` (stdlib — no issue)
- `pathlib` (stdlib — no issue)

### 8.2 Declared but unused (or questionable)
- `numpy` in `webapp/requirements.txt`: Used in `webapp/server.py:18` (`import numpy as np`) but never actually called. The `tolist()` calls are on torch tensors, not numpy arrays.
- `numpy` in `mcp/requirements.txt`: Not imported in `mcp/torchaudio_mcp/server.py`.
- `SoundFile` in root `requirements.txt`: Listed as optional. May be used as a backend fallback.
- `package-lock.json`: No Node.js dependencies at all.

### 8.3 Version concerns
- `requirements.txt`: `torch` unpinned — could break on major PyTorch version bumps.
- `webapp/requirements.txt`: `fastapi>=0.100.0`, `uvicorn>=0.23.0` — minimum versions, no upper bound.
- `mcp/requirements.txt`: `mcp[cli]>=1.9.0` — minimum version only.
- `setup.py`: `install_requires=[]` empty — torchaudio's setup.py pins nothing (relies on torch being pre-installed).
- `version.txt`: `2.11.0a0` — alpha release, not stable.
- `pyproject.toml`: References `black == 22.3` and `usort == 1.0.2` in pre-commit config. These are version-pinned but only for linting, not runtime.

## 9. Architecture Assessment

### 9.1 Current architecture
```
┌────────────────────────────────────────────┐
│                  start.sh                   │
│           orchestrates both services         │
└──────────────┬─────────────────────────────┘
               │
       ┌───────┴────────┐
       │                │
   ┌───▼──────┐   ┌─────▼───────┐
   │ Webapp   │   │ MCP Server  │
   │ (FastAPI)│   │ (FastMCP)   │
   │ :8777    │   │ :8765       │
   └────┬─────┘   └──────┬──────┘
        │                │
        └───────┬────────┘
                │
     ┌──────────▼──────────┐
     │   torchaudio 2.11   │
     │  (src/torchaudio/)  │
     └─────────────────────┘
```

### 9.2 Strengths
- Clean separation between the webapp API and MCP server
- Startup/shutdown lifecycle is well-structured (PID files, port checks, graceful shutdown with SIGTERM then SIGKILL)
- All API functions verified to exist in the torchaudio source — no phantom imports
- MCP server supports multiple transport modes, making it flexible for different deployment scenarios
- Good test coverage exists for the torchaudio core library (`test/` directory has unit tests for all major modules)
- Frontend SPA is fully self-contained (single HTML file, no build step)

### 9.3 Weaknesses
- **Monolithic webapp**: All 24 endpoints in a single 850-line file with no route/module organization
- **Two venvs**: Unnecessary complexity; `.venv-mcp` duplicates most of `.venv`
- **No persistence**: Sessions are in-memory; restart loses everything
- **No rate limiting**: Unprotected against abuse
- **No health check endpoint**: Start script polls `/`, which returns the HTML page — not ideal
- **Logs not rotated**: `.logs/api.log` grows unbounded; includes verbose download progress bars
- **Frontend depends on exact API port**: If port changes, the hardcoded fallback breaks
- **No Docker/compose setup**: The only Docker references are for building wheels, not deployment
- **Torchaudio is an `a0` (alpha) version**: Not production-stable

### 9.4 Recommended architecture changes
1. **Split webapp routes** into separate modules (e.g., `webapp/routes/filters.py`, `webapp/routes/effects.py`, `webapp/routes/analysis.py`)
2. **Use a single venv** for both services, with all dependencies declared in one `requirements.txt`
3. **Add a proper health endpoint** at `GET /api/health` that returns `{"status": "ok"}` instead of using `GET /`
4. **Move frontend API URL to a configurable setting** injected via a `<meta>` tag or API call, eliminating the hardcoded fallback
5. **Add log rotation** via Python's `logging` module with `RotatingFileHandler` instead of shell redirection
6. **Consider containerization** with a simple Dockerfile for reproducible deployment
