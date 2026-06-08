import os
from datetime import date
from pathlib import Path
from typing import List

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

from models import ConfirmedDocument

load_dotenv(Path(__file__).parent.parent / ".env")


def _get_connection():
    url = os.environ["DATABASE_URL"]
    # Strip SQLAlchemy driver prefix if present — psycopg2 expects plain postgresql://
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(url)


def is_already_processed(document_number: str) -> bool:
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM documents WHERE document_number = %s LIMIT 1",
                (document_number,),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def save_confirmed_document(doc: ConfirmedDocument) -> None:
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (
                    document_number, title, abstract, agency_names, document_type,
                    type, subtype, page_length, html_url, pdf_url, comment_url,
                    comments_close_on, effective_on, significant, publication_date,
                    confidence, is_relevant, regulation_category, filter_reason,
                    context_block, pipeline_state
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s
                )
                ON CONFLICT (document_number) DO NOTHING
                """,
                (
                    doc.document_number,
                    doc.title,
                    doc.abstract,
                    doc.agency_names,
                    doc.document_type,
                    doc.type,
                    doc.subtype,
                    doc.page_length,
                    doc.html_url,
                    doc.pdf_url,
                    doc.comment_url,
                    doc.comments_close_on.isoformat() if doc.comments_close_on else None,
                    doc.effective_on.isoformat() if doc.effective_on else None,
                    doc.significant,
                    doc.publication_date.isoformat(),
                    doc.confidence,
                    doc.is_relevant,
                    doc.regulation_category,
                    doc.filter_reason,
                    doc.context_block,
                    "INGESTED",
                ),
            )
        conn.commit()
    finally:
        conn.close()


def log_audit_entry(
    document_number: str,
    title: str,
    layer2_confidence: str,
    layer2_score: int,
    layer3_decision: bool,
    layer3_reason: str,
    was_cached: bool,
    run_date: date,
) -> None:
    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO filter_audit (
                    document_number, title, layer2_confidence, layer2_score,
                    layer3_decision, layer3_reason, was_cached, run_date
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    document_number,
                    title,
                    layer2_confidence,
                    layer2_score,
                    layer3_decision,
                    layer3_reason,
                    was_cached,
                    run_date.isoformat(),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_confirmed_documents_for_date(run_date: date) -> List[dict]:
    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM documents
                WHERE is_relevant = true
                  AND publication_date = %s
                """,
                (run_date.isoformat(),),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
