"""Tests for xml_builder.py — pure serialization, no external calls."""
import xml.etree.ElementTree as ET
from datetime import date

from models import DISCLAIMER, DocumentSummary
from xml_builder import build_xml


def _summary(**overrides) -> DocumentSummary:
    base = {
        "plain_language_summary": "This rule updates animal welfare standards.",
        "advocacy_relevance": "Affects ALDF litigation on factory farming.",
        "suggested_actions": ["Submit a comment.", "Alert legal team."],
        "suggested_talking_points": ["Animals need protection.", "Precedent-setting rule."],
        "regulation_category": "welfare",
    }
    base.update(overrides)
    return DocumentSummary(**base)


def _parse(xml_str: str) -> ET.Element:
    return ET.fromstring(xml_str)


# ---------------------------------------------------------------------------
# Root element
# ---------------------------------------------------------------------------

def test_root_element_name():
    root = _parse(build_xml(_summary()))
    assert root.tag == "regulatory_document_summary"


# ---------------------------------------------------------------------------
# Required text fields
# ---------------------------------------------------------------------------

def test_plain_language_summary_present():
    s = _summary()
    root = _parse(build_xml(s))
    assert root.findtext("plain_language_summary") == s.plain_language_summary


def test_advocacy_relevance_present():
    s = _summary()
    root = _parse(build_xml(s))
    assert root.findtext("advocacy_relevance") == s.advocacy_relevance


# ---------------------------------------------------------------------------
# suggested_actions
# ---------------------------------------------------------------------------

def test_actions_serialized_as_action_tags():
    s = _summary(suggested_actions=["Action one.", "Action two.", "Action three."])
    root = _parse(build_xml(s))
    actions = root.find("suggested_actions")
    assert actions is not None
    items = list(actions.findall("action"))
    assert len(items) == 3
    assert items[0].text == "Action one."
    assert items[2].text == "Action three."


def test_single_action():
    s = _summary(suggested_actions=["Only action."])
    root = _parse(build_xml(s))
    items = list(root.find("suggested_actions").findall("action"))
    assert len(items) == 1


# ---------------------------------------------------------------------------
# suggested_talking_points
# ---------------------------------------------------------------------------

def test_talking_points_serialized_as_point_tags():
    s = _summary(suggested_talking_points=["Point one.", "Point two."])
    root = _parse(build_xml(s))
    points_el = root.find("suggested_talking_points")
    assert points_el is not None
    items = list(points_el.findall("point"))
    assert len(items) == 2
    assert items[1].text == "Point two."


# ---------------------------------------------------------------------------
# deadlines
# ---------------------------------------------------------------------------

def test_deadlines_element_present():
    root = _parse(build_xml(_summary()))
    assert root.find("deadlines") is not None


def test_dates_serialized_as_isoformat():
    s = _summary(
        comment_close_date=date(2025, 7, 15),
        hearing_date=date(2025, 8, 1),
        effective_date=date(2025, 9, 1),
    )
    root = _parse(build_xml(s))
    d = root.find("deadlines")
    assert d.findtext("comment_close_date") == "2025-07-15"
    assert d.findtext("hearing_date") == "2025-08-01"
    assert d.findtext("effective_date") == "2025-09-01"


def test_none_dates_serialized_as_empty_string():
    s = _summary(comment_close_date=None, hearing_date=None, effective_date=None)
    root = _parse(build_xml(s))
    d = root.find("deadlines")
    assert d.findtext("comment_close_date") == ""
    assert d.findtext("hearing_date") == ""
    assert d.findtext("effective_date") == ""


# ---------------------------------------------------------------------------
# disclaimer
# ---------------------------------------------------------------------------

def test_disclaimer_in_xml_is_hardcoded():
    root = _parse(build_xml(_summary()))
    assert root.findtext("disclaimer") == DISCLAIMER


def test_xml_is_valid_and_parseable():
    xml_str = build_xml(_summary())
    # Should not raise
    ET.fromstring(xml_str)


def test_xml_element_order():
    """Elements must appear in the canonical order Phase 3 expects."""
    root = _parse(build_xml(_summary()))
    tags = [child.tag for child in root]
    assert tags == [
        "plain_language_summary",
        "advocacy_relevance",
        "suggested_actions",
        "suggested_talking_points",
        "deadlines",
        "disclaimer",
    ]