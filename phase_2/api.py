from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from pipeline import handle_correction, run_pipeline

load_dotenv(Path(__file__).parent.parent / ".env")

app = FastAPI(title="Federal Register Sentinel — Phase 2 Summarization")


class CorrectionRequest(BaseModel):
    document_number: str
    error_detail: str


@app.post("/phase2/run")
async def run():
    """Trigger summarization of all pending (INGESTED + is_relevant) documents."""
    result = await run_pipeline()
    return result


@app.post("/phase2/correct")
async def correct(request: CorrectionRequest):
    """Receive a correction request from Phase 3 and rerun the LLM for that document.
    Phase 3 calls this when XML validation fails.
    """
    success = await handle_correction(request.document_number, request.error_detail)
    status = "reprocessed" if success else "failed"
    return {"status": status, "document_number": request.document_number}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)