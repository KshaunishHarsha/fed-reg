import os
import re
from pathlib import Path
from typing import Optional

import instructor
import openai
from dotenv import load_dotenv

from models import DocumentRecord, DocumentSummary

load_dotenv(Path(__file__).parent.parent / ".env")

_URL_PATTERN = re.compile(r"https?://\S+")

_SYSTEM_BASE = """\
You are a regulatory intelligence assistant writing for attorneys and policy analysts \
at an animal law advocacy organization (Animal Legal Defense Fund).

Rules you must always follow:
- Write in plain language. No legal jargon or Latin terms.
- Never produce URLs, hyperlinks, or web addresses of any kind.
- Normalize all dates to YYYY-MM-DD format.
- If a date is not clearly stated in the document, return null — never infer or estimate.
- The disclaimer field must always be exactly: \
"This summary is informational only and does not constitute legal advice."
- regulation_category must be one of: welfare, wildlife, agriculture, research_animals, marine, trade.
- plain_language_summary must be 100 words or fewer.
- suggested_actions: maximum 3 items, each 25 words or fewer.
- suggested_talking_points: maximum 3 items, each 25 words or fewer.\
"""

_SYSTEM_PUBLIC_INSPECTION = """\

IMPORTANT — PUBLIC INSPECTION DOCUMENT:
This is a pre-publication filing. Official dates (comment deadlines, effective dates, \
hearing dates) are inserted by the Office of the Federal Register after filing and are \
not yet finalized. Return null for all date fields unless a date is explicitly stated \
in the document text provided.\
"""

_SYSTEM_HIGH_CONFIDENCE = """\

This document has already been confirmed as animal-law relevant by keyword analysis. \
Focus on extracting and presenting the advocacy content — do not re-evaluate relevance.\
"""

_CORRECTION_HEADER = """\

CORRECTION REQUIRED — A previous summary attempt was rejected:
{error_detail}

Address this specific issue in your revised summary.\
"""


def _build_system_prompt(doc: DocumentRecord, correction_note: Optional[str]) -> str:
    parts = [_SYSTEM_BASE]
    if doc.is_public_inspection:
        parts.append(_SYSTEM_PUBLIC_INSPECTION)
    if doc.confidence == "HIGH":
        parts.append(_SYSTEM_HIGH_CONFIDENCE)
    if correction_note:
        parts.append(_CORRECTION_HEADER.format(error_detail=correction_note))
    return "\n".join(parts)


def _sanitize(text: str) -> str:
    """Strip URLs from text before sending to LLM."""
    return _URL_PATTERN.sub("", text)


def summarize(
    doc: DocumentRecord,
    prepared_text: str,
    correction_note: Optional[str] = None,
) -> DocumentSummary:
    """Call GPT-4o-mini via OpenRouter with instructor self-correction (max 2 attempts)."""
    client = instructor.from_openai(
        openai.OpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1",
        )
    )

    system_prompt = _build_system_prompt(doc, correction_note)

    # Wrap content in XML tags to neutralize prompt-injection attempts in document text
    safe_text = _sanitize(prepared_text)
    user_content = (
        f"<document_payload>\n"
        f"Title: {doc.title}\n"
        f"Agency: {', '.join(doc.agency_names)}\n"
        f"Document Type: {doc.type or 'Unknown'}\n"
        f"Publication Date: {doc.publication_date}\n"
        f"Comment Deadline: {doc.comments_close_on or 'Not stated'}\n"
        f"Effective Date: {doc.effective_on or 'Not stated'}\n\n"
        f"Content:\n{safe_text}\n"
        f"</document_payload>"
    )

    return client.chat.completions.create(
        model="openai/gpt-4o-mini",
        max_tokens=1000,
        temperature=0,
        response_model=DocumentSummary,
        max_retries=2,  # instructor's internal Pydantic self-correction loop
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )