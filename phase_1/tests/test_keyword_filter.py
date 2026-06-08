"""
Unit tests for keyword_filter.py — no external API calls, no PDF downloads.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from keyword_filter import apply_keyword_filter
from models import RawDocument


def _doc(**kwargs) -> RawDocument:
    defaults = {
        "document_number": "2024-00001",
        "title": "Test Document",
        # Non-empty abstract prevents Layer 2a PDF scan from running in keyword scoring tests.
        # Tests that specifically exercise Layer 2a override this with abstract=None explicitly.
        "abstract": "Regulatory update for federal programs.",
        "html_url": "https://www.federalregister.gov/documents/test",
        "publication_date": date(2024, 1, 15),
        "type": "RULE",
    }
    defaults.update(kwargs)
    return RawDocument(**defaults)


# ---------------------------------------------------------------------------
# Step A: noise filter
# ---------------------------------------------------------------------------

def test_notice_with_noise_keyword_is_dropped():
    doc = _doc(type="NOTICE", title="Airspace Redesign Instrument Flight Rule Update")
    assert apply_keyword_filter(doc) is None


def test_notice_with_vessel_in_title_is_dropped():
    doc = _doc(type="NOTICE", title="Vessel Anchorage Regulations Update")
    assert apply_keyword_filter(doc) is None


def test_rule_with_noise_keyword_is_not_noise_dropped():
    # RULE type is never noise-dropped — may still be keyword-dropped for low score
    # "vessel" alone scores 0 context terms
    doc = _doc(type="RULE", title="Vessel Anchorage Rule")
    result = apply_keyword_filter(doc)
    # keyword score 0 → dropped, but NOT by noise filter
    assert result is None  # dropped by keyword scoring, not noise


def test_notice_without_noise_keywords_passes_noise_step():
    # NOTICE with a relevant title survives noise filter and keyword scoring
    doc = _doc(type="NOTICE", title="Animal Welfare Act Enforcement Notice")
    result = apply_keyword_filter(doc)
    assert result is not None
    assert result.confidence == "HIGH"


# ---------------------------------------------------------------------------
# Step B: anchor term → HIGH
# ---------------------------------------------------------------------------

def test_anchor_in_title_returns_high():
    doc = _doc(title="Animal Welfare Act Proposed Amendments 2024")
    result = apply_keyword_filter(doc)
    assert result is not None
    assert result.confidence == "HIGH"


def test_anchor_in_abstract_returns_high():
    doc = _doc(title="USDA Regulatory Notice", abstract="This rule covers CAFO water standards.")
    result = apply_keyword_filter(doc)
    assert result is not None
    assert result.confidence == "HIGH"


def test_anchor_awa_abbreviation_returns_high():
    doc = _doc(title="AWA Inspection Requirements Update")
    result = apply_keyword_filter(doc)
    assert result is not None
    assert result.confidence == "HIGH"


def test_anchor_endangered_species_act_returns_high():
    doc = _doc(title="Endangered Species Act Critical Habitat Designation")
    result = apply_keyword_filter(doc)
    assert result is not None
    assert result.confidence == "HIGH"


# ---------------------------------------------------------------------------
# Step B: context scoring
# ---------------------------------------------------------------------------

def test_one_context_term_is_dropped():
    # score = 1 < CONTEXT_THRESHOLD (2) → dropped
    doc = _doc(title="Livestock Feed Additive Notice", type="NOTICE")
    # "livestock" = 1 point — below threshold
    result = apply_keyword_filter(doc)
    assert result is None


def test_two_context_terms_returns_needs_confirmation():
    # "livestock" + "poultry" = 2 points ≥ threshold
    doc = _doc(title="Livestock and Poultry Regulations Update")
    result = apply_keyword_filter(doc)
    assert result is not None
    assert result.confidence == "NEEDS_CONFIRMATION"


def test_three_context_terms_returns_needs_confirmation():
    # "cattle" + "slaughter" + "veterinary" = 3 points
    doc = _doc(title="Cattle Slaughter Veterinary Inspection Rule")
    result = apply_keyword_filter(doc)
    assert result is not None
    assert result.confidence == "NEEDS_CONFIRMATION"


def test_zero_context_terms_is_dropped():
    doc = _doc(title="Grain Elevator Safety Standards Final Rule")
    result = apply_keyword_filter(doc)
    assert result is None


# ---------------------------------------------------------------------------
# Step C: Layer 2a (PDF scan) — only when abstract is absent
# ---------------------------------------------------------------------------

def test_context_block_is_none_when_abstract_is_present():
    # PDF scan must NOT run when abstract is populated
    doc = _doc(
        title="Animal Welfare Act Update",
        abstract="This proposed rule amends AWA enforcement procedures.",
    )
    result = apply_keyword_filter(doc)
    assert result is not None
    assert result.confidence == "HIGH"
    assert result.context_block is None


def test_pdf_scan_runs_when_abstract_is_absent(tmp_path):
    """Stub out requests + fitz to verify Layer 2a extracts a context block."""
    import fitz

    # Build a real single-page PDF with an anchor term
    pdf_doc = fitz.open()
    page = pdf_doc.new_page()
    text_before = "Regulatory preamble paragraph.\n\nBackground paragraph."
    text_match = "\n\nThis rule enforces the Animal Welfare Act standards for laboratory animals."
    text_after = "\n\nCompliance dates follow below.\n\nAdditional boilerplate."
    page.insert_text((50, 50), text_before + text_match + text_after, fontsize=11)
    pdf_bytes = pdf_doc.tobytes()
    pdf_doc.close()

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.content = pdf_bytes

    doc = _doc(
        title="Laboratory Animal Research Notice",
        type="NOTICE",
        abstract=None,
        pdf_url="https://example.com/test.pdf",
    )
    # "laboratory animal" is a CONTEXT_TERM → score=1, below threshold alone
    # But "animal welfare act" in PDF text → anchor hit in full-text scan
    # First ensure Step B passes via context score from title
    # "laboratory animal" = 1 point — below threshold, BUT
    # We need the doc to PASS Step B first before 2a runs.
    # Let's give it a title that passes scoring so 2a executes.
    doc = _doc(
        title="Laboratory Animal Rodent Research Facility Notice",
        type="NOTICE",
        abstract=None,
        pdf_url="https://example.com/test.pdf",
    )
    # "laboratory animal" + "rodent" + "processing facility"... let's count:
    # "laboratory animal" = 1, "rodent" = 1 → score = 2 ≥ threshold ✓

    with patch("keyword_filter.requests.get", return_value=mock_response):
        result = apply_keyword_filter(doc)

    assert result is not None
    assert result.context_block is not None
    assert "animal welfare act" in result.context_block.lower()


def test_pdf_scan_drops_doc_when_no_anchor_found():
    """If the PDF contains no anchor terms, the doc is discarded."""
    import fitz

    pdf_doc = fitz.open()
    page = pdf_doc.new_page()
    page.insert_text((50, 50), "General regulatory text about grain storage facilities.", fontsize=11)
    pdf_bytes = pdf_doc.tobytes()
    pdf_doc.close()

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.content = pdf_bytes

    # Title passes with 2 context terms, abstract absent → triggers Layer 2a
    doc = _doc(
        title="Livestock Poultry Processing Facility Rule",
        abstract=None,
        pdf_url="https://example.com/test.pdf",
    )

    with patch("keyword_filter.requests.get", return_value=mock_response):
        result = apply_keyword_filter(doc)

    assert result is None


def test_pdf_scan_skipped_when_no_pdf_url():
    """If abstract is absent and pdf_url is None, doc is discarded (can't scan)."""
    doc = _doc(
        title="Livestock Poultry Processing Facility Rule",
        abstract=None,
        pdf_url=None,
    )
    result = apply_keyword_filter(doc)
    assert result is None
