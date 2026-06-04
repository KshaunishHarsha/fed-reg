from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator, model_validator

DISCLAIMER = "This summary is informational only and does not constitute legal advice."


class DocumentRecord(BaseModel):
    """Represents a row read from the documents table."""
    document_number: str
    title: str
    agency_names: List[str] = []
    type: Optional[str] = None
    regulation_category: Optional[str] = None
    page_length: Optional[int] = None
    confidence: str
    abstract: Optional[str] = None
    context_block: Optional[str] = None
    comments_close_on: Optional[date] = None
    effective_on: Optional[date] = None
    html_url: str
    comment_url: Optional[str] = None
    publication_date: date
    pipeline_state: str

    @property
    def is_public_inspection(self) -> bool:
        """Inferred: no abstract but has context_block → public inspection filing."""
        return self.abstract is None


class DocumentSummary(BaseModel):
    """LLM output schema. All constraints enforced by Pydantic validators."""
    plain_language_summary: str
    advocacy_relevance: str
    suggested_actions: List[str]
    suggested_talking_points: List[str]
    comment_close_date: Optional[date] = None
    hearing_date: Optional[date] = None
    effective_date: Optional[date] = None
    disclaimer: str = DISCLAIMER
    regulation_category: Literal[
        "welfare", "wildlife", "agriculture", "research_animals", "marine", "trade"
    ]

    @field_validator("plain_language_summary")
    @classmethod
    def max_100_words(cls, v: str) -> str:
        count = len(v.split())
        if count > 100:
            raise ValueError(f"plain_language_summary has {count} words; maximum is 100.")
        return v

    @field_validator("advocacy_relevance")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("advocacy_relevance must not be empty.")
        return v

    @field_validator("suggested_actions")
    @classmethod
    def validate_actions(cls, v: List[str]) -> List[str]:
        if len(v) > 3:
            raise ValueError(f"suggested_actions has {len(v)} items; maximum is 3.")
        for i, action in enumerate(v):
            count = len(action.split())
            if count > 25:
                raise ValueError(
                    f"suggested_actions[{i}] has {count} words; maximum is 25."
                )
        return v

    @field_validator("suggested_talking_points")
    @classmethod
    def validate_talking_points(cls, v: List[str]) -> List[str]:
        if len(v) > 3:
            raise ValueError(f"suggested_talking_points has {len(v)} items; maximum is 3.")
        for i, point in enumerate(v):
            count = len(point.split())
            if count > 25:
                raise ValueError(
                    f"suggested_talking_points[{i}] has {count} words; maximum is 25."
                )
        return v

    @field_validator("disclaimer")
    @classmethod
    def enforce_disclaimer(cls, v: str) -> str:
        # Always overwrite with the hardcoded constant — never trust LLM output here.
        return DISCLAIMER
