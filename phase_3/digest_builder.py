"""
phase_3/digest_builder.py
-------------------------
Step 3.3 — Digest compilation and dual-layer email package assembly.

Responsibilities
----------------
1. Sort DigestRow objects into three urgency sections based on the `type` and
   `confidence` columns from the `documents` table (schema.sql alignment).

2. Parse each row's xml_summary_blob via xml_parser.py to extract the
   LLM-generated fields (plain_language_summary, advocacy_relevance,
   suggested_actions, suggested_talking_points, disclaimer).

3. Build static outbound links from verified DB values only — zero LLM:
     Federal Register source:  https://www.federalregister.gov/d/{document_number}
     Regulations.gov comments: https://www.regulations.gov/commentOn?D={comment_url}
   Note: comment_url in the DB stores the docket ID or full comment URL from
   the Federal Register API. If it already starts with "http", it is used as-is.
   Otherwise it is treated as a docket ID and interpolated into the template URL.

4. Render both HTML and plain-text email bodies using Jinja2 templates.

5. Return a DigestPackage containing both bodies + metadata, ready for
   platform_handoff.py to send via the Open Paws email system.

Section mapping (from schema.sql `type` values + `confidence`):
  Section A — PRORULE documents with comments_close_on >= today
  Section B — RULE + NOTICE documents (regardless of confidence)
  Section C — NEEDS_CONFIRMATION documents (any type) + PRORULE past deadline
              + 'Other' regulation_category documents
  Zero-result — circuit breaker when no documents exist for the day
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from phase_3.digest_query import DigestRow
from phase_3.xml_parser import XmlParseError, parse_xml_blob

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Jinja2 environment
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DigestEntry:
    """
    One fully-assembled email entry, ready for template rendering.
    All link fields are built from DB values — never from LLM output.
    """
    document_number: str
    title: str
    agency_names: List[str]
    regulation_category: Optional[str]
    comments_close_on: Optional[date]
    effective_on: Optional[date]
    source_url: str                          # federalregister.gov/d/{doc_num}
    comment_portal_url: Optional[str]        # regulations.gov link (if available)
    # LLM-generated fields (parsed from xml_summary_blob)
    plain_language_summary: str
    advocacy_relevance: str
    suggested_actions: List[str]
    suggested_talking_points: List[str]
    disclaimer: str                          # hardcoded exact string
    # Section assignment
    section: str                             # "A" | "B" | "C"
    is_needs_confirmation: bool = False      # drives Section C badge


class DigestPackage(BaseModel):
    """
    The complete compiled digest for one day, containing both email layers.
    Returned by build_digest() and consumed by platform_handoff.py.
    Pydantic model for FastAPI response serialization.
    """
    digest_date: date
    html_body: str
    text_body: str
    is_zero_result: bool
    section_a_count: int = 0
    section_b_count: int = 0
    section_c_count: int = 0
    total_documents: int = 0
    built_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Static link builder
# ---------------------------------------------------------------------------

def _build_source_url(document_number: str) -> str:
    """Always constructed from the federal document number — never from LLM."""
    return f"https://www.federalregister.gov/d/{document_number}"


def _build_comment_url(comment_url: Optional[str]) -> Optional[str]:
    """
    Build the regulations.gov comment portal link.
    If the DB value already looks like a full URL, use it directly.
    If it looks like a docket ID (e.g. APHIS-2026-0041), interpolate it.
    Returns None if comment_url is missing or empty.
    """
    if not comment_url or not comment_url.strip():
        return None
    cu = comment_url.strip()
    if cu.startswith("http://") or cu.startswith("https://"):
        return cu
    # Treat as docket ID
    return f"https://www.regulations.gov/commentOn?D={cu}"


# ---------------------------------------------------------------------------
# Section classifier
# ---------------------------------------------------------------------------

def _classify_section(row: DigestRow, today: date) -> str:
    """
    Assign one of three digest sections based on DB fields only.

    Section A — Proposed rules WITH an active (future/today) comment window.
                Highest priority: attorney action required before deadline.
    Section B — Final Rules and Notices, regardless of confidence.
                Important for litigation tracking but no immediate action window.
    Section C — Everything else:
                  • NEEDS_CONFIRMATION documents (borderline relevance)
                  • Proposed rules whose comment window has already closed
                  • 'Other' regulation_category
                  • Presidential Documents (type not PRORULE/RULE/NOTICE)
    """
    doc_type = (row.type or "").upper()
    is_confirmed = (row.confidence or "HIGH") == "HIGH"
    has_open_comment = (
        row.comments_close_on is not None
        and row.comments_close_on >= today
    )

    # Borderline confidence → always Section C regardless of type
    if not is_confirmed:
        return "C"

    if doc_type == "PRORULE":
        return "A" if has_open_comment else "C"

    if doc_type in ("RULE", "NOTICE"):
        return "B"

    # PRESDOC and anything unrecognised → Section C
    return "C"


# ---------------------------------------------------------------------------
# XML parser wrapper — soft-failure on individual entries
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "This summary is informational only and does not constitute legal advice."
)
_PARSE_FAIL_SUMMARY = (
    "[Summary unavailable — XML parsing failed for this entry. "
    "Review the raw blob in the summaries table.]"
)


def _parse_llm_fields(row: DigestRow) -> Dict[str, Any]:
    """
    Parse xml_summary_blob into LLM field dict.
    On parse failure, returns placeholder strings so the entry still renders
    in the digest rather than crashing the entire build.
    """
    try:
        return parse_xml_blob(row.xml_summary_blob)
    except XmlParseError as exc:
        logger.warning(
            "[%s] XML parse failed during digest build: %s. "
            "Entry will render with placeholder text.",
            row.document_number,
            exc,
        )
        return {
            "plain_language_summary": _PARSE_FAIL_SUMMARY,
            "advocacy_relevance": "",
            "suggested_actions": [],
            "suggested_talking_points": [],
            "disclaimer": _DISCLAIMER,
        }


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_digest(rows: List[DigestRow], digest_date: date) -> DigestPackage:
    """
    Compile the full dual-layer digest package for a given day.

    Args:
        rows:         List of DigestRow objects from digest_query.fetch_digest_rows().
                      May be empty (zero-result day).
        digest_date:  The calendar date this digest represents.

    Returns:
        DigestPackage with both html_body and text_body populated.
        is_zero_result=True if rows was empty (circuit-breaker path).
    """
    today = digest_date

    # -- Circuit breaker --------------------------------------------------------
    if not rows:
        logger.info(
            "[DigestBuilder] Zero documents for %s — rendering circuit-breaker digest.",
            digest_date.isoformat(),
        )
        html_body = _jinja_env.get_template("zero_result.html").render(
            digest_date=digest_date,
        )
        text_body = _jinja_env.get_template("zero_result.txt").render(
            digest_date=digest_date,
        )
        return DigestPackage(
            digest_date=digest_date,
            html_body=html_body,
            text_body=text_body,
            is_zero_result=True,
        )

    # -- Assemble entries -------------------------------------------------------
    section_a: List[DigestEntry] = []
    section_b: List[DigestEntry] = []
    section_c: List[DigestEntry] = []

    for row in rows:
        section = _classify_section(row, today)
        llm = _parse_llm_fields(row)

        entry = DigestEntry(
            document_number=row.document_number,
            title=row.title,
            agency_names=row.agency_names,
            regulation_category=row.regulation_category,
            comments_close_on=row.comments_close_on,
            effective_on=row.effective_on,
            source_url=_build_source_url(row.document_number),
            comment_portal_url=_build_comment_url(row.comment_url),
            plain_language_summary=llm["plain_language_summary"],
            advocacy_relevance=llm["advocacy_relevance"],
            suggested_actions=llm["suggested_actions"],
            suggested_talking_points=llm["suggested_talking_points"],
            disclaimer=llm.get("disclaimer", _DISCLAIMER),
            section=section,
            is_needs_confirmation=(row.confidence == "NEEDS_CONFIRMATION"),
        )

        if section == "A":
            section_a.append(entry)
        elif section == "B":
            section_b.append(entry)
        else:
            section_c.append(entry)

    # Section A: soonest deadline first (already sorted by query, keep order)
    # Section B: no further sort needed
    # Section C: unconfirmed items last within section
    section_c.sort(key=lambda e: (e.is_needs_confirmation, e.document_number))

    logger.info(
        "[DigestBuilder] %s — Section A: %d, Section B: %d, Section C: %d",
        digest_date.isoformat(),
        len(section_a),
        len(section_b),
        len(section_c),
    )

    # -- Render templates -------------------------------------------------------
    template_ctx = {
        "digest_date": digest_date,
        "section_a": section_a,
        "section_b": section_b,
        "section_c": section_c,
        "has_a": bool(section_a),
        "has_b": bool(section_b),
        "has_c": bool(section_c),
        "total": len(rows),
        "disclaimer": _DISCLAIMER,
        "built_at": datetime.now(timezone.utc),
    }

    html_body = _jinja_env.get_template("digest_email.html").render(**template_ctx)
    text_body = _jinja_env.get_template("digest_email.txt").render(**template_ctx)

    return DigestPackage(
        digest_date=digest_date,
        html_body=html_body,
        text_body=text_body,
        is_zero_result=False,
        section_a_count=len(section_a),
        section_b_count=len(section_b),
        section_c_count=len(section_c),
        total_documents=len(rows),
    )
