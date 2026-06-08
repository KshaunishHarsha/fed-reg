"""
Unit tests for database.py — psycopg2 connection is fully mocked.
No real network calls or environment variables required.
"""
from datetime import date
from unittest.mock import MagicMock, patch

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


def _make_mock_connection(fetchone=None, fetchall=None):
    """Build a MagicMock psycopg2 connection with controllable cursor results."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchone.return_value = fetchone
    mock_cursor.fetchall.return_value = fetchall if fetchall is not None else []
    return mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# is_already_processed
# ---------------------------------------------------------------------------

def test_is_already_processed_returns_false_when_not_in_db():
    mock_conn, _ = _make_mock_connection(fetchone=None)
    with patch("database._get_connection", return_value=mock_conn):
        assert database.is_already_processed("2024-05000") is False


def test_is_already_processed_returns_true_when_in_db():
    mock_conn, _ = _make_mock_connection(fetchone=(1,))
    with patch("database._get_connection", return_value=mock_conn):
        assert database.is_already_processed("2024-05000") is True


def test_is_already_processed_queries_correct_table_and_field():
    mock_conn, mock_cursor = _make_mock_connection(fetchone=None)
    with patch("database._get_connection", return_value=mock_conn):
        database.is_already_processed("2024-05000")

    sql = mock_cursor.execute.call_args[0][0]
    params = mock_cursor.execute.call_args[0][1]
    assert "documents" in sql
    assert "document_number" in sql
    assert "2024-05000" in params


# ---------------------------------------------------------------------------
# save_confirmed_document
# ---------------------------------------------------------------------------

def test_save_confirmed_document_executes_and_commits():
    mock_conn, mock_cursor = _make_mock_connection()
    doc = _make_confirmed()

    with patch("database._get_connection", return_value=mock_conn):
        database.save_confirmed_document(doc)

    mock_cursor.execute.assert_called_once()
    mock_conn.commit.assert_called_once()


def test_save_confirmed_document_sets_pipeline_state_to_ingested():
    mock_conn, mock_cursor = _make_mock_connection()
    doc = _make_confirmed()

    with patch("database._get_connection", return_value=mock_conn):
        database.save_confirmed_document(doc)

    params = mock_cursor.execute.call_args[0][1]
    assert "INGESTED" in params


def test_save_confirmed_document_serializes_dates_as_isoformat():
    mock_conn, mock_cursor = _make_mock_connection()
    doc = _make_confirmed(
        comments_close_on=date(2024, 4, 1),
        effective_on=date(2024, 5, 1),
    )

    with patch("database._get_connection", return_value=mock_conn):
        database.save_confirmed_document(doc)

    params = mock_cursor.execute.call_args[0][1]
    assert "2024-04-01" in params
    assert "2024-05-01" in params
    assert "2024-03-15" in params


def test_save_confirmed_document_handles_none_dates():
    mock_conn, mock_cursor = _make_mock_connection()
    doc = _make_confirmed(comments_close_on=None, effective_on=None)

    with patch("database._get_connection", return_value=mock_conn):
        database.save_confirmed_document(doc)

    params = mock_cursor.execute.call_args[0][1]
    # Index 11 = comments_close_on, index 12 = effective_on
    assert params[11] is None
    assert params[12] is None


# ---------------------------------------------------------------------------
# log_audit_entry
# ---------------------------------------------------------------------------

def test_log_audit_entry_inserts_to_filter_audit():
    mock_conn, mock_cursor = _make_mock_connection()

    with patch("database._get_connection", return_value=mock_conn):
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

    sql = mock_cursor.execute.call_args[0][0]
    params = mock_cursor.execute.call_args[0][1]
    assert "filter_audit" in sql
    assert "2024-05000" in params
    assert "2024-03-15" in params
    assert False in params
    mock_conn.commit.assert_called_once()


def test_log_audit_entry_records_cache_hits():
    mock_conn, mock_cursor = _make_mock_connection()

    with patch("database._get_connection", return_value=mock_conn):
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

    params = mock_cursor.execute.call_args[0][1]
    assert True in params
    assert None in params


# ---------------------------------------------------------------------------
# get_confirmed_documents_for_date
# ---------------------------------------------------------------------------

def test_get_confirmed_documents_for_date_returns_data():
    expected = [{"document_number": "2024-05000", "title": "Test", "is_relevant": True}]
    mock_conn, _ = _make_mock_connection(fetchall=expected)

    with patch("database._get_connection", return_value=mock_conn):
        result = database.get_confirmed_documents_for_date(date(2024, 3, 15))

    assert result == expected


def test_get_confirmed_documents_for_date_filters_by_relevant_and_date():
    mock_conn, mock_cursor = _make_mock_connection(fetchall=[])

    with patch("database._get_connection", return_value=mock_conn):
        database.get_confirmed_documents_for_date(date(2024, 3, 15))

    sql = mock_cursor.execute.call_args[0][0]
    params = mock_cursor.execute.call_args[0][1]
    assert "is_relevant" in sql
    assert "2024-03-15" in params
