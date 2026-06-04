"""
Federal Register Sentinel — Unified FastAPI App

Single process, single port (8000). All phases run in-process.
No HTTP calls between Phase 1, 2, and 3.

Endpoints:
  POST /run                   ← daily cron entry point (Phase 1 → 2 → 3)
  POST /phase2/run            ← trigger Phase 2 alone (standalone use)
  POST /phase2/correct        ← Phase 3 correction hook
  + all Phase 3 endpoints     ← status, digest test, validate test, etc.
"""

from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv(Path(__file__).parent / ".env")

app = FastAPI(
    title="Federal Register Sentinel",
    description="Unified pipeline: Phase 1 → Phase 2 → Phase 3, all in-process.",
    version="1.0.0",
)

# ── Phase 2 router ────────────────────────────────────────────────────────────
from phase_2.api import router as phase2_router
app.include_router(phase2_router)

# ── Phase 3 router ────────────────────────────────────────────────────────────
# Included when Phase 3 is available. Provides /phase3/status, /phase3/digest/test, etc.
try:
    from phase_3.router import router as phase3_router
    from phase_3.db import init_db
    
    init_db()  # Initialize the Phase 3 database connection pool
    app.include_router(phase3_router)
except ImportError:
    pass  # Phase 3 not yet wired up — unified app still works for Phase 1/2


# ── Root orchestration endpoint ───────────────────────────────────────────────

@app.post("/run")
async def run(date: str = None):
    """
    Daily cron entry point.
    Runs Phase 1 → Phase 2 → Phase 3 sequentially via direct in-process calls.
    Pass ?date=YYYY-MM-DD to run against a specific date (backfill / testing).
    """
    from orchestrator import run_full_pipeline
    return await run_full_pipeline(date)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)