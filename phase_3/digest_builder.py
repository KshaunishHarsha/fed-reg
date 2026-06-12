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

Section mapping (action axis — from schema.sql `type` + comment window):
  Section A — PRORULE documents with comments_close_on >= today (actionable)
  Section B — everything else relevant: RULE, NOTICE, expired PRORULE, other types
  Zero-result — circuit breaker when no documents exist for the day

Relevancy (separate axis — from `documents.confidence`):
  HIGH / MEDIUM / LOW badge rendered on every card; sorts entries within a section.
  HIGH = strong keyword anchor, MEDIUM / LOW = AI-graded context-only documents.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field, PrivateAttr

from phase_3.digest_query import DigestRow
from phase_3.xml_parser import XmlParseError, parse_xml_blob

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Jinja2 environment
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).parent / "templates"

def _datefmt(d: date) -> str:
    """Format date as 'Month D, YYYY' without a leading zero on the day (cross-platform)."""
    return d.strftime("%B ") + str(d.day) + d.strftime(", %Y")


_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_jinja_env.filters["datefmt"] = _datefmt


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
    publication_date: date
    source_url: str                          # federalregister.gov/d/{doc_num}
    comment_portal_url: Optional[str]        # regulations.gov link (if available)
    # LLM-generated fields (parsed from xml_summary_blob)
    plain_language_summary: str
    advocacy_relevance: str
    suggested_actions: List[str]
    suggested_talking_points: List[str]
    disclaimer: str                          # hardcoded exact string
    # Computed / derived
    is_public_inspection: bool               # True when abstract is None (pre-publication draft)
    comments_days_left: Optional[int]        # None if no deadline; negative if expired
    summarization_tier: Optional[int]        # 1=abstract only, 2=body, 3=full doc
    # Section assignment
    section: str                             # "A" | "B"
    relevancy: str = "MEDIUM"                # HIGH | MEDIUM | LOW — drives the card badge


class DigestPackage(BaseModel):
    """
    The complete compiled digest for one day, containing both email layers.
    Returned by build_digest() and consumed by platform_handoff.py.
    Pydantic model for FastAPI response serialization.
    """
    model_config = {"arbitrary_types_allowed": True}

    digest_date: date
    html_body: str
    text_body: str
    is_zero_result: bool
    section_a_count: int = 0
    section_b_count: int = 0
    section_c_count: int = 0
    total_documents: int = 0
    built_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Internal lists — used by orchestrator for per-subscriber filtering.
    # Declared as PrivateAttr so Pydantic excludes them from JSON serialization.
    _section_a: List[Any] = PrivateAttr(default_factory=list)
    _section_b: List[Any] = PrivateAttr(default_factory=list)
    _section_c: List[Any] = PrivateAttr(default_factory=list)


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
# Category helpers
# ---------------------------------------------------------------------------

# Human-readable labels for regulation_category codes from Phase 2
CATEGORY_LABELS: Dict[str, str] = {
    "welfare":                "Companion & Gen. Welfare",
    "wildlife":               "Wild Animals & Habitat",
    "agriculture":            "Livestock Regulations",
    "agricultural_subsidies": "Farm Subsidies & Loans",
    "research_animals":       "Lab & Research Animals",
    "marine":                 "Marine & Ocean Life",
    "trade":                  "Animal Trade & Export",
}

# Preferred display order for categories within a section
_CATEGORY_ORDER = [
    "welfare",
    "wildlife",
    "agriculture",
    "agricultural_subsidies",
    "research_animals",
    "marine",
    "trade",
]


def _group_by_category(entries: List[DigestEntry]) -> List[Dict[str, Any]]:
    """
    Group a flat list of DigestEntry objects by regulation_category.
    Returns a list of dicts: [{label: str, entries: [DigestEntry]}]
    ordered by _CATEGORY_ORDER, with unknown categories appended at the end.
    """
    buckets: Dict[str, List[DigestEntry]] = {}
    for entry in entries:
        cat = (entry.regulation_category or "other").lower()
        buckets.setdefault(cat, []).append(entry)

    ordered_cats = [c for c in _CATEGORY_ORDER if c in buckets]
    remaining = [c for c in buckets if c not in _CATEGORY_ORDER]
    groups = []
    for cat in ordered_cats + remaining:
        groups.append({
            "label": CATEGORY_LABELS.get(cat, cat.replace("_", " ").title()),
            "entries": buckets[cat],
        })
    return groups



# ---------------------------------------------------------------------------
# Section classifier
# ---------------------------------------------------------------------------

_RELEVANCY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def _normalize_relevancy(value: Optional[str]) -> str:
    """
    Coerce the documents.confidence value into a HIGH/MEDIUM/LOW relevancy grade.

    New rows store HIGH/MEDIUM/LOW directly. Legacy rows may still hold the old
    keyword tier ('NEEDS_CONFIRMATION') — map that to LOW. Anything unknown or
    missing defaults to MEDIUM so the entry is neither hidden nor over-promoted.
    """
    v = (value or "").upper()
    if v in _RELEVANCY_RANK:
        return v
    if v == "NEEDS_CONFIRMATION":
        return "LOW"
    return "MEDIUM"


def _classify_section(row: DigestRow, today: date) -> str:
    """
    Assign one of two digest sections based on DB fields only. Relevancy is a
    separate axis (the HIGH/MEDIUM/LOW badge) and no longer affects the section.

    Section A — Any document WITH an active (future/today) comment window.
                The only actionable section: a comment can still be filed.
                Includes NOTICEs that reopen comment periods — the FR API often
                files these as NOTICE type rather than PRORULE.
    Section B — Everything else: final rules, notices with no/expired comment
                window, and any other document type. Tracking only.
    """
    has_open_comment = (
        row.comments_close_on is not None
        and row.comments_close_on >= today
    )

    if has_open_comment:
        return "A"

    return "B"


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
            "regulation_category": "",
        }


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_digest(
    rows: List[DigestRow],
    digest_date: date,
    *,
    _pre_classified: bool = False,
    _section_a: Optional[List] = None,
    _section_b: Optional[List] = None,
    _section_c: Optional[List] = None,
) -> DigestPackage:
    """
    Compile the full dual-layer digest package for a given day.

    Args:
        rows:            List of DigestRow objects. Pass [] for pre-classified path.
        digest_date:     The calendar date this digest represents.
        _pre_classified: If True, skip classification and use _section_X directly.
                         Used by the orchestrator for per-subscriber re-rendering.
        _section_a/b/c:  Pre-classified DigestEntry lists (only used when _pre_classified=True).

    Returns:
        DigestPackage with both html_body and text_body populated.
    """
    today = digest_date

    # -- Pre-classified fast-path (per-subscriber re-rendering) -----------------
    if _pre_classified:
        # Entries are already-assembled DigestEntry objects — skip classification
        # entirely and render straight from the supplied lists.
        section_a = list(_section_a or [])
        section_b = list(_section_b or [])
        section_c = list(_section_c or [])
    # -- Circuit breaker --------------------------------------------------------
    elif not rows:
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
    # -- Assemble entries from raw DigestRow objects ----------------------------
    else:
        section_a = []
        section_b = []
        section_c = []

        for row in rows:
            section = _classify_section(row, today)
            llm = _parse_llm_fields(row)

            entry = DigestEntry(
                document_number=row.document_number,
                title=row.title,
                agency_names=row.agency_names,
                # Prefer the animal-topic category from the LLM blob (welfare,
                # wildlife, ...). Fall back to the documents column only for legacy
                # rows whose blob predates the regulation_category element.
                regulation_category=(llm.get("regulation_category") or row.regulation_category),
                comments_close_on=row.comments_close_on,
                effective_on=row.effective_on,
                publication_date=row.publication_date,
                source_url=_build_source_url(row.document_number),
                comment_portal_url=_build_comment_url(row.comment_url),
                plain_language_summary=llm["plain_language_summary"],
                advocacy_relevance=llm["advocacy_relevance"],
                suggested_actions=llm["suggested_actions"],
                suggested_talking_points=llm["suggested_talking_points"],
                disclaimer=llm.get("disclaimer", _DISCLAIMER),
                is_public_inspection=(row.abstract is None),
                comments_days_left=(
                    (row.comments_close_on - today).days
                    if row.comments_close_on is not None
                    else None
                ),
                summarization_tier=row.summarization_tier,
                section=section,
                relevancy=_normalize_relevancy(row.confidence),
            )

            if section == "A":
                section_a.append(entry)
            else:
                section_b.append(entry)

        # Within each section, surface higher-relevancy documents first.
        # Section A keeps the query's deadline ordering as the tie-breaker.
        section_a.sort(key=lambda e: _RELEVANCY_RANK.get(e.relevancy, 1))
        section_b.sort(key=lambda e: (_RELEVANCY_RANK.get(e.relevancy, 1), e.document_number))

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
        # Category-grouped views for visual filtering in the email
        "section_a_groups": _group_by_category(section_a),
        "section_b_groups": _group_by_category(section_b),
        "section_c_groups": _group_by_category(section_c),
        "has_a": bool(section_a),
        "has_b": bool(section_b),
        "has_c": bool(section_c),
        "category_labels": CATEGORY_LABELS,
        "total": len(rows),
        "disclaimer": _DISCLAIMER,
        "built_at": datetime.now(timezone.utc),
        # URL of the Astro frontend — used to build "Draft a Comment" deep-links
        # in Section A cards. Leave unset (or empty) to hide the button.
        "frontend_url": os.environ.get("FRONTEND_URL", "").rstrip("/"),
    }

    html_body = _jinja_env.get_template("digest_email.html").render(**template_ctx)
    text_body = _jinja_env.get_template("digest_email.txt").render(**template_ctx)

    pkg = DigestPackage(
        digest_date=digest_date,
        html_body=html_body,
        text_body=text_body,
        is_zero_result=False,
        section_a_count=len(section_a),
        section_b_count=len(section_b),
        section_c_count=len(section_c),
        total_documents=len(section_a) + len(section_b) + len(section_c),
    )
    # Attach raw entry lists for per-subscriber filtering in the orchestrator
    pkg._section_a = section_a
    pkg._section_b = section_b
    pkg._section_c = section_c
    return pkg
