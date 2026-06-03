import os
from datetime import date
from typing import List

from supabase import create_client, Client

from models import ConfirmedDocument


def _client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def is_already_processed(document_number: str) -> bool:
    """Return True if document_number already exists in documents table."""
    result = (
        _client()
        .table("documents")
        .select("document_number")
        .eq("document_number", document_number)
        .execute()
    )
    return len(result.data) > 0


def save_confirmed_document(doc: ConfirmedDocument) -> None:
    """Upsert confirmed document into documents table. On conflict, do nothing."""
    row = {
        "document_number": doc.document_number,
        "title": doc.title,
        "abstract": doc.abstract,
        "agency_names": doc.agency_names,
        "document_type": doc.document_type,
        "type": doc.type,
        "subtype": doc.subtype,
        "page_length": doc.page_length,
        "html_url": doc.html_url,
        "pdf_url": doc.pdf_url,
        "comment_url": doc.comment_url,
        "comments_close_on": doc.comments_close_on.isoformat() if doc.comments_close_on else None,
        "effective_on": doc.effective_on.isoformat() if doc.effective_on else None,
        "significant": doc.significant,
        "publication_date": doc.publication_date.isoformat(),
        "confidence": doc.confidence,
        "is_relevant": doc.is_relevant,
        "regulation_category": doc.regulation_category,
        "filter_reason": doc.filter_reason,
        "context_block": doc.context_block,
        "pipeline_state": "INGESTED",
    }
    (
        _client()
        .table("documents")
        .upsert(row, on_conflict="document_number", ignore_duplicates=True)
        .execute()
    )


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
    """Insert a row into filter_audit for every document that reaches Layer 3."""
    row = {
        "document_number": document_number,
        "title": title,
        "layer2_confidence": layer2_confidence,
        "layer2_score": layer2_score,
        "layer3_decision": layer3_decision,
        "layer3_reason": layer3_reason,
        "was_cached": was_cached,
        "run_date": run_date.isoformat(),
    }
    _client().table("filter_audit").insert(row).execute()


# Phase 2 read interface — the only function Phase 2 should call.
def get_confirmed_documents_for_date(run_date: date) -> List[dict]:
    """Return all is_relevant=True documents for the given publication date."""
    result = (
        _client()
        .table("documents")
        .select("*")
        .eq("is_relevant", True)
        .eq("publication_date", run_date.isoformat())
        .execute()
    )
    return result.data
