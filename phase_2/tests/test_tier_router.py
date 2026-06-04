"""Tests for tier_router.py — all HTTP calls mocked."""
from datetime import date
from unittest.mock import patch

import pytest

from models import DocumentRecord
from tier_router import route_and_prepare


def _doc(**overrides) -> DocumentRecord:
    defaults = {
        "document_number": "2025-00001",
        "title": "Animal Welfare Act Enforcement Rule",
        "html_url": "https://www.federalregister.gov/documents/2025-00001",
        "publication_date": date(2025, 3, 15),
        "confidence": "HIGH",
        "pipeline_state": "INGESTED",
        "abstract": "This rule amends AWA enforcement procedures.",
        "agency_names": ["APHIS"],
    }
    defaults.update(overrides)
    return DocumentRecord(**defaults)


# ---------------------------------------------------------------------------
# Tier 1: page_length < 15
# ---------------------------------------------------------------------------

def test_tier1_for_short_document():
    doc = _doc(page_length=5)
    tier, text = route_and_prepare(doc)
    assert tier == 1


def test_tier1_uses_abstract():
    doc = _doc(page_length=10, abstract="Short abstract text.")
    tier, text = route_and_prepare(doc)
    assert tier == 1
    assert text == "Short abstract text."


def test_tier1_page_length_14_is_still_tier1():
    doc = _doc(page_length=14)
    tier, _ = route_and_prepare(doc)
    assert tier == 1


def test_tier1_falls_back_to_title_when_no_abstract():
    doc = _doc(page_length=5, abstract=None, context_block=None)
    tier, text = route_and_prepare(doc)
    assert tier == 1
    assert text == doc.title


def test_tier1_when_page_length_is_none():
    doc = _doc(page_length=None, abstract="Abstract content.")
    tier, text = route_and_prepare(doc)
    assert tier == 1
    assert text == "Abstract content."


# ---------------------------------------------------------------------------
# Tier 2: 15 <= page_length <= 50
# ---------------------------------------------------------------------------

def test_tier2_for_medium_document():
    doc = _doc(page_length=30)
    with patch("tier_router.boilerplate_pruner.prune", return_value="Pruned content."):
        tier, text = route_and_prepare(doc)
    assert tier == 2
    assert text == "Pruned content."


def test_tier2_page_length_15_boundary():
    doc = _doc(page_length=15)
    with patch("tier_router.boilerplate_pruner.prune", return_value="Pruned."):
        tier, _ = route_and_prepare(doc)
    assert tier == 2


def test_tier2_page_length_50_boundary():
    doc = _doc(page_length=50)
    with patch("tier_router.boilerplate_pruner.prune", return_value="Pruned."):
        tier, _ = route_and_prepare(doc)
    assert tier == 2


def test_tier2_falls_back_to_abstract_when_pruner_returns_empty():
    doc = _doc(page_length=30, abstract="Fallback abstract.")
    with patch("tier_router.boilerplate_pruner.prune", return_value=""):
        tier, text = route_and_prepare(doc)
    assert tier == 2
    assert text == "Fallback abstract."


def test_tier2_falls_back_to_title_when_pruner_empty_and_no_abstract():
    doc = _doc(page_length=30, abstract=None)
    with patch("tier_router.boilerplate_pruner.prune", return_value=""):
        tier, text = route_and_prepare(doc)
    assert tier == 2
    assert text == doc.title


# ---------------------------------------------------------------------------
# Tier 3: page_length > 50
# ---------------------------------------------------------------------------

def test_tier3_for_long_document():
    doc = _doc(page_length=80, context_block="Extracted context block text.")
    tier, text = route_and_prepare(doc)
    assert tier == 3
    assert text == "Extracted context block text."


def test_tier3_page_length_51_boundary():
    doc = _doc(page_length=51, context_block="Context.")
    tier, _ = route_and_prepare(doc)
    assert tier == 3


def test_tier3_does_not_call_boilerplate_pruner():
    doc = _doc(page_length=100, context_block="Context block.")
    with patch("tier_router.boilerplate_pruner.prune") as mock_prune:
        route_and_prepare(doc)
    mock_prune.assert_not_called()


def test_tier3_falls_back_to_abstract_when_context_block_missing():
    doc = _doc(page_length=80, context_block=None, abstract="Abstract fallback.")
    tier, text = route_and_prepare(doc)
    assert tier == 3
    assert text == "Abstract fallback."


def test_tier3_falls_back_to_title_when_both_missing():
    doc = _doc(page_length=80, context_block=None, abstract=None)
    tier, text = route_and_prepare(doc)
    assert tier == 3
    assert text == doc.title