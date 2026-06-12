"""
phase_2/comment_drafter.py
--------------------------
"Draft a Comment" feature — generates a formal public comment letter for a
proposed rule, on demand, when a user clicks the button in the email digest.

Design notes
------------
This is a fast, cheap LLM call. It does NOT re-read the source PDF. Instead it
reuses the advocacy talking points + relevance that were already generated and
stored in summaries.xml_summary_blob during the morning pipeline run. The model
only has to turn those bullet points into a 3-4 paragraph letter, so it finishes
in a few seconds and costs a fraction of a cent.

Lives in Phase 2 because Phase 2 owns the OpenRouter/instructor LLM client and
the DB access. Phase 3 forbids LLM calls (CLAUDE.md design rule #2), so the
endpoint is exposed at /phase2/draft-comment, not /phase3/.

Flow:
  1. fetch_document_by_number()  → title, agency, comment_url, dates  [async DB]
  2. fetch_summary_blob()        → the stored XML summary             [async DB]
  3. parse talking points + advocacy_relevance out of the blob
  4. one GPT-4o-mini call (temperature 0) to draft the letter
  5. return the draft text + the regulations.gov submit link
"""

from __future__ import annotations

import asyncio
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional

import openai
from dotenv import load_dotenv

from phase_2.database import fetch_document_by_number, fetch_summary_blob

load_dotenv(Path(__file__).parent.parent / ".env")

_URL_PATTERN = re.compile(r"https?://\S+")
_MODEL = "openai/gpt-4o-mini"


class DraftCommentError(Exception):
    """Raised when a draft cannot be produced. `status` mirrors the HTTP code to return."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


_SYSTEM_PROMPT = """\
You are an animal welfare advocate writing a formal public comment letter on a \
proposed federal rule on behalf of the Animal Legal Defense Fund.

Rules you must always follow:
- Base your arguments ENTIRELY on the talking points and position summary provided. \
Do not invent facts, statistics, or cite statutes that are not mentioned.
- Structure the letter as: a formal greeting addressed to the agency, a clear \
statement of position, two to three paragraphs of substantive argument drawn from \
the talking points, and a professional sign-off.
- Use the literal placeholder [Your Name/Organization] for the signature block. \
Do not invent a signer.
- Keep it to 3-4 paragraphs. Write in plain, persuasive language.
- Never include URLs, hyperlinks, or web addresses of any kind.
- Output only the letter text. Do not add commentary, headers, or markdown.\
"""


def _sanitize(text: str) -> str:
    """Strip URLs from any text before it reaches the model (project convention)."""
    return _URL_PATTERN.sub("", text or "").strip()


def _parse_summary(blob: str) -> dict:
    """Pull the advocacy fields out of the stored XML summary blob.

    Returns a dict with advocacy_relevance, plain_language_summary, and
    talking_points (list). Missing fields default to empty so a partial blob
    still yields a usable draft.
    """
    try:
        root = ET.fromstring(blob.strip())
    except ET.ParseError as exc:
        raise DraftCommentError(
            f"Stored summary for this document is malformed XML: {exc}", status=500
        ) from exc

    def _text(tag: str) -> str:
        el = root.find(tag)
        return (el.text or "").strip() if el is not None else ""

    points_parent = root.find("suggested_talking_points")
    talking_points = (
        [(el.text or "").strip() for el in points_parent.findall("point")]
        if points_parent is not None
        else []
    )

    return {
        "advocacy_relevance": _text("advocacy_relevance"),
        "plain_language_summary": _text("plain_language_summary"),
        "talking_points": [p for p in talking_points if p],
    }


def _regulations_gov_url(comment_url: Optional[str]) -> Optional[str]:
    """Build the regulations.gov submit link from the stored comment_url / docket ID."""
    if not comment_url or not comment_url.strip():
        return None
    cu = comment_url.strip()
    if cu.startswith("http://") or cu.startswith("https://"):
        return cu
    return f"https://www.regulations.gov/commentOn?D={cu}"


def _build_user_payload(
    title: str,
    agencies: List[str],
    comment_deadline: Optional[str],
    advocacy_relevance: str,
    plain_language_summary: str,
    talking_points: List[str],
) -> str:
    points_block = "\n".join(f"- {_sanitize(p)}" for p in talking_points) or "- (none provided)"
    return (
        "<document_payload>\n"
        f"Title: {_sanitize(title)}\n"
        f"Agency: {_sanitize(', '.join(agencies))}\n"
        f"Comment Deadline: {comment_deadline or 'Not stated'}\n\n"
        f"Position summary: {_sanitize(advocacy_relevance)}\n\n"
        f"Plain-language summary of the rule: {_sanitize(plain_language_summary)}\n\n"
        "Key talking points to build the argument from:\n"
        f"{points_block}\n"
        "</document_payload>"
    )


def _generate_letter(user_payload: str) -> str:
    """Synchronous OpenRouter call. Run via asyncio.to_thread so it never blocks the loop."""
    client = openai.OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )
    response = client.chat.completions.create(
        model=_MODEL,
        max_tokens=900,
        temperature=0,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_payload},
        ],
    )
    return (response.choices[0].message.content or "").strip()


async def draft_comment(document_number: str) -> dict:
    """Generate a public comment letter for `document_number`.

    Raises DraftCommentError (with an HTTP-style .status) if the document or its
    summary is missing, or if the LLM returns nothing.
    """
    doc = await fetch_document_by_number(document_number)
    if doc is None:
        raise DraftCommentError(f"Document {document_number} not found.", status=404)

    blob = await fetch_summary_blob(document_number)
    if not blob:
        raise DraftCommentError(
            f"No summary has been generated for {document_number} yet — "
            "the draft is built from the morning pipeline's talking points.",
            status=404,
        )

    fields = _parse_summary(blob)
    payload = _build_user_payload(
        title=doc.title,
        agencies=doc.agency_names,
        comment_deadline=str(doc.comments_close_on) if doc.comments_close_on else None,
        advocacy_relevance=fields["advocacy_relevance"],
        plain_language_summary=fields["plain_language_summary"],
        talking_points=fields["talking_points"],
    )

    letter = await asyncio.to_thread(_generate_letter, payload)
    if not letter:
        raise DraftCommentError("The model returned an empty draft. Try again.", status=502)

    return {
        "document_number": document_number,
        "title": doc.title,
        "agency_names": doc.agency_names,
        "comments_close_on": doc.comments_close_on.isoformat() if doc.comments_close_on else None,
        "source_url": f"https://www.federalregister.gov/d/{document_number}",
        "regulations_gov_url": _regulations_gov_url(doc.comment_url),
        "draft_comment": letter,
    }
