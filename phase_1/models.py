from pydantic import BaseModel
from typing import Optional, List, Literal
from datetime import date


class RawDocument(BaseModel):
    document_number: str
    title: str
    abstract: Optional[str] = None
    agency_names: List[str] = []
    agency_slugs: List[str] = []
    document_type: Optional[str] = None
    type: Optional[str] = None
    subtype: Optional[str] = None
    page_length: Optional[int] = None
    html_url: str
    pdf_url: Optional[str] = None
    comment_url: Optional[str] = None
    comments_close_on: Optional[date] = None
    effective_on: Optional[date] = None
    significant: Optional[bool] = None
    publication_date: date


class FilteredDocument(RawDocument):
    confidence: Literal["HIGH", "NEEDS_CONFIRMATION"]
    context_block: Optional[str] = None  # populated by Layer 2a when abstract is absent


class ConfirmedDocument(FilteredDocument):
    is_relevant: bool
    regulation_category: str
    filter_reason: str
