"""
FastAPI backend for TJRS Jurisprudência Search Assistant.

Endpoints:
  POST /api/chat          – Chat with DeepSeek assistant (text + optional file)
  POST /api/upload         – Upload a file, extract text, return AI-suggested fields
  POST /api/search         – Run the TJRS scraper with given search fields
  GET  /api/search/status  – Poll scraper progress
  GET  /api/results/{id}   – Get results for a search job
  POST /api/download       – Download inteiro teor for selected results
"""

import os
from pathlib import Path

# Load .env early so all modules see its variables.
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=True)
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from modules.config import TJRS_FRONTEND_DIST_DIR

# ── App factory ─────────────────────────────────────────────────────────────

app = FastAPI(title="Juris Search")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files ────────────────────────────────────────────────────────────

if (TJRS_FRONTEND_DIST_DIR / "assets").is_dir():
    tjrs_assets_dir = str(TJRS_FRONTEND_DIST_DIR / "assets")
    app.mount("/assets", StaticFiles(directory=tjrs_assets_dir), name="frontend_assets_root")
    app.mount("/juris/assets", StaticFiles(directory=tjrs_assets_dir), name="frontend_assets_scoped")

# ── Routers ─────────────────────────────────────────────────────────────────

from modules.routes_chat import router as chat_router
from modules.routes_search import router as search_router
from modules.routes_download import router as download_router
from modules.routes_storage import router as storage_router
from modules.routes_health import router as health_router
from modules.routes_master import router as master_router
from modules.routes_ingest_pdf import router as ingest_pdf_router
from modules.routes_frontend import router as frontend_router

# API routers are served under both `/api/...` (used by the MCP server and
# external monitors) and `/juris/api/...` (used by the bundled frontend, which
# is served from `/juris/`). The frontend router is mounted separately below.
for router in (chat_router, search_router, download_router, storage_router, health_router, master_router, ingest_pdf_router):
    app.include_router(router)
    app.include_router(router, prefix="/juris")

app.include_router(frontend_router)

# ── Lifecycle ───────────────────────────────────────────────────────────────

from modules.lifecycle import register_lifecycle

register_lifecycle(app)

# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
