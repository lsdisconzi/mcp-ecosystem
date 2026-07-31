The `start-all.sh` script itself is now fixed—the report generated successfully without the arithmetic crash. The remaining failures are **project‑level issues** that need to be resolved inside each subproject. Here's what's wrong and how to fix them.

---

### 1. **discovery** – `case-server` crashes with missing `dotenv`
**Error:** `Cannot find module 'dotenv'`  
**Fix:** Install the missing Node dependency. From the repo root:

```bash
cd discovery
npm install dotenv
cd ..
```

If `case-server` has its own `package.json` (likely in `discovery/case-server/`), run `npm install` there as well:

```bash
cd discovery/case-server
npm install
cd ../..
```

---

### 2. **juris-search** – `LOG_DIR: unbound variable`
**Error:** `./start.sh: line 46: LOG_DIR: unbound variable`  
**Fix:** Edit `juris-search/start.sh` and either **set a default** at the top or define the variable before it's used. Add this near the top of that script:

```bash
LOG_DIR="${LOG_DIR:-$ROOT/.dev-logs}"   # adjust path to your logs directory
mkdir -p "$LOG_DIR"
```

If the script already sets `ROOT`, use `$ROOT/.dev-logs`. Otherwise, hardcode the path you used elsewhere.

---

### 3. **garge**, **transcription**, **audio** – missing Python virtual environments

- **garge:** `Missing project Python environment in /Users/dev/_sell/mcp-ecosystem/garge/.venv`
- **transcription:** same pattern
- **audio:** `Missing uvicorn for audio webapp (.venv/.venv-mcp)`

These projects need their Python environments created and dependencies installed. For each project, do:

```bash
cd garge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # or whatever the project requires
deactivate
cd ..
```

Repeat for **transcription** and **audio**.  
For **audio**, the error says `Missing uvicorn for audio webapp (.venv/.venv-mcp)` – it may need a separate `.venv-mcp` environment. Check the `audio/start.sh` to see which venv it expects, and create/activate that venv, then install `uvicorn` plus all other dependencies.

---

### 4. **violation-refiner** – missing `mcp` Python package
**Error:** `The 'mcp' package is required to run the MCP server.`  
**Fix:** Install the `mcp` package in its environment:

```bash
cd violation-refiner
source .venv/bin/activate        # (or create one if it doesn't exist)
pip install mcp
# or if there's a setup.py:
pip install -e '.[mcp]'
deactivate
cd ..
```

---

### 5. **ops dashboard** – warning about `return` in `finally` block (non‑fatal)
This is just a Python `SyntaxWarning`; it doesn't break the service, but you can clean up the code in `ops/app.py` lines 2624,2628 if desired. The dashboard started successfully.

---

### Summary of actions

```bash
# 1. discovery dotenv
cd discovery && npm install dotenv && cd ..

# 2. juris-search LOG_DIR
# Manually edit juris-search/start.sh and add LOG_DIR="${LOG_DIR:-...}" before line 46

# 3. Python venvs (garge, transcription, audio)
for proj in garge transcription audio; do
    cd $proj
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt   # or specific packages
    deactivate
    cd ..
done
# For audio, also check if .venv-mcp is required and set it up similarly.

# 4. violation-refiner mcp package
cd violation-refiner
source .venv/bin/activate
pip install mcp
deactivate
cd ..
```

