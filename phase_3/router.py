"""
phase_3/router.py
-----------------
FastAPI router for Phase 3. Mounted at prefix /phase3 in the main app.

Implemented steps:
  Step 1 — Validation + self-correction retry loop
  Step 2 — Database storage and idempotency fail-safe

Steps 3-4 (digest compilation, platform handoff) will be added in later sprints.

Endpoints:
  POST /phase3/ingest                    - Receive Phase 2 payload, validate, persist
  GET  /phase3/status/{document_number}  - Check pipeline_state for a document
  POST /phase3/validate/test             - Dev utility: validate XML blob in isolation
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Body, HTTPException, Path, status
from pydantic import BaseModel
from sqlalchemy import text

from phase_3.db import get_session_factory
from phase_3.models import IngestPayload, ValidationResult
from phase_3.persistence import PersistenceResult, persist_validated_document
from phase_3.validator import validate_blob

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/phase3", tags=["Phase 3 — Post-Processing"])

# ---------------------------------------------------------------------------
# Configuration (will move to settings/env in a later sprint)
# ---------------------------------------------------------------------------

MAX_RETRIES = 2  # Maximum self-correction cycles before giving up

# Phase 2 correction endpoint — Phase 3 sends the error_detail back here.
# Phase 2 re-runs the LLM with the error as a correction prompt and returns
# a new xml_summary_blob. Set via environment variable in production.
PHASE2_CORRECTION_URL: str | None = None  # Set from env in main app startup


# ---------------------------------------------------------------------------
# Internal: retry loop
# ---------------------------------------------------------------------------

async def _ingest_with_retry(payload: IngestPayload) -> ValidationResult:
    """
    Run the validation + self-correction loop.

    Cycle:
      1. Validate the current xml_summary_blob.
      2. If passed → return the ValidationResult immediately.
      3. If failed → send error_detail to Phase 2's correction endpoint,
         receive a new xml_summary_blob, update payload, repeat.
      4. After MAX_RETRIES exhausted → return the final failed ValidationResult.

    Phase 3 never modifies documents.pipeline_state for failed documents.
    The row stays at SUMMARY_GENERATED. It is simply excluded from the
    digest query (which filters on pipeline_state = 'DIGEST_SENT').
    """
    doc_number = payload.document_record.document_number
    current_blob = payload.xml_summary_blob

    for attempt in range(1, MAX_RETRIES + 2):  # attempts: 1, 2, 3 (initial + 2 retries)
        logger.info(
            "[%s] Validation attempt %d/%d",
            doc_number,
            attempt,
            MAX_RETRIES + 1,
        )

        result = validate_blob(doc_number, current_blob)

        if result.passed:
            return result

        # --- Exhausted retries? -------------------------------------------------
        if attempt > MAX_RETRIES:
            logger.error(
                "[%s] Validation failed after %d attempt(s). "
                "Document excluded from digest. Final error:\n%s",
                doc_number,
                attempt,
                result.error_detail,
            )
            return result  # passed=False, caller raises 422

        # --- Send correction request to Phase 2 ---------------------------------
        if not PHASE2_CORRECTION_URL:
            logger.warning(
                "[%s] PHASE2_CORRECTION_URL is not configured. "
                "Cannot perform self-correction on attempt %d.",
                doc_number,
                attempt,
            )
            return result

        correction_payload = {
            "document_number": doc_number,
            "original_xml_blob": current_blob,
            "validation_error": result.error_detail,
            "attempt_number": attempt,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    PHASE2_CORRECTION_URL,
                    json=correction_payload,
                )
                resp.raise_for_status()
                correction_data = resp.json()
                current_blob = correction_data["xml_summary_blob"]
                logger.info(
                    "[%s] Received corrected blob from Phase 2 (attempt %d).",
                    doc_number,
                    attempt,
                )
        except (httpx.HTTPError, KeyError) as exc:
            logger.error(
                "[%s] Phase 2 correction request failed on attempt %d: %s",
                doc_number,
                attempt,
                exc,
            )
            # Treat a failed correction call as exhausted retries.
            # Build a new result rather than mutating the Pydantic model in place.
            return ValidationResult(
                document_number=result.document_number,
                passed=False,
                error_detail=(
                    f"{result.error_detail}\n\n"
                    f"[Phase 2 correction call also failed: {exc}]"
                ),
                url_stripped=result.url_stripped,
            )

    # Should not reach here, but satisfy type checker
    return result  # type: ignore[return-value]



class IngestResponse(BaseModel):
    """Combined Step 1 + Step 2 outcome returned from POST /phase3/ingest."""
    document_number: str
    validation: ValidationResult
    persistence: Optional[PersistenceResult] = None


# ---------------------------------------------------------------------------
# POST /phase3/ingest
# ---------------------------------------------------------------------------

@router.post(
    "/ingest",
    response_model=IngestResponse,
    summary="Receive a Phase 2 summary, validate (Step 1), and persist (Step 2).",
    responses={
        200: {"description": "Validation passed and document cached. was_cached=True means free cache hit."},
        422: {"description": "Validation failed after all retry attempts. Document excluded from digest."},
        500: {"description": "Persistence failed after validation passed."},
        503: {"description": "Unexpected internal error during validation."},
    },
)
async def ingest(payload: IngestPayload) -> IngestResponse:
    """
    Entry point for Phase 2 → Phase 3 handoff.

    Phase 2 posts:
      - document_record: metadata row from the `documents` table
      - xml_summary_blob: exact XML string from `summaries.xml_summary_blob`

    Phase 3 Step 1:
      Parses and validates the XML blob. On failure, sends error_detail back
      to Phase 2 for correction (up to MAX_RETRIES times). Raises HTTP 422
      after exhausted retries.

    Phase 3 Step 2:
      Promotes documents.pipeline_state from SUMMARY_GENERATED → DIGEST_SENT
      using document_number as the unique key. Idempotent: if already at
      DIGEST_SENT, returns was_cached=True without a second write.

    Steps 3-4 (digest compilation, delivery) will be wired in later sprints.
    """
    doc_number = payload.document_record.document_number

    # -- Step 1: Validate ---------------------------------------------------
    try:
        validation_result = await _ingest_with_retry(payload)
    except Exception as exc:
        logger.exception("[%s] Unexpected error during validation: %s", doc_number, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Internal validation error: {exc}",
        )

    if not validation_result.passed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "document_number": doc_number,
                "error": validation_result.error_detail,
                "message": (
                    f"Document failed validation after {MAX_RETRIES + 1} "
                    "attempt(s) and has been excluded from the digest. "
                    "Review the error detail and correct the summarization prompt."
                ),
            },
        )

    # -- Step 2: Persist ----------------------------------------------------
    try:
        persistence_result = await persist_validated_document(doc_number)
    except Exception as exc:
        logger.exception("[%s] Unexpected error during persistence: %s", doc_number, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Validation passed but DB write failed: {exc}",
        )

    if persistence_result.error:
        # Persistence returned a soft error (unexpected state, race condition, etc.)
        # Log it as an error but do NOT hide the validation success.
        # The caller can inspect the persistence field and decide.
        logger.error(
            "[%s] Persistence soft error: %s",
            doc_number,
            persistence_result.error,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "document_number": doc_number,
                "validation": "passed",
                "persistence_error": persistence_result.error,
            },
        )

    return IngestResponse(
        document_number=doc_number,
        validation=validation_result,
        persistence=persistence_result,
    )

# ---------------------------------------------------------------------------
# GET /phase3/status/{document_number}  — idempotency inspection
# ---------------------------------------------------------------------------

@router.get(
    "/status/{document_number}",
    summary="Return the current pipeline_state of a document (idempotency check).",
    responses={
        200: {"description": "Document found. pipeline_state returned."},
        404: {"description": "Document not found in the database."},
    },
)
async def get_document_status(
    document_number: str = Path(..., description="Federal document number, e.g. 2026-09841"),
) -> dict:
    """
    Read-only endpoint. Queries `documents.pipeline_state` directly.

    Useful for:
      - Confirming a document was promoted to DIGEST_SENT.
      - Checking cache status before re-submitting to /ingest.
      - Admin / monitoring dashboards.

    Returns: { "document_number": str, "pipeline_state": str }
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await session.execute(
            text("SELECT pipeline_state FROM documents WHERE document_number = :dn"),
            {"dn": document_number},
        )
        record = row.fetchone()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_number}' not found in the database.",
        )

    return {"document_number": document_number, "pipeline_state": record[0]}


# ---------------------------------------------------------------------------
# POST /phase3/validate/test  — dev/admin utility
# ---------------------------------------------------------------------------

@router.post(
    "/validate/test",
    response_model=ValidationResult,
    summary="[Dev] Validate a raw XML blob without triggering persistence or retry.",
    include_in_schema=True,
)
async def validate_test(
    document_number: str = Body(..., description="Document number for logging context"),
    xml_blob: str = Body(..., description="Raw XML blob to validate"),
) -> ValidationResult:
    """
    Developer utility: validate a raw XML blob in isolation.
    Does not write to the database or trigger the retry loop.
    Useful for testing Phase 2 output before wiring up the full pipeline.
    """
    return validate_blob(document_number, xml_blob)
