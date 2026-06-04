import os
from pathlib import Path
from typing import Optional

import httpx
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


async def process_document(
    doc: DocumentRecord,
    correction_note: Optional[str] = None,
) -> bool:
    """Summarize one document and deliver it to Phase 3. Returns True on success."""
    try:
        tier, prepared_text = route_and_prepare(doc)
        summary = summarize(doc, prepared_text, correction_note)
        xml_blob = build_xml(summary)

        await save_summary(doc.document_number, xml_blob, tier, "complete")
        await update_pipeline_state(doc.document_number, "SUMMARY_GENERATED")
        await _post_to_phase3(doc, xml_blob)

        print(f"[Phase2] ✓ {doc.document_number} — Tier {tier}")
        return True

    except Exception as exc:
        print(f"[Phase2] ✗ {doc.document_number} — {exc}")
        await update_pipeline_state(doc.document_number, "SUMMARIZATION_FAILED")
        return False


async def run_pipeline() -> dict:
    """Process all INGESTED + is_relevant=true documents."""
    docs = await fetch_pending_documents()
    print(f"[Phase2] {len(docs)} documents to summarize")

    success, failed = 0, 0
    for doc in docs:
        ok = await process_document(doc)
        if ok:
            success += 1
        else:
            failed += 1

    print(f"[Phase2] Done — {success} succeeded, {failed} failed")
    return {"processed": success, "failed": failed, "total": len(docs)}


async def handle_correction(document_number: str, error_detail: str) -> bool:
    """Rerun the LLM for a document after Phase 3 validation failure.
    Maximum _MAX_CORRECTION_RETRIES attempts. Marks as failed if exhausted.
    """
    attempts = await increment_correction_attempts(document_number)

    if attempts > _MAX_CORRECTION_RETRIES:
        print(
            f"[Phase2] {document_number} exceeded max correction retries "
            f"({_MAX_CORRECTION_RETRIES}) — marking failed"
        )
        await save_summary(document_number, "", 0, "failed")
        return False

    doc = await fetch_document_by_number(document_number)
    if not doc:
        print(f"[Phase2] Correction requested for unknown document: {document_number}")
        return False

    print(
        f"[Phase2] Correction attempt {attempts}/{_MAX_CORRECTION_RETRIES} "
        f"for {document_number}: {error_detail}"
    )
    return await process_document(doc, correction_note=error_detail)


async def _post_to_phase3(doc: DocumentRecord, xml_blob: str) -> None:
    """POST the validated summary to Phase 3's ingest endpoint."""
    phase3_url = os.environ["PHASE3_INGEST_URL"]

    payload = {
        "document_record": {
            "document_number": doc.document_number,
            "title": doc.title,
            "agency_names": doc.agency_names,
            "type": doc.type,
            "regulation_category": doc.regulation_category,
            "confidence": doc.confidence,
            "comments_close_on": (
                doc.comments_close_on.isoformat() if doc.comments_close_on else None
            ),
            "effective_on": (
                doc.effective_on.isoformat() if doc.effective_on else None
            ),
            "html_url": doc.html_url,
            "comment_url": doc.comment_url,
            "publication_date": doc.publication_date.isoformat(),
            "pipeline_state": "SUMMARY_GENERATED",
        },
        "xml_summary_blob": xml_blob,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(phase3_url, json=payload)
        resp.raise_for_status()