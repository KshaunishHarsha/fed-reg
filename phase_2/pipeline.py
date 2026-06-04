from pathlib import Path
from typing import Awaitable, Callable, Optional

from dotenv import load_dotenv

from database import (
    fetch_document_by_number,
    fetch_pending_documents,
    increment_correction_attempts,
    save_summary,
    update_pipeline_state,
)
from models import DocumentRecord
from summarizer import summarize
from tier_router import route_and_prepare
from xml_builder import build_xml

load_dotenv(Path(__file__).parent.parent / ".env")

_MAX_CORRECTION_RETRIES = 2

# Callback type: async fn(doc, xml_blob) -> None
# Provided by the orchestrator; Phase 2 never imports Phase 3 directly.
Phase3IngestFn = Callable[[DocumentRecord, str], Awaitable[None]]


async def process_document(
    doc: DocumentRecord,
    correction_note: Optional[str] = None,
    phase3_ingest_fn: Optional[Phase3IngestFn] = None,
) -> Optional[str]:
    """Summarize one document and (optionally) deliver it to Phase 3.

    Returns the xml_blob string on success, None on failure.
    The caller is responsible for Phase 3 delivery via phase3_ingest_fn.
    """
    try:
        tier, prepared_text = route_and_prepare(doc)
        summary = summarize(doc, prepared_text, correction_note)
        xml_blob = build_xml(summary)

        await save_summary(doc.document_number, xml_blob, tier, "complete")
        await update_pipeline_state(doc.document_number, "SUMMARY_GENERATED")

        if phase3_ingest_fn is not None:
            await phase3_ingest_fn(doc, xml_blob)

        print(f"[Phase2] ✓ {doc.document_number} — Tier {tier}")
        return xml_blob

    except Exception as exc:
        print(f"[Phase2] ✗ {doc.document_number} — {exc}")
        await update_pipeline_state(doc.document_number, "SUMMARIZATION_FAILED")
        return None


async def run_pipeline(
    phase3_ingest_fn: Optional[Phase3IngestFn] = None,
) -> dict:
    """Process all INGESTED + is_relevant=true documents."""
    docs = await fetch_pending_documents()
    print(f"[Phase2] {len(docs)} documents to summarize")

    success, failed = 0, 0
    for doc in docs:
        result = await process_document(doc, phase3_ingest_fn=phase3_ingest_fn)
        if result is not None:
            success += 1
        else:
            failed += 1

    print(f"[Phase2] Done — {success} succeeded, {failed} failed")
    return {"processed": success, "failed": failed, "total": len(docs)}


async def handle_correction(
    document_number: str,
    error_detail: str,
    phase3_ingest_fn: Optional[Phase3IngestFn] = None,
) -> Optional[str]:
    """Rerun the LLM for a document after Phase 3 validation failure.

    Returns the new xml_blob on success, None if retries are exhausted.
    """
    attempts = await increment_correction_attempts(document_number)

    if attempts > _MAX_CORRECTION_RETRIES:
        print(f"[Phase2] {document_number} exceeded max correction retries — marking failed")
        await save_summary(document_number, "", 0, "failed")
        return None

    doc = await fetch_document_by_number(document_number)
    if not doc:
        print(f"[Phase2] Correction requested for unknown document: {document_number}")
        return None

    print(f"[Phase2] Correction {attempts}/{_MAX_CORRECTION_RETRIES} for {document_number}: {error_detail}")
    return await process_document(doc, correction_note=error_detail, phase3_ingest_fn=phase3_ingest_fn)