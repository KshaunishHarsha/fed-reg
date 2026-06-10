"""
phase_3/digest_query.py
-----------------------
Step 3.3 — Database query layer for the daily digest compilation.

Fetches all documents that have passed Phase 2 summarization and are ready
to be compiled into today's digest. Joins `documents` with `summaries` to
get both the metadata and the LLM-generated XML blob in one round trip.

Query mirrors the reference query in schema.sql (lines 103-126) with one
change: we read from pipeline_state = 'SUMMARY_GENERATED' (not DIGEST_SENT)
because Step 3 runs BEFORE Step 2's final promotion in a normal pipeline
run. After the digest is compiled and sent, the scheduler marks each document
DIGEST_SENT via the existing persist_validated_document() in persistence.py.

Schema columns used (read-only):
  documents : document_number, title, agency_names, type, regulation_category,
              confidence, comments_close_on, effective_on, html_url,
              comment_url, publication_date
  summaries : xml_summary_blob
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from phase_3.db import get_session_factory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Row dataclass — one per document returned from the query
# ---------------------------------------------------------------------------

@dataclass
class DigestRow:
    """
    Flat representation of one joined documents+summaries row.
    All values come directly from the database — zero LLM involvement here.
    The xml_summary_blob is parsed later by the digest builder.
    """
    document_number: str
    title: str
    agency_names: List[str]
    type: Optional[str]                  # PRORULE | RULE | NOTICE | None
    regulation_category: Optional[str]   # Proposed Rule | Final Rule | Notice | Other
    confidence: Optional[str]            # relevancy grade: HIGH | MEDIUM | LOW
    comments_close_on: Optional[date]
    effective_on: Optional[date]
    html_url: Optional[str]
    comment_url: Optional[str]
    publication_date: date
    xml_summary_blob: str
    abstract: Optional[str]
    summarization_tier: Optional[int]


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

_DIGEST_QUERY = text("""
    SELECT
        d.document_number,
        d.title,
        d.agency_names,
        d.type,
        d.regulation_category,
        d.confidence,
        d.comments_close_on,
        d.effective_on,
        d.html_url,
        d.comment_url,
        d.publication_date,
        s.xml_summary_blob,
        d.abstract,
        s.summarization_tier
    FROM documents d
    INNER JOIN summaries s ON d.document_number = s.document_number
    WHERE d.pipeline_state IN ('SUMMARY_GENERATED', 'DIGEST_SENT')
      AND d.publication_date = :target_date
    ORDER BY
        CASE d.type
            WHEN 'PRORULE' THEN 1
            WHEN 'RULE'    THEN 2
            WHEN 'NOTICE'  THEN 3
            ELSE                4
        END,
        d.comments_close_on ASC NULLS LAST
""")


async def fetch_digest_rows(target_date: date) -> List[DigestRow]:
    """
    Pull all SUMMARY_GENERATED documents for `target_date` from the database.

    Returns an empty list if no documents match — the caller (digest_builder)
    treats this as the circuit-breaker condition and sends the zero-result email.

    Args:
        target_date: The calendar date to compile the digest for (usually today).

    Returns:
        List of DigestRow objects, pre-sorted by urgency (PRORULE first, then
        RULE/NOTICE, then everything else, with soonest comment deadlines first).
    """
    session_factory = get_session_factory()
    rows: List[DigestRow] = []

    async with session_factory() as session:  # type: AsyncSession
        result = await session.execute(_DIGEST_QUERY, {"target_date": target_date})
        records = result.fetchall()

    for rec in records:
        rows.append(DigestRow(
            document_number=rec[0],
            title=rec[1],
            agency_names=list(rec[2]) if rec[2] else [],
            type=rec[3],
            regulation_category=rec[4],
            confidence=rec[5],
            comments_close_on=rec[6],
            effective_on=rec[7],
            html_url=rec[8],
            comment_url=rec[9],
            publication_date=rec[10],
            xml_summary_blob=rec[11],
            abstract=rec[12],
            summarization_tier=rec[13],
        ))

    logger.info(
        "[DigestQuery] %d document(s) found for %s.",
        len(rows),
        target_date.isoformat(),
    )
    return rows
