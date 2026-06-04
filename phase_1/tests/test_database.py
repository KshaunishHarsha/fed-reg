"""
Unit tests for database.py — Supabase client is fully mocked.
No real network calls or environment variables required.
"""
from datetime import date
from unittest.mock import MagicMock, patch, call

import pytest

import database
from models import ConfirmedDocument


def _make_confirmed(**kwargs) -> ConfirmedDocument:
    defaults = {
        "document_number": "2024-05000",
        "title": "Animal Welfare Act Enforcement Rule",
        "html_url": "https://www.federalregister.gov/documents/2024-05000",
        "publication_date": date(2024, 3, 15),
        "agency_names": ["Animal and Plant Health Inspection Service"],
        "type": "RULE",
        "confidence": "HIGH",
        "is_relevant": True,
        "regulation_category": "Final Rule",
        "filter_reason": "Document directly references the Animal Welfare Act.",
    }
    defaults.update(kwargs)
    return ConfirmedDocument(**defaults)


def _make_mock_client(select_data=None):
    """Build a MagicMock Supabase client with controllable select results."""
    client = MagicMock()
    # Chain: .table().select().eq().execute().data
    client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = (
        select_data if select_data is not None else []
    )
    return client


# ---------------------------------------------------------------------------
# is_already_processed
# ---------------------------------------------------------------------------

def test_is_already_processed_returns_false_when_not_in_db():
    client = _make_mock_client(select_data=[])
    with patch("database._client", return_value=client):
        assert database.is_already_processed("2024-05000") is False


def test_is_already_processed_returns_true_when_in_db():
    client = _make_mock_client(select_data=[{"document_number": "2024-05000"}])
    with patch("database._client", return_value=client):
        assert database.is_already_processed("2024-05000") is True


def test_is_already_processed_queries_correct_table_and_field():
    client = _make_mock_client(select_data=[])
    with patch("database._client", return_value=client):
        database.is_already_processed("2024-05000")

    client.table.assert_called_once_with("documents")
    client.table.return_value.select.assert_called_once_with("document_number")
    client.table.return_value.select.return_value.eq.assert_called_once_with(
        "document_number", "2024-05000"
    )


# ---------------------------------------------------------------------------
# save_confirmed_document
# ---------------------------------------------------------------------------

def test_save_confirmed_document_calls_upsert():
    client = MagicMock()
    doc = _make_confirmed()

    with patch("database._client", return_value=client):
        database.save_confirmed_document(doc)

    client.table.assert_called_once_with("documents")
    upsert_call = client.table.return_value.upsert
    upsert_call.assert_called_once()
    kwargs = upsert_call.call_args
    assert kwargs[1].get("on_conflict") == "document_number"
    assert kwargs[1].get("ignore_duplicates") is True


def test_save_confirmed_document_sets_pipeline_state_to_ingested():
    client = MagicMock()
    doc = _make_confirmed()

    with patch("database._client", return_value=client):
        database.save_confirmed_document(doc)

    row = client.table.return_value.upsert.call_args[0][0]
    assert row["pipeline_state"] == "INGESTED"


def test_save_confirmed_document_serializes_dates_as_isoformat():
    client = MagicMock()
    doc = _make_confirmed(
        comments_close_on=date(2024, 4, 1),
        effective_on=date(2024, 5, 1),
    )

    with patch("database._client", return_value=client):
        database.save_confirmed_document(doc)

    row = client.table.return_value.upsert.call_args[0][0]
    assert row["comments_close_on"] == "2024-04-01"
    assert row["effective_on"] == "2024-05-01"
    assert row["publication_date"] == "2024-03-15"


def test_save_confirmed_document_handles_none_dates():
    client = MagicMock()
    doc = _make_confirmed(comments_close_on=None, effective_on=None)

    with patch("database._client", return_value=client):
        database.save_confirmed_document(doc)

    row = client.table.return_value.upsert.call_args[0][0]
    assert row["comments_close_on"] is None
    assert row["effective_on"] is None


# ---------------------------------------------------------------------------
# log_audit_entry
# ---------------------------------------------------------------------------

def test_log_audit_entry_inserts_to_filter_audit():
    client = MagicMock()

    with patch("database._client", return_value=client):
        database.log_audit_entry(
            document_number="2024-05000",
            title="Test",
            layer2_confidence="HIGH",
            layer2_score=None,
            layer3_decision=True,
            layer3_reason="Direct AWA reference.",
            was_cached=False,
            run_date=date(2024, 3, 15),
        )

    client.table.assert_called_once_with("filter_audit")
    client.table.return_value.insert.assert_called_once()
    row = client.table.return_value.insert.call_args[0][0]
    assert row["document_number"] == "2024-05000"
    assert row["was_cached"] is False
    assert row["run_date"] == "2024-03-15"


def test_log_audit_entry_records_cache_hits():
    client = MagicMock()

    with patch("database._client", return_value=client):
        database.log_audit_entry(
            document_number="2024-05000",
            title="Test",
            layer2_confidence="HIGH",
            layer2_score=None,
            layer3_decision=None,
            layer3_reason="cache hit",
            was_cached=True,
            run_date=date(2024, 3, 15),
        )

    row = client.table.return_value.insert.call_args[0][0]
    assert row["was_cached"] is True
    assert row["layer3_decision"] is None


# ---------------------------------------------------------------------------
# get_confirmed_documents_for_date
# ---------------------------------------------------------------------------

def test_get_confirmed_documents_for_date_returns_data():
    expected = [{"document_number": "2024-05000", "title": "Test", "is_relevant": True}]
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = expected

    with patch("database._client", return_value=client):
        result = database.get_confirmed_documents_for_date(date(2024, 3, 15))

    assert result == expected


def test_get_confirmed_documents_for_date_filters_by_relevant_and_date():
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    with patch("database._client", return_value=client):
        database.get_confirmed_documents_for_date(date(2024, 3, 15))

    chain = client.table.return_value.select.return_value.eq
    first_eq = chain.call_args_list[0]
    assert first_eq == call("is_relevant", True)
