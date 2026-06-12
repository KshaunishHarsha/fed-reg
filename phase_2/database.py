import os
from datetime import date
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from phase_2.models import DocumentRecord

load_dotenv(Path(__file__).parent.parent / ".env")

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    return _engine


async def fetch_pending_documents() -> List[DocumentRecord]:
    """Fetch all INGESTED + is_relevant=true documents for summarization."""
    async with _get_engine().begin() as conn:
        result = await conn.execute(text("""
            SELECT
                document_number, title, agency_names, type, regulation_category,
                page_length, confidence, abstract, context_block,
                comments_close_on, effective_on, html_url, comment_url,
                publication_date, pipeline_state
            FROM documents
            WHERE pipeline_state = 'INGESTED'
              AND is_relevant = true
            ORDER BY publication_date DESC, document_number
        """))
        rows = result.mappings().all()

    return [_row_to_record(row) for row in rows]


async def fetch_document_by_number(document_number: str) -> Optional[DocumentRecord]:
    """Fetch a single document by document_number regardless of pipeline_state."""
    async with _get_engine().begin() as conn:
        result = await conn.execute(text("""
            SELECT
                document_number, title, agency_names, type, regulation_category,
                page_length, confidence, abstract, context_block,
                comments_close_on, effective_on, html_url, comment_url,
                publication_date, pipeline_state
            FROM documents
            WHERE document_number = :doc_num
            LIMIT 1
        """), {"doc_num": document_number})
        row = result.mappings().fetchone()

    return _row_to_record(row) if row else None


async def fetch_summary_blob(document_number: str) -> Optional[str]:
    """Fetch the stored xml_summary_blob for a document, or None if not summarized yet."""
    async with _get_engine().begin() as conn:
        result = await conn.execute(text("""
            SELECT xml_summary_blob
            FROM summaries
            WHERE document_number = :doc_num
            LIMIT 1
        """), {"doc_num": document_number})
        row = result.mappings().fetchone()

    return row["xml_summary_blob"] if row else None


async def save_summary(
    document_number: str,
    xml_summary_blob: str,
    summarization_tier: int,
    summarization_status: str = "complete",
) -> None:
    """Upsert a row into the summaries table."""
    async with _get_engine().begin() as conn:
        await conn.execute(text("""
            INSERT INTO summaries
                (document_number, xml_summary_blob, summarization_tier, summarization_status)
            VALUES
                (:doc_num, :blob, :tier, :status)
            ON CONFLICT (document_number) DO UPDATE SET
                xml_summary_blob      = EXCLUDED.xml_summary_blob,
                summarization_tier    = EXCLUDED.summarization_tier,
                summarization_status  = EXCLUDED.summarization_status,
                updated_at            = now()
        """), {
            "doc_num": document_number,
            "blob": xml_summary_blob,
            "tier": summarization_tier,
            "status": summarization_status,
        })


async def update_pipeline_state(document_number: str, state: str) -> None:
    """Advance (or revert) pipeline_state on a document row."""
    async with _get_engine().begin() as conn:
        await conn.execute(text("""
            UPDATE documents
            SET pipeline_state = :state
            WHERE document_number = :doc_num
        """), {"state": state, "doc_num": document_number})


async def increment_correction_attempts(document_number: str) -> int:
    """Bump correction_attempts counter and return the new value."""
    async with _get_engine().begin() as conn:
        result = await conn.execute(text("""
            UPDATE summaries
            SET correction_attempts = correction_attempts + 1
            WHERE document_number = :doc_num
            RETURNING correction_attempts
        """), {"doc_num": document_number})
        row = result.fetchone()
    return row[0] if row else 0


def _row_to_record(row) -> DocumentRecord:
    return DocumentRecord(
        document_number=row["document_number"],
        title=row["title"],
        agency_names=row["agency_names"] or [],
        type=row["type"],
        regulation_category=row["regulation_category"],
        page_length=row["page_length"],
        confidence=row["confidence"],
        abstract=row["abstract"],
        context_block=row["context_block"],
        comments_close_on=row["comments_close_on"],
        effective_on=row["effective_on"],
        html_url=row["html_url"],
        comment_url=row["comment_url"],
        publication_date=row["publication_date"],
        pipeline_state=row["pipeline_state"],
    )