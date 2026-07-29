"""
OCR Service — Minimal FastAPI wrapper for OCR operations.
Provides a health endpoint and API to run OCR pipeline jobs.
Standardized for ops-dashboard integration.
"""

import os
import sys
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="OCR Service", version="1.0.0")

SCRIPT_DIR = Path(__file__).resolve().parent


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "OCR"}


@app.get("/")
async def root():
    return {"service": "OCR", "endpoints": ["/health", "/docs", "/api/run-demo"]}


@app.post("/api/run-demo")
async def run_demo():
    """Run the OCR demo pipeline."""
    demo_script = SCRIPT_DIR / "run_demo.py"
    if not demo_script.exists():
        raise HTTPException(status_code=404, detail="run_demo.py not found")

    try:
        result = subprocess.run(
            [sys.executable, str(demo_script)],
            capture_output=True, text=True, timeout=120,
            cwd=str(SCRIPT_DIR),
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[-5000:],
            "stderr": result.stderr[-2000:],
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="OCR demo timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8098))
    uvicorn.run(app, host="0.0.0.0", port=port)
