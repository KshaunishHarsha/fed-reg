from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter
from pydantic import BaseModel

from pipeline import handle_correction, run_pipeline

load_dotenv(Path(__file__).parent.parent / ".env")

router = APIRouter(tags=["phase2"])


class CorrectionRequest(BaseModel):
    document_number: str
    error_detail: str


@router.post("/phase2/run")
async def phase2_run():
    """Trigger summarization of all pending (INGESTED + is_relevant) documents.
    When called via the unified app, phase3_ingest_fn is injected by the orchestrator.
    This endpoint is for standalone Phase 2 runs only.
    """
    return await run_pipeline()


@router.post("/phase2/correct")
async def phase2_correct(request: CorrectionRequest):
    """Receive a correction from Phase 3 and rerun the LLM for that document."""
    new_blob = await handle_correction(request.document_number, request.error_detail)
    status = "reprocessed" if new_blob is not None else "failed"
    return {"status": status, "document_number": request.document_number}


# Standalone entry point — run Phase 2 in isolation without the unified app
if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    standalone = FastAPI(title="Federal Register Sentinel — Phase 2 (Standalone)")
    standalone.include_router(router)
    uvicorn.run(standalone, host="0.0.0.0", port=8002)