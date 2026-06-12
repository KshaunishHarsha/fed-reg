from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from phase_2.comment_drafter import DraftCommentError, draft_comment
from phase_2.pipeline import handle_correction, run_pipeline

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


class DraftCommentResponse(BaseModel):
    document_number: str
    title: str
    agency_names: List[str]
    comments_close_on: Optional[str] = None
    source_url: str
    regulations_gov_url: Optional[str] = None
    draft_comment: str


@router.get("/phase2/draft-comment", response_model=DraftCommentResponse)
async def phase2_draft_comment(
    document_number: str = Query(..., description="FR document number, e.g. 2026-12345"),
):
    """On-demand public comment letter for a proposed rule.

    Reuses the talking points already stored in summaries.xml_summary_blob, so
    the model only drafts prose (fast + cheap). Called by the 'Draft a Comment'
    button in the email digest.
    """
    try:
        return await draft_comment(document_number)
    except DraftCommentError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


# Standalone entry point — run Phase 2 in isolation without the unified app
if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    standalone = FastAPI(title="Federal Register Sentinel — Phase 2 (Standalone)")
    standalone.include_router(router)
    uvicorn.run(standalone, host="0.0.0.0", port=8002)