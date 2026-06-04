"""
Unit tests for ingestion.py — requests.get is mocked; no real HTTP calls.
"""
from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from ingestion import fetch_documents


TARGET_DATE = date(2024, 3, 15)

_PUBLISHED_ITEM = {
    "document_number": "2024-05000",
    "title": "Animal Welfare Act Enforcement Rule",
    "html_url": "https://www.federalregister.gov/documents/2024-05000",
    "publication_date": "2024-03-15",
    "type": "RULE",
    "document_type": "Rule",
    "agency_names": ["Animal and Plant Health Inspection Service"],
    "agencies": [{"slug": "animal-and-plant-health-inspection-service"}],
    "abstract": "Amends AWA enforcement procedures.",
    "pdf_url": "https://www.govinfo.gov/content/pkg/test.pdf",
    "page_length": 12,
}

_INSPECTION_ITEM = {
    "document_number": "2024-05001",
    "title": "FSIS Humane Slaughter Notice",
    "html_url": "https://www.federalregister.gov/documents/2024-05001",
    "type": "NOTICE",
    "agencies": [
        {"slug": "food-safety-and-inspection-service", "raw_name": "Food Safety and Inspection Service"}
    ],
}


def _mock_get(published_items=None, inspection_items=None, next_page_url=None):
    """Build a mock requests.get that returns controlled API responses."""
    published_resp = MagicMock()
    published_resp.raise_for_status.return_value = None
    published_resp.json.return_value = {
        "results": published_items or [],
        "next_page_url": next_page_url,
    }

    inspection_resp = MagicMock()
    inspection_resp.raise_for_status.return_value = None
    inspection_resp.json.return_value = {"documents": inspection_items or []}

    def side_effect(url, **kwargs):
        if "public-inspection" in url:
            return inspection_resp
        return published_resp

    return side_effect


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def test_deduplication_same_doc_in_both_feeds():
    """A document appearing in both feeds must only appear once in output."""
    shared = dict(_PUBLISHED_ITEM)
    inspection_version = {
        "document_number": shared["document_number"],
        "title": shared["title"],
        "html_url": shared["html_url"],
        "type": shared["type"],
        "agencies": [{"slug": "animal-and-plant-health-inspection-service", "raw_name": "APHIS"}],
    }

    with patch("ingestion.requests.get", side_effect=_mock_get(
        published_items=[shared],
        inspection_items=[inspection_version],
    )):
        docs = fetch_documents(TARGET_DATE)

    doc_numbers = [d.document_number for d in docs]
    assert doc_numbers.count(shared["document_number"]) == 1


def test_published_doc_takes_priority_over_inspection_duplicate():
    """When deduplicating, published doc is listed first and wins."""
    shared_number = "2024-05000"
    published = dict(_PUBLISHED_ITEM, document_number=shared_number)
    inspection = dict(_INSPECTION_ITEM, document_number=shared_number)

    with patch("ingestion.requests.get", side_effect=_mock_get(
        published_items=[published],
        inspection_items=[inspection],
    )):
        docs = fetch_documents(TARGET_DATE)

    assert len(docs) == 1
    # Published version has an abstract; inspection version does not
    assert docs[0].abstract is not None


# ---------------------------------------------------------------------------
# Client-side filtering of public inspection feed
# ---------------------------------------------------------------------------

def test_inspection_doc_with_wrong_agency_slug_is_filtered():
    wrong_agency = dict(_INSPECTION_ITEM, agencies=[
        {"slug": "department-of-defense", "raw_name": "DoD"}
    ])

    with patch("ingestion.requests.get", side_effect=_mock_get(inspection_items=[wrong_agency])):
        docs = fetch_documents(TARGET_DATE)

    assert all(d.document_number != wrong_agency["document_number"] for d in docs)


def test_inspection_doc_with_wrong_type_is_filtered():
    wrong_type = dict(_INSPECTION_ITEM, type="PRESDOCU")

    with patch("ingestion.requests.get", side_effect=_mock_get(inspection_items=[wrong_type])):
        docs = fetch_documents(TARGET_DATE)

    assert all(d.document_number != wrong_type["document_number"] for d in docs)


def test_inspection_doc_with_correct_agency_and_type_is_included():
    with patch("ingestion.requests.get", side_effect=_mock_get(inspection_items=[_INSPECTION_ITEM])):
        docs = fetch_documents(TARGET_DATE)

    assert any(d.document_number == _INSPECTION_ITEM["document_number"] for d in docs)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def test_pagination_follows_next_page_url():
    """fetch_documents must follow next_page_url until exhausted."""
    page1_item = dict(_PUBLISHED_ITEM, document_number="2024-05100")
    page2_item = dict(_PUBLISHED_ITEM, document_number="2024-05101")

    call_count = 0

    def paginated_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        if "public-inspection" in url:
            resp.json.return_value = {"documents": []}
        elif call_count == 1:
            # first call: page 1 of published feed
            resp.json.return_value = {
                "results": [page1_item],
                "next_page_url": "https://www.federalregister.gov/api/v1/documents.json?page=2",
            }
        else:
            # second call: page 2, no more pages
            resp.json.return_value = {
                "results": [page2_item],
                "next_page_url": None,
            }
        return resp

    with patch("ingestion.requests.get", side_effect=paginated_get):
        docs = fetch_documents(TARGET_DATE)

    numbers = {d.document_number for d in docs}
    assert "2024-05100" in numbers
    assert "2024-05101" in numbers


# ---------------------------------------------------------------------------
# Field parsing
# ---------------------------------------------------------------------------

def test_publication_date_defaults_to_target_date_for_inspection_docs():
    """Public inspection docs have no publication_date; must default to run date."""
    with patch("ingestion.requests.get", side_effect=_mock_get(inspection_items=[_INSPECTION_ITEM])):
        docs = fetch_documents(TARGET_DATE)

    inspection_doc = next(d for d in docs if d.document_number == _INSPECTION_ITEM["document_number"])
    assert inspection_doc.publication_date == TARGET_DATE


def test_doc_missing_required_fields_is_skipped():
    """Items without document_number or html_url are silently skipped."""
    bad = {"title": "No ID or URL"}
    with patch("ingestion.requests.get", side_effect=_mock_get(published_items=[bad])):
        docs = fetch_documents(TARGET_DATE)

    assert all(d.document_number != bad.get("document_number") for d in docs)
