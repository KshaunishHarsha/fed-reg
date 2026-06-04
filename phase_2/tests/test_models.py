"""Tests for Pydantic schema validation in models.py."""
import pytest
from datetime import date
from pydantic import ValidationError

from models import DocumentSummary, DISCLAIMER


def _valid_summary(**overrides) -> dict:
    base = {
        "plain_language_summary": "This rule updates animal welfare standards for federally inspected facilities.",
        "advocacy_relevance": "Directly affects ALDF litigation strategy on factory farming oversight.",
        "suggested_actions": ["Submit public comment by deadline.", "Brief legal team."],
        "suggested_talking_points": ["Animals deserve federal protection.", "This rule sets a precedent."],
        "regulation_category": "welfare",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# plain_language_summary
# ---------------------------------------------------------------------------

def test_summary_within_100_words_passes():
    data = _valid_summary()
    s = DocumentSummary(**data)
    assert len(s.plain_language_summary.split()) <= 100


def test_summary_exceeding_100_words_raises():
    long = " ".join(["word"] * 101)
    with pytest.raises(ValidationError, match="100"):
        DocumentSummary(**_valid_summary(plain_language_summary=long))


def test_summary_exactly_100_words_passes():
    exact = " ".join(["word"] * 100)
    s = DocumentSummary(**_valid_summary(plain_language_summary=exact))
    assert s.plain_language_summary == exact


# ---------------------------------------------------------------------------
# advocacy_relevance
# ---------------------------------------------------------------------------

def test_empty_advocacy_relevance_raises():
    with pytest.raises(ValidationError, match="empty"):
        DocumentSummary(**_valid_summary(advocacy_relevance=""))


def test_whitespace_only_advocacy_relevance_raises():
    with pytest.raises(ValidationError, match="empty"):
        DocumentSummary(**_valid_summary(advocacy_relevance="   "))


# ---------------------------------------------------------------------------
# suggested_actions
# ---------------------------------------------------------------------------

def test_three_actions_passes():
    s = DocumentSummary(**_valid_summary(
        suggested_actions=["Action one.", "Action two.", "Action three."]
    ))
    assert len(s.suggested_actions) == 3


def test_four_actions_raises():
    with pytest.raises(ValidationError, match="maximum is 3"):
        DocumentSummary(**_valid_summary(
            suggested_actions=["A", "B", "C", "D"]
        ))


def test_action_exceeding_25_words_raises():
    long_action = " ".join(["word"] * 26)
    with pytest.raises(ValidationError, match="25"):
        DocumentSummary(**_valid_summary(suggested_actions=[long_action]))


def test_action_at_25_words_passes():
    exact = " ".join(["word"] * 25)
    s = DocumentSummary(**_valid_summary(suggested_actions=[exact]))
    assert len(s.suggested_actions[0].split()) == 25


# ---------------------------------------------------------------------------
# suggested_talking_points
# ---------------------------------------------------------------------------

def test_three_talking_points_passes():
    s = DocumentSummary(**_valid_summary(
        suggested_talking_points=["Point one.", "Point two.", "Point three."]
    ))
    assert len(s.suggested_talking_points) == 3


def test_four_talking_points_raises():
    with pytest.raises(ValidationError, match="maximum is 3"):
        DocumentSummary(**_valid_summary(
            suggested_talking_points=["A", "B", "C", "D"]
        ))


def test_talking_point_exceeding_25_words_raises():
    long_point = " ".join(["word"] * 26)
    with pytest.raises(ValidationError, match="25"):
        DocumentSummary(**_valid_summary(suggested_talking_points=[long_point]))


# ---------------------------------------------------------------------------
# disclaimer — always hardcoded
# ---------------------------------------------------------------------------

def test_disclaimer_default_is_hardcoded():
    s = DocumentSummary(**_valid_summary())
    assert s.disclaimer == DISCLAIMER


def test_disclaimer_overwritten_even_if_llm_provides_wrong_value():
    s = DocumentSummary(**_valid_summary(disclaimer="Wrong disclaimer from LLM."))
    assert s.disclaimer == DISCLAIMER


def test_disclaimer_constant_value():
    assert DISCLAIMER == (
        "This summary is informational only and does not constitute legal advice."
    )


# ---------------------------------------------------------------------------
# regulation_category
# ---------------------------------------------------------------------------

def test_valid_regulation_categories():
    for cat in ["welfare", "wildlife", "agriculture", "research_animals", "marine", "trade"]:
        s = DocumentSummary(**_valid_summary(regulation_category=cat))
        assert s.regulation_category == cat


def test_invalid_regulation_category_raises():
    with pytest.raises(ValidationError):
        DocumentSummary(**_valid_summary(regulation_category="unknown"))


# ---------------------------------------------------------------------------
# date fields
# ---------------------------------------------------------------------------

def test_date_fields_accept_none():
    s = DocumentSummary(**_valid_summary(
        comment_close_date=None,
        hearing_date=None,
        effective_date=None,
    ))
    assert s.comment_close_date is None


def test_date_fields_accept_date_objects():
    s = DocumentSummary(**_valid_summary(
        comment_close_date=date(2025, 7, 15),
    ))
    assert s.comment_close_date == date(2025, 7, 15)