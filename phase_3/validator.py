"""
phase_3/validator.py
--------------------
Step 1: Post-Generation Validation & Self-Correction Loop (Phase 3's side).

Design alignment notes
----------------------
The schema (schemas.md) does NOT have a validation_attempts column or a
summarization_failed pipeline_state. The only states are:
    INGESTED → SUMMARY_GENERATED → DIGEST_SENT

Rather than adding columns to the schema owned by Phase 1, Phase 3 handles
the re-ask loop as an in-memory runtime concern:

  • Phase 3 exposes validate_blob() which parses + validates the XML blob
    and returns a structured ValidationOutcome.
  • The POST /phase3/ingest endpoint drives up to MAX_RETRIES retry cycles
    by calling Phase 2's correction endpoint with the exact Pydantic error
    string as the correction prompt payload.
  • If the model exhausts retries, the ingest endpoint returns HTTP 422 with
    the final error detail — Phase 2 is responsible for its own logging.
    Phase 3 never touches documents.pipeline_state for failed summaries
    (the row stays at SUMMARY_GENERATED, which is correct: it was generated
    but failed quality review and is excluded from the digest).

Self-correction loop: see router.py → _ingest_with_retry() for the full loop.
This file is purely the validation layer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from pydantic import ValidationError

from phase_3.models import ValidatedSummary, ValidationResult
from phase_3.xml_parser import XmlParseError, parse_xml_blob

logger = logging.getLogger(__name__)

# Silently strip URLs from LLM fields before Pydantic sees them.
# This is the one auto-corrected violation (logged, not bounced back).
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _strip_urls(data: dict) -> tuple[dict, bool]:
    """
    Strip any URLs from all string / list-of-string fields.
    Returns (cleaned_data, url_was_present).
    """
    stripped = False

    def clean(value: object) -> object:
        nonlocal stripped
        if isinstance(value, str) and _URL_RE.search(value):
            stripped = True
            return _URL_RE.sub("", value).strip()
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return {k: clean(v) for k, v in data.items()}, stripped


def validate_blob(
    document_number: str,
    xml_blob: str,
) -> ValidationResult:
    """
    Parse the raw xml_summary_blob and run all Pydantic v2 validation rules.

    Steps:
      1. Parse XML → dict  (XmlParseError if structurally broken)
      2. Strip any URLs silently and log the event
      3. Run ValidatedSummary(**parsed)  (raises ValidationError on rule violation)
      4. Return a ValidationResult with pass/fail + structured error detail

    The caller (router._ingest_with_retry) uses the error_detail string as the
    correction prompt body when re-asking Phase 2.
    """

    # -- Step 1: XML parse ---------------------------------------------------
    try:
        parsed = parse_xml_blob(xml_blob)
    except XmlParseError as exc:
        logger.warning(
            "[%s] XML parse failed: %s", document_number, exc
        )
        return ValidationResult(
            document_number=document_number,
            passed=False,
            error_detail=f"XML_PARSE_ERROR: {exc}",
        )

    # -- Step 2: URL strip ----------------------------------------------------
    parsed, url_stripped = _strip_urls(parsed)
    if url_stripped:
        logger.warning(
            "[%s] URLs were found in LLM output fields and silently removed. "
            "Instruct the model never to include hyperlinks in summaries.",
            document_number,
        )

    # -- Step 3: Pydantic validation ------------------------------------------
    try:
        validated = ValidatedSummary(**parsed)
    except ValidationError as exc:
        # Build a human-readable correction string from Pydantic's error list.
        # This exact string is forwarded to Phase 2 as the correction prompt.
        errors = exc.errors()
        detail_lines = []
        for err in errors:
            loc = " → ".join(str(l) for l in err["loc"])
            detail_lines.append(f"[{loc}] {err['msg']}")
        error_detail = (
            "VALIDATION_FAILED. The following rules were violated:\n"
            + "\n".join(f"  • {line}" for line in detail_lines)
            + "\n\nPlease regenerate the XML strictly following the schema "
            "constraints and resubmit."
        )
        logger.warning(
            "[%s] Validation failed (%d error(s)):\n%s",
            document_number,
            len(errors),
            error_detail,
        )
        return ValidationResult(
            document_number=document_number,
            passed=False,
            error_detail=error_detail,
            url_stripped=url_stripped,
        )

    # -- Step 4: Pass ---------------------------------------------------------
    logger.info("[%s] Validation passed.", document_number)
    return ValidationResult(
        document_number=document_number,
        passed=True,
        validated_summary=validated,
        url_stripped=url_stripped,
    )
