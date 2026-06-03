"""
phase_3/models.py
-----------------
Pydantic v2 models used exclusively by Phase 3.

Phase 3 does NOT call the LLM. It receives an xml_summary_blob (stored in
the `summaries` table by Phase 2) and parses + validates it here before any
digest compilation or DB state update occurs.

Schema alignment notes (schemas.md):
  - summaries.xml_summary_blob  → parsed into ValidatedSummary
  - documents.*                 → carried alongside as DocumentRecord
  - Phase 3 only writes: documents.pipeline_state → 'DIGEST_SENT'
  - No new tables are created or required by Phase 3.
"""

from __future__ import annotations

import re
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DISCLAIMER_EXACT = (
    "This summary is informational only and does not constitute legal advice."
)
MAX_SENTENCE_SUMMARY = 3
MAX_SENTENCE_RELEVANCE = 2
MAX_ITEMS_ACTIONS = 3
MAX_ITEMS_POINTS = 3
MAX_WORDS_PER_ITEM = 25
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _count_sentences(text: str) -> int:
    """Heuristic sentence counter: split on . ! ? followed by whitespace."""
    stripped = text.strip()
    if not stripped:
        return 0
    parts = _SENTENCE_SPLIT.split(stripped)
    return len([p for p in parts if p.strip()])


def _word_count(text: str) -> int:
    return len(text.split())


# ---------------------------------------------------------------------------
# Parsed LLM payload  (comes from xml_summary_blob via XmlParser)
# ---------------------------------------------------------------------------

class ValidatedSummary(BaseModel):
    """
    Represents the parsed, validated content of a Phase 2 xml_summary_blob.

    Field constraints exactly match the contract in llm_output_contract.md:
      - plain_language_summary  : 1-3 sentences, no URLs
      - advocacy_relevance      : 1-2 sentences, no URLs
      - suggested_actions       : 1-3 items, ≤25 words each, no URLs
      - suggested_talking_points: 1-3 items, ≤25 words each, no URLs
      - disclaimer              : must be the exact hardcoded string

    Raises ValidationError (Pydantic v2) with a structured message describing
    the specific rule that was violated. The caller (Phase 2 retry loop or
    Phase 3 ingest endpoint) catches this to decide whether to retry or flag.
    """

    plain_language_summary: str
    advocacy_relevance: str
    suggested_actions: List[str]
    suggested_talking_points: List[str]
    disclaimer: str

    # ------------------------------------------------------------------ #
    # Field-level validators                                               #
    # ------------------------------------------------------------------ #

    @field_validator("plain_language_summary")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("plain_language_summary must not be empty.")
        if URL_PATTERN.search(v):
            raise ValueError(
                "plain_language_summary must not contain URLs. "
                "Links are injected from the database, never from LLM output."
            )
        count = _count_sentences(v)
        if count > MAX_SENTENCE_SUMMARY:
            raise ValueError(
                f"plain_language_summary has {count} sentences; "
                f"maximum is {MAX_SENTENCE_SUMMARY}."
            )
        return v

    @field_validator("advocacy_relevance")
    @classmethod
    def validate_relevance(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("advocacy_relevance must not be empty.")
        if URL_PATTERN.search(v):
            raise ValueError(
                "advocacy_relevance must not contain URLs."
            )
        count = _count_sentences(v)
        if count > MAX_SENTENCE_RELEVANCE:
            raise ValueError(
                f"advocacy_relevance has {count} sentences; "
                f"maximum is {MAX_SENTENCE_RELEVANCE}."
            )
        return v

    @field_validator("suggested_actions")
    @classmethod
    def validate_actions(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("suggested_actions must contain at least 1 item.")
        if len(v) > MAX_ITEMS_ACTIONS:
            raise ValueError(
                f"suggested_actions has {len(v)} items; "
                f"maximum is {MAX_ITEMS_ACTIONS}."
            )
        for i, item in enumerate(v, start=1):
            if URL_PATTERN.search(item):
                raise ValueError(
                    f"suggested_actions item {i} must not contain URLs."
                )
            wc = _word_count(item)
            if wc > MAX_WORDS_PER_ITEM:
                raise ValueError(
                    f"suggested_actions item {i} has {wc} words; "
                    f"maximum is {MAX_WORDS_PER_ITEM}."
                )
        return [item.strip() for item in v]

    @field_validator("suggested_talking_points")
    @classmethod
    def validate_points(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError(
                "suggested_talking_points must contain at least 1 item."
            )
        if len(v) > MAX_ITEMS_POINTS:
            raise ValueError(
                f"suggested_talking_points has {len(v)} items; "
                f"maximum is {MAX_ITEMS_POINTS}."
            )
        for i, item in enumerate(v, start=1):
            if URL_PATTERN.search(item):
                raise ValueError(
                    f"suggested_talking_points item {i} must not contain URLs."
                )
            wc = _word_count(item)
            if wc > MAX_WORDS_PER_ITEM:
                raise ValueError(
                    f"suggested_talking_points item {i} has {wc} words; "
                    f"maximum is {MAX_WORDS_PER_ITEM}."
                )
        return [item.strip() for item in v]

    @field_validator("disclaimer")
    @classmethod
    def validate_disclaimer(cls, v: str) -> str:
        if v.strip() != DISCLAIMER_EXACT:
            raise ValueError(
                f"disclaimer must be exactly: '{DISCLAIMER_EXACT}'. "
                f"Received: '{v.strip()}'"
            )
        return v.strip()


# ---------------------------------------------------------------------------
# Document record  (fetched from `documents` table — no LLM fields)
# ---------------------------------------------------------------------------

class DocumentRecord(BaseModel):
    """
    Mirrors the columns Phase 3 reads from the `documents` table.
    All values come directly from the database (originally from the
    Federal Register API + Phase 1 extraction). No LLM-generated text.
    """

    document_number: str
    title: str
    agency_names: Optional[List[str]] = None
    type: Optional[str] = None                  # RULE | PRORULE | NOTICE
    regulation_category: Optional[str] = None   # Proposed Rule | Final Rule | Notice | Other
    comments_close_on: Optional[date] = None
    effective_on: Optional[date] = None
    html_url: Optional[str] = None
    comment_url: Optional[str] = None
    publication_date: date
    confidence: Optional[str] = None            # HIGH | NEEDS_CONFIRMATION
    pipeline_state: str = "SUMMARY_GENERATED"


# ---------------------------------------------------------------------------
# Combined ingest payload  (what Phase 2 posts to /phase3/ingest)
# ---------------------------------------------------------------------------

class IngestPayload(BaseModel):
    """
    The full envelope posted to POST /phase3/ingest by Phase 2.

    document_record : metadata row from `documents` table
    xml_summary_blob: raw XML string from `summaries` table (xml_summary_blob)

    Phase 3 parses xml_summary_blob → ValidatedSummary internally.
    The raw blob is never modified; it stays in the summaries table as-is.
    """

    document_record: DocumentRecord
    xml_summary_blob: str


# ---------------------------------------------------------------------------
# Validation result  (returned by the validator to the caller)
# ---------------------------------------------------------------------------

class ValidationResult(BaseModel):
    """Outcome of a single validation run."""

    document_number: str
    passed: bool
    validated_summary: Optional[ValidatedSummary] = None
    error_detail: Optional[str] = None      # structured rule violation message
    url_stripped: bool = False              # True if URLs were silently removed
