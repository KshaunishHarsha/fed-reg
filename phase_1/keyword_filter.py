from typing import Optional

import fitz  # PyMuPDF
import requests

import config
from models import FilteredDocument, RawDocument


def apply_keyword_filter(doc: RawDocument) -> Optional[FilteredDocument]:
    """
    Layer 2 + 2a entry point.
    Returns FilteredDocument if the doc passes, None if discarded.
    """
    # Step A: noise filter
    if _is_noise(doc):
        print(f"[NOISE DROP] {doc.document_number} — {doc.title}")
        return None

    # Step B: keyword scoring
    confidence = _score_keywords(doc)
    if confidence is None:
        return None

    filtered = FilteredDocument(**doc.model_dump(), confidence=confidence)

    # Step C: Layer 2a full-text scan (only when abstract is absent)
    if not doc.abstract:
        context_block = _full_text_scan(doc)
        if context_block is None:
            print(f"[FULLTEXT DROP] {doc.document_number}")
            return None
        filtered.context_block = context_block

    return filtered


# ---------------------------------------------------------------------------
# Step A
# ---------------------------------------------------------------------------

def _is_noise(doc: RawDocument) -> bool:
    if doc.type != "NOTICE":
        return False
    title_lower = (doc.title or "").lower()
    return any(kw in title_lower for kw in config.NOISE_TITLE_KEYWORDS)


# ---------------------------------------------------------------------------
# Step B
# ---------------------------------------------------------------------------

def _score_keywords(doc: RawDocument) -> Optional[str]:
    text = f"{doc.title} {doc.abstract or ''}".lower()

    for term in config.ANCHOR_TERMS:
        if term in text:
            return "HIGH"

    score = sum(1 for term in config.CONTEXT_TERMS if term in text)
    if score >= config.CONTEXT_THRESHOLD:
        return "NEEDS_CONFIRMATION"

    print(f"[KEYWORD DROP] {doc.document_number} — score: {score}")
    return None


# ---------------------------------------------------------------------------
# Step C — Layer 2a: full-text PDF scan
# ---------------------------------------------------------------------------

def _full_text_scan(doc: RawDocument) -> Optional[str]:
    """Download the PDF and scan for anchor terms. Returns context block or None."""
    if not doc.pdf_url:
        return None

    try:
        response = requests.get(doc.pdf_url, timeout=60)
        response.raise_for_status()
        pdf_bytes = response.content
    except requests.RequestException as exc:
        print(f"[FULLTEXT] PDF download failed for {doc.document_number}: {exc}")
        return None

    try:
        pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        print(f"[FULLTEXT] PDF parse failed for {doc.document_number}: {exc}")
        return None

    anchor_terms_lower = [t.lower() for t in config.ANCHOR_TERMS]
    context_windows: list[str] = []

    for page in pdf:
        page_text = page.get_text("text")
        paragraphs = [p.strip() for p in page_text.split("\n\n") if p.strip()]

        for idx, para in enumerate(paragraphs):
            para_lower = para.lower()
            if any(term in para_lower for term in anchor_terms_lower):
                before = paragraphs[max(0, idx - 2) : idx]
                after = paragraphs[idx + 1 : idx + 3]
                window = "\n\n".join(before + [para] + after)
                context_windows.append(window)

    pdf.close()

    if not context_windows:
        return None

    return "\n\n---\n\n".join(context_windows)
