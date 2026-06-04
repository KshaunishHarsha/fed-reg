"""
phase_3/router.py
-----------------
FastAPI router for Phase 3. Mounted at prefix /phase3 in the main app.

Implemented steps:
  Step 1 — Validation + self-correction retry loop
  Step 2 — Database storage and idempotency fail-safe
  Step 3 — Digest compilation and dual-layer email layout

Step 4 (platform handoff) will be added in the next sprint.

Endpoints:
  POST /phase3/run                       - [CRON] Single entry point: runs Phase 1 → 2 → 3 end-to-end
  POST /phase3/ingest                    - Receive Phase 2 payload, validate, persist (called by Phase 2)
  GET  /phase3/status/{document_number}  - Check pipeline_state for a document
  POST /phase3/digest/test               - [Dev] Compile email for a date without running the full pipeline
  POST /phase3/validate/test             - [Dev] Validate a raw XML blob in isolation
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Optional

import httpx
from fastapi import APIRouter, Body, HTTPException, Path, Query, status
from pydantic import BaseModel
from sqlalchemy import text

from phase_3.db import get_session_factory
from phase_3.digest_builder import DigestPackage, build_digest
from phase_3.digest_query import fetch_digest_rows
from phase_3.models import IngestPayload, ValidationResult
from phase_3.persistence import PersistenceResult, persist_validated_document
from phase_3.validator import validate_blob

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/phase3", tags=["Phase 3 — Post-Processing"])

# ---------------------------------------------------------------------------
# Configuration — all URLs read from environment variables at startup
# ---------------------------------------------------------------------------

MAX_RETRIES = 2  # Maximum self-correction cycles before giving up

# Phase 1: document ingestion service
# Expected: POST {PHASE1_RUN_URL}  →  triggers today's Federal Register pull
# Returns any JSON body (Phase 3 only checks HTTP 2xx for success).
PHASE1_RUN_URL: str | None = os.environ.get("PHASE1_RUN_URL")  # e.g. http://localhost:8001/phase1/run

# Phase 2: summarization service
# Expected: POST {PHASE2_RUN_URL}  →  triggers LLM summarization for INGESTED docs
# Returns any JSON body (Phase 3 only checks HTTP 2xx for success).
PHASE2_RUN_URL: str | None = os.environ.get("PHASE2_RUN_URL")  # e.g. http://localhost:8002/phase2/run

# Phase 2 correction endpoint — Phase 3 sends the error_detail back here
# so Phase 2 can re-run the LLM with the error as a correction prompt.
PHASE2_CORRECTION_URL: str | None = os.environ.get("PHASE2_CORRECTION_URL")


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
# POST /phase3/run  — PRODUCTION CRON ENTRY POINT
# ---------------------------------------------------------------------------

class PipelineRunResult(BaseModel):
    """Summary result returned by the single cron endpoint."""
    run_date: date
    phase1_ok: bool
    phase2_ok: bool
    phase3_ok: bool
    is_zero_result: bool
    section_a_count: int = 0
    section_b_count: int = 0
    section_c_count: int = 0
    total_documents: int = 0
    phase1_error: Optional[str] = None
    phase2_error: Optional[str] = None
    phase3_error: Optional[str] = None


@router.post(
    "/run",
    response_model=PipelineRunResult,
    summary="[CRON] Run the full pipeline: Phase 1 → Phase 2 → Phase 3.",
    responses={
        200: {"description": "Pipeline completed (check per-phase ok flags for partial failures)."},
        503: {"description": "Unrecoverable error prevented the pipeline from starting."},
    },
)
async def run_pipeline(
    target_date: Optional[date] = Query(
        default=None,
        description="Date to run the pipeline for. Defaults to today (UTC). Use for backfills.",
    ),
) -> PipelineRunResult:
    """
    Single entry point for the daily cron job.

    Execution order:
      1. POST to PHASE1_RUN_URL  — ingests today's Federal Register documents.
      2. POST to PHASE2_RUN_URL  — summarizes newly INGESTED documents via LLM.
      3. Internally runs Phase 3 digest compilation on SUMMARY_GENERATED documents.

    Each phase is attempted independently. If Phase 1 fails, Phase 2 and 3 still
    run against whatever documents are already in the database from previous runs.
    This means a Phase 1 outage does not silence the digest — it just means today's
    new documents may be missing from this run.

    The response contains per-phase ok flags and error strings so the cron
    scheduler / alerting system can identify exactly which phase failed.

    Environment variables required:
      PHASE1_RUN_URL         — e.g. http://phase1-service/phase1/run
      PHASE2_RUN_URL         — e.g. http://phase2-service/phase2/run
    """
    from datetime import datetime, timezone

    run_date = target_date or datetime.now(timezone.utc).date()
    result = PipelineRunResult(
        run_date=run_date,
        phase1_ok=False,
        phase2_ok=False,
        phase3_ok=False,
        is_zero_result=False,
    )

    # -- Phase 1: Ingestion -----------------------------------------------------
    if not PHASE1_RUN_URL:
        logger.warning("[/run] PHASE1_RUN_URL not configured — skipping Phase 1.")
        result.phase1_error = "PHASE1_RUN_URL not configured."
    else:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(PHASE1_RUN_URL, json={"target_date": run_date.isoformat()})
                resp.raise_for_status()
                result.phase1_ok = True
                logger.info("[/run] Phase 1 completed (HTTP %d).", resp.status_code)
        except httpx.HTTPError as exc:
            result.phase1_error = f"Phase 1 HTTP error: {exc}"
            logger.error("[/run] Phase 1 failed: %s", exc)

    # -- Phase 2: Summarization -------------------------------------------------
    if not PHASE2_RUN_URL:
        logger.warning("[/run] PHASE2_RUN_URL not configured — skipping Phase 2.")
        result.phase2_error = "PHASE2_RUN_URL not configured."
    else:
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:  # LLM calls are slow
                resp = await client.post(PHASE2_RUN_URL, json={"target_date": run_date.isoformat()})
                resp.raise_for_status()
                result.phase2_ok = True
                logger.info("[/run] Phase 2 completed (HTTP %d).", resp.status_code)
        except httpx.HTTPError as exc:
            result.phase2_error = f"Phase 2 HTTP error: {exc}"
            logger.error("[/run] Phase 2 failed: %s", exc)

    # -- Phase 3: Digest compilation --------------------------------------------
    # Runs regardless of Phase 1/2 outcome — always compile whatever is in the DB.
    try:
        rows = await fetch_digest_rows(run_date)
        package = build_digest(rows, run_date)
        result.phase3_ok = True
        result.is_zero_result = package.is_zero_result
        result.section_a_count = package.section_a_count
        result.section_b_count = package.section_b_count
        result.section_c_count = package.section_c_count
        result.total_documents = package.total_documents
        logger.info(
            "[/run] Phase 3 digest built — A:%d B:%d C:%d (zero=%s).",
            package.section_a_count,
            package.section_b_count,
            package.section_c_count,
            package.is_zero_result,
        )
        # TODO Step 4: pass `package` to platform_handoff.send_digest(package)
    except Exception as exc:
        result.phase3_error = f"Phase 3 error: {exc}"
        logger.exception("[/run] Phase 3 failed: %s", exc)

    return result


# ---------------------------------------------------------------------------
# POST /phase3/digest/test  — DEV ONLY: compile email without running pipeline
# ---------------------------------------------------------------------------

@router.post(
    "/digest/test",
    response_model=DigestPackage,
    summary="[Dev] Compile digest email for a date without running Phase 1 or 2.",
    include_in_schema=True,
    responses={
        200: {"description": "Digest compiled from existing DB rows. is_zero_result=True if none found."},
        503: {"description": "Database or template rendering error."},
    },
)
async def build_digest_test(
    target_date: Optional[date] = Query(
        default=None,
        description="Date to compile for (YYYY-MM-DD). Defaults to today (UTC).",
    ),
) -> DigestPackage:
    """
    DEV / TESTING ONLY — does NOT call Phase 1 or Phase 2.

    Reads whatever SUMMARY_GENERATED rows are already in the database for
    `target_date` and compiles the full dual-layer email package from them.
    Use this to preview the email layout after inserting dummy data directly
    into the database without needing to run the full pipeline.

    For the production cron-triggered flow, use POST /phase3/run instead.
    """
    from datetime import datetime, timezone

    run_date = target_date or datetime.now(timezone.utc).date()

    try:
        rows = await fetch_digest_rows(run_date)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database error while fetching digest rows: {exc}",
        )

    try:
        package = build_digest(rows, run_date)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Error during digest compilation: {exc}",
        )

    return package


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
