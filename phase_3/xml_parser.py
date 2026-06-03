"""
phase_3/xml_parser.py
---------------------
Parses Phase 2's raw xml_summary_blob into a dict that feeds ValidatedSummary.

Phase 2 stores the LLM's raw XML output verbatim into summaries.xml_summary_blob.
Phase 3 owns the responsibility of parsing that blob — Phase 2 never touches
parsed fields. This keeps the two phases cleanly decoupled.

XML contract (from llm_output_contract.md):

  <regulatory_document_summary>
      <plain_language_summary>...</plain_language_summary>
      <advocacy_relevance>...</advocacy_relevance>
      <suggested_actions>
          <action>...</action>
      </suggested_actions>
      <suggested_talking_points>
          <point>...</point>
      </suggested_talking_points>
      <disclaimer>...</disclaimer>
  </regulatory_document_summary>
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict


class XmlParseError(Exception):
    """Raised when the blob cannot be parsed as valid XML or is missing root."""


def parse_xml_blob(xml_blob: str) -> Dict[str, Any]:
    """
    Parse a Phase 2 xml_summary_blob string into a plain dict suitable for
    constructing a ValidatedSummary.

    Returns:
        {
          "plain_language_summary": str,
          "advocacy_relevance": str,
          "suggested_actions": [str, ...],
          "suggested_talking_points": [str, ...],
          "disclaimer": str,
        }

    Raises:
        XmlParseError: if the XML is malformed, the root tag is wrong,
                       or a required tag is missing from the blob.
    """
    try:
        root = ET.fromstring(xml_blob.strip())
    except ET.ParseError as exc:
        raise XmlParseError(f"Malformed XML blob: {exc}") from exc

    if root.tag != "regulatory_document_summary":
        raise XmlParseError(
            f"Unexpected root tag <{root.tag}>; "
            "expected <regulatory_document_summary>."
        )

    def _text(tag: str) -> str:
        el = root.find(tag)
        if el is None:
            raise XmlParseError(f"Required tag <{tag}> is missing from XML blob.")
        return (el.text or "").strip()

    def _list(parent_tag: str, child_tag: str) -> list[str]:
        parent = root.find(parent_tag)
        if parent is None:
            raise XmlParseError(
                f"Required tag <{parent_tag}> is missing from XML blob."
            )
        return [(el.text or "").strip() for el in parent.findall(child_tag)]

    return {
        "plain_language_summary": _text("plain_language_summary"),
        "advocacy_relevance": _text("advocacy_relevance"),
        "suggested_actions": _list("suggested_actions", "action"),
        "suggested_talking_points": _list("suggested_talking_points", "point"),
        "disclaimer": _text("disclaimer"),
    }
