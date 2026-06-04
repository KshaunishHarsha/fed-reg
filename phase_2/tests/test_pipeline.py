"""
Unit tests for pipeline.py — correction loop logic and orchestration.
All DB, LLM, and HTTP calls are mocked.
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import DocumentRecord, DocumentSummary, DISCLAIMER

_XML_BLOB = "<regulatory_document_summary><plain_language_summary>Test.</plain_language_summary></regulatory_document_summary>"


def _doc(**overrides) -> DocumentRecord:
    defaults = {
        "document_number": "2025-00001",
        "title": "AWA Enforcement Rule",
        "html_url": "https://www.federalregister.gov/d/2025-00001",
        "publication_date": date(2025, 3, 15),
        "confidence": "HIGH",
        "pipeline_state": "INGESTED",
        "abstract": "This rule amends AWA enforcement.",
        "agency_names": ["APHIS"],
        "type": "RULE",
        "regulation_category": "Final Rule",
        "page_length": 8,
    }
    defaults.update(overrides)
    return DocumentRecord(**defaults)


def _valid_summary() -> DocumentSummary:
    return DocumentSummary(
        plain_language_summary="This rule updates animal welfare standards.",
        advocacy_relevance="Affects ALDF litigation on factory farming oversight.",
        suggested_actions=["Submit comment.", "Brief legal team."],
        suggested_talking_points=["Animals need protection.", "Precedent-setting."],
        regulation_category="welfare",
    )


# ---------------------------------------------------------------------------
# process_document — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_document_success_returns_xml_blob():
    from pipeline import process_document

    doc = _doc()

    with (
        patch("pipeline.route_and_prepare", return_value=(1, "Prepared text")),
        patch("pipeline.summarize", return_value=_valid_summary()),
        patch("pipeline.build_xml", return_value=_XML_BLOB),
        patch("pipeline.save_summary", new_callable=AsyncMock),
        patch("pipeline.update_pipeline_state", new_callable=AsyncMock) as mock_state,
    ):
        result = await process_document(doc)

    assert result == _XML_BLOB
    mock_state.assert_called_once_with(doc.document_number, "SUMMARY_GENERATED")


@pytest.mark.asyncio
async def test_process_document_calls_phase3_callback_when_provided():
    from pipeline import process_document

    doc = _doc()
    callback = AsyncMock()

    with (
        patch("pipeline.route_and_prepare", return_value=(1, "Text")),
        patch("pipeline.summarize", return_value=_valid_summary()),
        patch("pipeline.build_xml", return_value=_XML_BLOB),
        patch("pipeline.save_summary", new_callable=AsyncMock),
        patch("pipeline.update_pipeline_state", new_callable=AsyncMock),
    ):
        await process_document(doc, phase3_ingest_fn=callback)

    callback.assert_called_once_with(doc, _XML_BLOB)


@pytest.mark.asyncio
async def test_process_document_skips_callback_when_none():
    from pipeline import process_document

    doc = _doc()

    with (
        patch("pipeline.route_and_prepare", return_value=(1, "Text")),
        patch("pipeline.summarize", return_value=_valid_summary()),
        patch("pipeline.build_xml", return_value=_XML_BLOB),
        patch("pipeline.save_summary", new_callable=AsyncMock),
        patch("pipeline.update_pipeline_state", new_callable=AsyncMock),
    ):
        result = await process_document(doc, phase3_ingest_fn=None)

    assert result is not None  # still succeeds


@pytest.mark.asyncio
async def test_process_document_returns_none_on_exception():
    from pipeline import process_document

    doc = _doc()

    with (
        patch("pipeline.route_and_prepare", side_effect=RuntimeError("LLM error")),
        patch("pipeline.update_pipeline_state", new_callable=AsyncMock) as mock_state,
    ):
        result = await process_document(doc)

    assert result is None
    mock_state.assert_called_once_with(doc.document_number, "SUMMARIZATION_FAILED")


# ---------------------------------------------------------------------------
# handle_correction — retry logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_correction_attempt_1_reruns_and_returns_blob():
    from pipeline import handle_correction

    doc = _doc()

    with (
        patch("pipeline.increment_correction_attempts", new_callable=AsyncMock, return_value=1),
        patch("pipeline.fetch_document_by_number", new_callable=AsyncMock, return_value=doc),
        patch("pipeline.process_document", new_callable=AsyncMock, return_value=_XML_BLOB),
    ):
        result = await handle_correction("2025-00001", "Summary too long.")

    assert result == _XML_BLOB


@pytest.mark.asyncio
async def test_correction_attempt_2_still_reruns():
    from pipeline import handle_correction

    doc = _doc()

    with (
        patch("pipeline.increment_correction_attempts", new_callable=AsyncMock, return_value=2),
        patch("pipeline.fetch_document_by_number", new_callable=AsyncMock, return_value=doc),
        patch("pipeline.process_document", new_callable=AsyncMock, return_value=_XML_BLOB),
    ):
        result = await handle_correction("2025-00001", "Missing advocacy_relevance.")

    assert result is not None


@pytest.mark.asyncio
async def test_correction_attempt_3_returns_none_and_marks_failed():
    from pipeline import handle_correction

    with (
        patch("pipeline.increment_correction_attempts", new_callable=AsyncMock, return_value=3),
        patch("pipeline.save_summary", new_callable=AsyncMock) as mock_save,
        patch("pipeline.process_document", new_callable=AsyncMock) as mock_process,
    ):
        result = await handle_correction("2025-00001", "Still invalid.")

    assert result is None
    mock_process.assert_not_called()
    mock_save.assert_called_once_with("2025-00001", "", 0, "failed")


@pytest.mark.asyncio
async def test_correction_returns_none_for_unknown_document():
    from pipeline import handle_correction

    with (
        patch("pipeline.increment_correction_attempts", new_callable=AsyncMock, return_value=1),
        patch("pipeline.fetch_document_by_number", new_callable=AsyncMock, return_value=None),
        patch("pipeline.process_document", new_callable=AsyncMock) as mock_process,
    ):
        result = await handle_correction("UNKNOWN-999", "Error detail.")

    assert result is None
    mock_process.assert_not_called()


@pytest.mark.asyncio
async def test_correction_passes_callback_through_to_process_document():
    from pipeline import handle_correction

    doc = _doc()
    callback = AsyncMock()

    with (
        patch("pipeline.increment_correction_attempts", new_callable=AsyncMock, return_value=1),
        patch("pipeline.fetch_document_by_number", new_callable=AsyncMock, return_value=doc),
        patch("pipeline.process_document", new_callable=AsyncMock, return_value=_XML_BLOB) as mock_proc,
    ):
        await handle_correction("2025-00001", "Error.", phase3_ingest_fn=callback)

    _, kwargs = mock_proc.call_args
    assert kwargs.get("phase3_ingest_fn") is callback


# ---------------------------------------------------------------------------
# run_pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_pipeline_processes_all_docs():
    from pipeline import run_pipeline

    docs = [_doc(document_number=f"2025-0000{i}") for i in range(3)]

    with (
        patch("pipeline.fetch_pending_documents", new_callable=AsyncMock, return_value=docs),
        patch("pipeline.process_document", new_callable=AsyncMock, return_value=_XML_BLOB),
    ):
        result = await run_pipeline()

    assert result["processed"] == 3
    assert result["failed"] == 0
    assert result["total"] == 3


@pytest.mark.asyncio
async def test_run_pipeline_counts_failures():
    from pipeline import run_pipeline

    docs = [_doc(document_number=f"2025-0000{i}") for i in range(4)]
    return_values = [_XML_BLOB, _XML_BLOB, None, None]

    with (
        patch("pipeline.fetch_pending_documents", new_callable=AsyncMock, return_value=docs),
        patch("pipeline.process_document", new_callable=AsyncMock, side_effect=return_values),
    ):
        result = await run_pipeline()

    assert result["processed"] == 2
    assert result["failed"] == 2


@pytest.mark.asyncio
async def test_run_pipeline_returns_zero_when_no_docs():
    from pipeline import run_pipeline

    with patch("pipeline.fetch_pending_documents", new_callable=AsyncMock, return_value=[]):
        result = await run_pipeline()

    assert result["total"] == 0
    assert result["processed"] == 0


@pytest.mark.asyncio
async def test_run_pipeline_passes_callback_to_each_process_document():
    from pipeline import run_pipeline

    docs = [_doc(document_number="2025-00001")]
    callback = AsyncMock()

    with (
        patch("pipeline.fetch_pending_documents", new_callable=AsyncMock, return_value=docs),
        patch("pipeline.process_document", new_callable=AsyncMock, return_value=_XML_BLOB) as mock_proc,
    ):
        await run_pipeline(phase3_ingest_fn=callback)

    _, kwargs = mock_proc.call_args
    assert kwargs.get("phase3_ingest_fn") is callback


@pytest.mark.asyncio
async def test_keyword_dropped_docs_never_reach_layer3():
    from pipeline import run_pipeline

    with (
        patch("pipeline.fetch_pending_documents", new_callable=AsyncMock, return_value=[]),
        patch("pipeline.process_document", new_callable=AsyncMock) as mock_process,
    ):
        result = await run_pipeline()

    mock_process.assert_not_called()
    assert result["total"] == 0