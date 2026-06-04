from datetime import date
from typing import List

import requests

import config
from models import RawDocument


_FR_FIELDS = [
    "document_number",
    "title",
    "abstract",
    "agency_names",
    "agencies",
    "publication_date",
    "type",
    "subtype",
    "page_length",
    "html_url",
    "pdf_url",
    "comment_url",
    "comments_close_on",
    "effective_on",
    "significant",
]


def _fetch_published(target_date: date) -> List[RawDocument]:
    """Fetch officially published documents from the FR API for the given date."""
    docs: List[RawDocument] = []
    url = f"{config.FR_API_BASE}/documents.json"

    params: list = []
    for slug in config.TARGET_AGENCY_SLUGS:
        params.append(("conditions[agencies][]", slug))
    params.append(("conditions[publication_date][is]", target_date.isoformat()))
    for doc_type in config.TARGET_DOC_TYPES:
        params.append(("conditions[type][]", doc_type))
    for field in _FR_FIELDS:
        params.append(("fields[]", field))
    params.append(("per_page", "100"))

    while url:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("results", []):
            doc = _parse_published(item, target_date)
            if doc:
                docs.append(doc)

        # Follow pagination; params are embedded in next_page_url
        next_url = data.get("next_page_url")
        url = next_url
        params = []  # next_page_url already includes all params

    return docs


def _parse_published(item: dict, target_date: date) -> RawDocument | None:
    doc_number = item.get("document_number")
    html_url = item.get("html_url")
    if not doc_number or not html_url:
        return None

    pub_date_raw = item.get("publication_date")
    try:
        pub_date = date.fromisoformat(pub_date_raw) if pub_date_raw else target_date
    except ValueError:
        pub_date = target_date

    agency_names = item.get("agency_names") or []

    return RawDocument(
        document_number=doc_number,
        title=item.get("title", ""),
        abstract=item.get("abstract") or None,
        agency_names=agency_names,
        document_type=item.get("document_type"),
        type=item.get("type"),
        subtype=item.get("subtype"),
        page_length=item.get("page_length"),
        html_url=html_url,
        pdf_url=item.get("pdf_url"),
        comment_url=item.get("comment_url"),
        comments_close_on=_parse_date(item.get("comments_close_on")),
        effective_on=_parse_date(item.get("effective_on")),
        significant=item.get("significant"),
        publication_date=pub_date,
    )


def _fetch_public_inspection(target_date: date) -> List[RawDocument]:
    """Fetch public inspection previews and filter client-side by agency slug and type."""
    url = f"{config.FR_API_BASE}/public-inspection-issues/{target_date.isoformat()}.json"
    resp = requests.get(url, timeout=30)
    if resp.status_code == 404:
        # No public inspection issue for this date (weekend, holiday, or future date)
        return []
    resp.raise_for_status()
    data = resp.json()

    target_slugs = set(config.TARGET_AGENCY_SLUGS)
    target_types = set(config.TARGET_DOC_TYPES)
    docs: List[RawDocument] = []

    for item in data.get("documents", []):
        doc_type = item.get("type", "").upper()
        if doc_type not in target_types:
            continue

        agencies = item.get("agencies", [])
        slugs = {a.get("slug", "") for a in agencies if isinstance(a, dict)}
        if not slugs & target_slugs:
            continue

        doc = _parse_inspection(item, target_date)
        if doc:
            docs.append(doc)

    return docs


def _parse_inspection(item: dict, target_date: date) -> RawDocument | None:
    doc_number = item.get("document_number")
    html_url = item.get("html_url")
    if not doc_number or not html_url:
        return None

    agencies = item.get("agencies", [])
    agency_names = [
        a.get("raw_name") or a.get("name") or a.get("slug", "")
        for a in agencies
        if isinstance(a, dict)
    ]

    return RawDocument(
        document_number=doc_number,
        title=item.get("title", ""),
        abstract=item.get("abstract") or None,
        agency_names=agency_names,
        document_type=item.get("document_type"),
        type=item.get("type"),
        subtype=item.get("subtype"),
        page_length=item.get("page_length"),
        html_url=html_url,
        pdf_url=item.get("pdf_url"),
        comment_url=item.get("comment_url"),
        comments_close_on=_parse_date(item.get("comments_close_on")),
        effective_on=_parse_date(item.get("effective_on")),
        significant=item.get("significant"),
        # Pre-publication docs use today as publication_date
        publication_date=target_date,
    )


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def fetch_documents(target_date: date) -> List[RawDocument]:
    """Layer 1 entry point. Returns deduplicated RawDocuments from both FR feeds."""
    published = _fetch_published(target_date)
    inspection = _fetch_public_inspection(target_date)

    seen: dict[str, RawDocument] = {}
    for doc in published + inspection:
        if doc.document_number not in seen:
            seen[doc.document_number] = doc

    return list(seen.values())
