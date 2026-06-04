import re
from typing import Optional

import requests
from bs4 import BeautifulSoup, Tag

_FR_API_BASE = "https://www.federalregister.gov/api/v1"

_URL_PATTERN = re.compile(r"https?://\S+")

# Section headers that signal low-signal boilerplate — strip these and their content.
_NOISE_HEADERS = {
    "background",
    "regulatory history",
    "historical background",
    "history",
    "list of subjects",
    "statutory authority",
    "authority",
    "signature",
    "regulatory flexibility act",
    "paperwork reduction act",
    "environmental impact",
    "executive order",
    "unfunded mandates reform act",
    "federalism",
    "takings",
    "small business regulatory enforcement fairness act",
    "congressional review act",
    "administrative practice and procedure",
}

# Section headers worth keeping explicitly — stop stripping when we hit these.
_SIGNAL_HEADERS = {
    "summary",
    "dates",
    "supplementary information",
    "action",
    "proposed rule",
    "rule",
    "regulatory text",
    "amendments",
    "preamble",
}


def get_body_html_url(document_number: str) -> Optional[str]:
    """Fetch the body_html_url for a document from the FR API."""
    resp = requests.get(
        f"{_FR_API_BASE}/documents/{document_number}.json",
        params=[("fields[]", "body_html_url")],
        timeout=30,
    )
    if resp.status_code != 200:
        return None
    return resp.json().get("body_html_url")


def prune(document_number: str) -> str:
    """Fetch and prune the HTML body for a Tier 2 document.
    Returns pruned plain text. Falls back to empty string on any failure.
    """
    body_url = get_body_html_url(document_number)
    if not body_url:
        return ""

    try:
        resp = requests.get(body_url, timeout=60)
        resp.raise_for_status()
    except Exception:
        return ""

    soup = BeautifulSoup(resp.text, "lxml")

    # Remove chrome elements
    for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    # Walk headings and strip noise sections (heading + all content until next heading)
    headings = soup.find_all(["h1", "h2", "h3", "h4"])
    for heading in headings:
        heading_text = heading.get_text(separator=" ").strip().lower()
        if any(noise in heading_text for noise in _NOISE_HEADERS):
            _remove_section(heading)

    # Collect remaining paragraphs, strip URLs
    paragraphs = []
    for p in soup.find_all("p"):
        text = p.get_text(separator=" ").strip()
        if not text:
            continue
        text = _URL_PATTERN.sub("", text).strip()
        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs)


def _remove_section(heading: Tag) -> None:
    """Remove a heading element and all its siblings until the next heading of equal or higher level."""
    level = int(heading.name[1])  # h2 → 2, h3 → 3, etc.
    to_remove = [heading]

    sibling = heading.next_sibling
    while sibling:
        if isinstance(sibling, Tag) and sibling.name in ["h1", "h2", "h3", "h4"]:
            sibling_level = int(sibling.name[1])
            if sibling_level <= level:
                break
        to_remove.append(sibling)
        sibling = sibling.next_sibling

    for node in to_remove:
        if isinstance(node, Tag):
            node.decompose()
        else:
            try:
                node.extract()
            except Exception:
                pass