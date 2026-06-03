"""
phase_3/persistence.py
----------------------
Step 2: Database Storage and Automated Fail-Safe Routine.

Responsibilities
----------------
1. Idempotency guard — check if the document is already cached at DIGEST_SENT.
   If it is, return immediately without a second write. This makes the pipeline
   safe to re-run after crashes or scheduler restarts.

2. State promotion — write `documents.pipeline_state = 'DIGEST_SENT'` for
   documents that passed Step 1 validation. The document_number (the federal
   register's own unique identifier) acts as the primary key, so no duplicate
   rows are ever created.

Schema alignment (schema.sql / schemas.md)
------------------------------------------
Phase 3 only touches the `documents` table, and only the `pipeline_state`
column. The `summaries` table is read-only for Phase 3 — Phase 2 owns it.

  documents.pipeline_state values:
    'INGESTED'          — Phase 1 complete
    'SUMMARY_GENERATED' — Phase 2 complete (this is what we receive)
    'DIGEST_SENT'       — Phase 3 complete (this is what we set)

No new tables. No new columns. No schema changes.

Design note: raw SQL via SQLAlchemy text()
------------------------------------------
Rather than an ORM layer, we use raw parameterised SQL statements that map
1-to-1 with schema.sql. This keeps the queries readable, avoids ORM model
drift, and makes it easy for the Phase 1 teammate to verify no schema
modifications were made.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from phase_3.db import get_session_factory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

class PersistenceResult(BaseModel):
    """Outcome of a single persistence attempt."""
    document_number: str
    was_cached: bool        # True  → already at DIGEST_SENT, skipped write
    promoted: bool          # True  → just promoted from SUMMARY_GENERATED
    error: Optional[str] = None  # non-None → DB operation failed


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

_CHECK_STATE_SQL = text("""
    SELECT pipeline_state
    FROM   documents
    WHERE  document_number = :document_number
""")

_PROMOTE_STATE_SQL = text("""
    UPDATE documents
    SET    pipeline_state = 'DIGEST_SENT'
    WHERE  document_number = :document_number
      AND  pipeline_state  = 'SUMMARY_GENERATED'
""")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def persist_validated_document(
    document_number: str,
) -> PersistenceResult:
    """
    Commit a successfully validated document to the permanent cache by
    promoting its pipeline_state from SUMMARY_GENERATED → DIGEST_SENT.

    Idempotency guarantee
    ---------------------
    If the row is already at DIGEST_SENT (e.g. the pipeline re-ran after a
    crash), the UPDATE's WHERE clause silently matches zero rows and we return
    `was_cached=True`. No duplicate writes, no errors, no extra LLM calls.

    If the row does not exist at all, or is still at INGESTED (Phase 2
    hasn't finished), the UPDATE matches zero rows and we log a warning.
    The caller receives `promoted=False` with an explanatory error string.

    Args:
        document_number: The federal document number (primary key in `documents`).

    Returns:
        PersistenceResult describing the outcome.
    """
    session_factory = get_session_factory()

    async with session_factory() as session:  # type: AsyncSession
        async with session.begin():
            try:
                # -- 1. Read current state ----------------------------------
                row = await session.execute(
                    _CHECK_STATE_SQL,
                    {"document_number": document_number},
                )
                record = row.fetchone()

                if record is None:
                    # Document doesn't exist in the DB at all.
                    # This should not happen — Phase 1 writes it, Phase 2 updates it.
                    msg = (
                        f"[{document_number}] Document not found in `documents` table. "
                        "Cannot promote pipeline_state. Phase 1 or Phase 2 may not have "
                        "completed for this document."
                    )
                    logger.error(msg)
                    return PersistenceResult(
                        document_number=document_number,
                        was_cached=False,
                        promoted=False,
                        error=msg,
                    )

                current_state: str = record[0]

                # -- 2. Idempotency check -----------------------------------
                if current_state == "DIGEST_SENT":
                    logger.info(
                        "[%s] Already at DIGEST_SENT — reading from cache, skipping write.",
                        document_number,
                    )
                    return PersistenceResult(
                        document_number=document_number,
                        was_cached=True,
                        promoted=False,
                    )

                if current_state != "SUMMARY_GENERATED":
                    msg = (
                        f"[{document_number}] Unexpected pipeline_state '{current_state}'. "
                        "Expected 'SUMMARY_GENERATED'. Skipping promotion."
                    )
                    logger.warning(msg)
                    return PersistenceResult(
                        document_number=document_number,
                        was_cached=False,
                        promoted=False,
                        error=msg,
                    )

                # -- 3. Promote to DIGEST_SENT ------------------------------
                result = await session.execute(
                    _PROMOTE_STATE_SQL,
                    {"document_number": document_number},
                )
                rows_affected: int = result.rowcount

                if rows_affected == 0:
                    # Race condition: another process updated the row
                    # between our SELECT and UPDATE. Re-check is safe.
                    msg = (
                        f"[{document_number}] UPDATE matched 0 rows — "
                        "possible race condition. Row may have been updated "
                        "concurrently. Check current state manually."
                    )
                    logger.warning(msg)
                    return PersistenceResult(
                        document_number=document_number,
                        was_cached=False,
                        promoted=False,
                        error=msg,
                    )

                logger.info(
                    "[%s] Successfully promoted pipeline_state → DIGEST_SENT.",
                    document_number,
                )
                return PersistenceResult(
                    document_number=document_number,
                    was_cached=False,
                    promoted=True,
                )

            except Exception as exc:
                # session.begin() context manager rolls back on exception.
                msg = f"[{document_number}] DB error during state promotion: {exc}"
                logger.exception(msg)
                return PersistenceResult(
                    document_number=document_number,
                    was_cached=False,
                    promoted=False,
                    error=str(exc),
                )
