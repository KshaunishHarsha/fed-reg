"""
Unit tests for pipeline.py — all layer functions are mocked.
Tests the orchestration logic: ordering, cache hits, dry-run, return values.
"""
from datetime import date
from unittest.mock import MagicMock, patch, call

import pytest

from models import ConfirmedDocument, FilteredDocument, RawDocument
from pipeline import run_pipeline


_RUN_DATE = date(2024, 3, 15)


def _raw_doc(doc_number="2024-05000", doc_type="RULE") -> RawDocument:
    return RawDocument(
        document_number=doc_number,
        title="Animal Welfare Act Enforcement Rule",
        html_url="https://www.federalregister.gov/documents/test",
        publication_date=_RUN_DATE,
        type=doc_type,
        agency_names=["APHIS"],
        abstract="Amends AWA enforcement.",
    )


def _filtered_doc(doc_number="2024-05000", confidence="HIGH") -> FilteredDocument:
    return FilteredDocument(
        document_number=doc_number,
        title="Animal Welfare Act Enforcement Rule",
        html_url="https://www.federalregister.gov/documents/test",
        publication_date=_RUN_DATE,
        type="RULE",
        agency_names=["APHIS"],
        abstract="Amends AWA enforcement.",
        confidence=confidence,
    )


def _verification_result(is_relevant=True) -> MagicMock:
    result = MagicMock()
    result.is_relevant = is_relevant
    result.confidence_reason = "Direct AWA reference."
    result.regulation_category = "Final Rule"
    return result


# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------

def test_dry_run_returns_empty_list():
    raw = [_raw_doc()]
    filtered = [_filtered_doc()]

    with (
        patch("pipeline.fetch_documents", return_value=raw),
        patch("pipeline.apply_keyword_filter", return_value=filtered[0]),
        patch("pipeline.is_already_processed") as mock_cache,
        patch("pipeline.verify_document") as mock_ai,
        patch("pipeline.save_confirmed_document") as mock_save,
        patch("pipeline.log_audit_entry") as mock_audit,
    ):
        result = run_pipeline(_RUN_DATE, dry_run=True)

    assert result == []


def test_dry_run_does_not_call_ai_or_db():
    raw = [_raw_doc()]
    filtered = [_filtered_doc()]

    with (
        patch("pipeline.fetch_documents", return_value=raw),
        patch("pipeline.apply_keyword_filter", return_value=filtered[0]),
        patch("pipeline.is_already_processed") as mock_cache,
        patch("pipeline.verify_document") as mock_ai,
        patch("pipeline.save_confirmed_document") as mock_save,
        patch("pipeline.log_audit_entry") as mock_audit,
    ):
        run_pipeline(_RUN_DATE, dry_run=True)

    mock_cache.assert_not_called()
    mock_ai.assert_not_called()
    mock_save.assert_not_called()
    mock_audit.assert_not_called()


# ---------------------------------------------------------------------------
# Cache hit path
# ---------------------------------------------------------------------------

def test_cache_hit_skips_ai_and_save():
    raw = [_raw_doc()]
    filtered = [_filtered_doc()]

    with (
        patch("pipeline.fetch_documents", return_value=raw),
        patch("pipeline.apply_keyword_filter", return_value=filtered[0]),
        patch("pipeline.is_already_processed", return_value=True),
        patch("pipeline.verify_document") as mock_ai,
        patch("pipeline.save_confirmed_document") as mock_save,
        patch("pipeline.log_audit_entry") as mock_audit,
    ):
        result = run_pipeline(_RUN_DATE)

    mock_ai.assert_not_called()
    mock_save.assert_not_called()
    assert result == []


def test_cache_hit_still_logs_audit_entry():
    raw = [_raw_doc()]
    filtered = [_filtered_doc()]

    with (
        patch("pipeline.fetch_documents", return_value=raw),
        patch("pipeline.apply_keyword_filter", return_value=filtered[0]),
        patch("pipeline.is_already_processed", return_value=True),
        patch("pipeline.verify_document"),
        patch("pipeline.save_confirmed_document"),
        patch("pipeline.log_audit_entry") as mock_audit,
    ):
        run_pipeline(_RUN_DATE)

    mock_audit.assert_called_once()
    audit_kwargs = mock_audit.call_args
    # was_cached=True is the 7th positional arg
    assert audit_kwargs[0][6] is True


# ---------------------------------------------------------------------------
# Relevant document path
# ---------------------------------------------------------------------------

def test_relevant_doc_is_saved_and_returned():
    raw = [_raw_doc()]
    filtered = [_filtered_doc()]
    verification = _verification_result(is_relevant=True)

    with (
        patch("pipeline.fetch_documents", return_value=raw),
        patch("pipeline.apply_keyword_filter", return_value=filtered[0]),
        patch("pipeline.is_already_processed", return_value=False),
        patch("pipeline.verify_document", return_value=verification),
        patch("pipeline.save_confirmed_document") as mock_save,
        patch("pipeline.log_audit_entry"),
    ):
        result = run_pipeline(_RUN_DATE)

    assert len(result) == 1
    assert isinstance(result[0], ConfirmedDocument)
    assert result[0].is_relevant is True
    mock_save.assert_called_once()


def test_irrelevant_doc_is_not_saved():
    raw = [_raw_doc()]
    filtered = [_filtered_doc(confidence="NEEDS_CONFIRMATION")]
    verification = _verification_result(is_relevant=False)

    with (
        patch("pipeline.fetch_documents", return_value=raw),
        patch("pipeline.apply_keyword_filter", return_value=filtered[0]),
        patch("pipeline.is_already_processed", return_value=False),
        patch("pipeline.verify_document", return_value=verification),
        patch("pipeline.save_confirmed_document") as mock_save,
        patch("pipeline.log_audit_entry"),
    ):
        result = run_pipeline(_RUN_DATE)

    assert result == []
    mock_save.assert_not_called()


def test_audit_logged_for_every_layer3_doc():
    """Every doc that reaches Layer 3 (non-cached) gets an audit entry."""
    raw = [_raw_doc("2024-05000"), _raw_doc("2024-05001")]
    filtered = [_filtered_doc("2024-05000"), _filtered_doc("2024-05001")]
    verification = _verification_result(is_relevant=True)

    filter_iter = iter(filtered)

    with (
        patch("pipeline.fetch_documents", return_value=raw),
        patch("pipeline.apply_keyword_filter", side_effect=lambda d: next(filter_iter)),
        patch("pipeline.is_already_processed", return_value=False),
        patch("pipeline.verify_document", return_value=verification),
        patch("pipeline.save_confirmed_document"),
        patch("pipeline.log_audit_entry") as mock_audit,
    ):
        run_pipeline(_RUN_DATE)

    assert mock_audit.call_count == 2


# ---------------------------------------------------------------------------
# Keyword filter drop path
# ---------------------------------------------------------------------------

def test_keyword_dropped_docs_never_reach_layer3():
    raw = [_raw_doc()]

    with (
        patch("pipeline.fetch_documents", return_value=raw),
        patch("pipeline.apply_keyword_filter", return_value=None),  # dropped
        patch("pipeline.is_already_processed") as mock_cache,
        patch("pipeline.verify_document") as mock_ai,
        patch("pipeline.save_confirmed_document") as mock_save,
        patch("pipeline.log_audit_entry") as mock_audit,
    ):
        result = run_pipeline(_RUN_DATE)

    assert result == []
    mock_cache.assert_not_called()
    mock_ai.assert_not_called()
    mock_save.assert_not_called()
    mock_audit.assert_not_called()
