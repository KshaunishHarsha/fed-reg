"""
Federal Register Sentinel — Unified FastAPI App

Single process, single port (8000). All phases run in-process.
No HTTP calls between Phase 1, 2, and 3.

Endpoints:
  GET  /                      ← demo frontend
  POST /demo/run              ← demo: subscribe email + trigger full pipeline
  POST /run                   ← daily cron entry point (Phase 1 → 2 → 3)
  POST /phase2/run            ← trigger Phase 2 alone (standalone use)
  POST /phase2/correct        ← Phase 3 correction hook
  + all Phase 3 endpoints     ← status, digest test, validate test, etc.
"""

import re
import uuid
from pathlib import Path
from typing import Any, Dict

import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(Path(__file__).parent / ".env")

# ── In-memory job registry ─────────────────────────────────────────────────────
# Stores pipeline run state keyed by job_id (uuid4 string).
# States: "running" | "done" | "error"
# This is process-local and intentionally ephemeral — jobs disappear on restart.
_jobs: Dict[str, Dict[str, Any]] = {}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ASTRO_DIST = Path(__file__).parent / "sentinel-frontend" / "dist"
_LEGACY_FRONTEND = Path(__file__).parent / "frontend" / "index.html"

app = FastAPI(
    title="Federal Register Sentinel",
    description="Unified pipeline: Phase 1 → Phase 2 → Phase 3, all in-process.",
    version="1.0.0",
)

# CORS — localhost for dev, plus any origins listed in ALLOWED_ORIGINS (comma-separated)
import os as _os
_extra_origins = [o.strip() for o in _os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4321", "http://localhost:3000"] + _extra_origins,
    allow_methods=["*"],
    allow_headers=["*"],
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

# Serve Astro static assets if the dist folder exists
_astro_assets = _ASTRO_DIST / "_assets"
if _astro_assets.exists():
    app.mount("/_assets", StaticFiles(directory=str(_astro_assets)), name="astro-assets")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def frontend():
    """Serve the Astro frontend (falls back to legacy index.html)."""
    astro_index = _ASTRO_DIST / "index.html"
    if astro_index.exists():
        return HTMLResponse(astro_index.read_text(encoding="utf-8"))
    if _LEGACY_FRONTEND.exists():
        return HTMLResponse(_LEGACY_FRONTEND.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Federal Register Sentinel</h1><p>Frontend not built. Run <code>cd sentinel-frontend && npm run build</code>.</p>", status_code=200)


class DemoRequest(BaseModel):
    email: str


@app.post("/demo/run")
async def demo_run(request: DemoRequest, background_tasks: BackgroundTasks):
    """
    Demo entry point: subscribe an email address and trigger the full pipeline.
    The pipeline runs in the background — the response is returned immediately.
    In production this endpoint does not exist; the pipeline is triggered by a
    scheduled cron job once per day.
    """
    from orchestrator import run_full_pipeline
    from phase_3.mailing_list import add_subscriber

    if not _EMAIL_RE.match(request.email):
        raise HTTPException(status_code=400, detail="Invalid email address.")

    await add_subscriber(request.email)
    background_tasks.add_task(run_full_pipeline)
    return {"subscribed": request.email, "pipeline_started": True}


@app.post("/run", status_code=202)
async def run(background_tasks: BackgroundTasks, date: str = None):
    """
    Daily cron / demo entry point.
    Returns 202 immediately with a job_id. The full Phase 1 → 2 → 3 pipeline
    runs in the background. Poll GET /run/status/{job_id} to track progress.
    Pass ?date=YYYY-MM-DD to run against a specific date (backfill / testing).
    """
    from orchestrator import run_full_pipeline

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running", "date": date, "result": None, "error": None}

    async def _run_and_capture():
        try:
            result = await run_full_pipeline(date)
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = result
        except Exception as exc:  # noqa: BLE001
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(exc)

    background_tasks.add_task(_run_and_capture)
    return {"job_id": job_id, "status": "running", "date": date}


@app.get("/run/status/{job_id}")
async def run_status(job_id: str):
    """
    Poll the status of a background pipeline run.
    Returns:
      status=running  — pipeline still executing
      status=done     — pipeline finished; result payload included
      status=error    — pipeline raised an exception; error string included
    """
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found. It may have expired after a server restart.")
    return job


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)