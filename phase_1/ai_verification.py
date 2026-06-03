import os
from typing import Literal

import instructor
import openai
from pydantic import BaseModel

import config
from models import FilteredDocument


class VerificationResult(BaseModel):
    is_relevant: bool
    confidence_reason: str  # one sentence max
    regulation_category: Literal["Proposed Rule", "Final Rule", "Notice", "Other"]


_HIGH_SYSTEM = (
    "You are a regulatory data extraction assistant for an animal law advocacy organization. "
    "This document has already been confirmed relevant by keyword match. "
    "Always set is_relevant=true. Your only tasks are: populate regulation_category "
    "and write one sentence in confidence_reason describing what the document covers."
)

_CONFIRM_SYSTEM = (
    "You are a relevance classifier for an animal law advocacy organization. "
    "Evaluate whether this federal document is relevant to animal welfare, animal law, "
    "wildlife protection, or related policy. Set is_relevant accordingly. "
    "Populate regulation_category and write one sentence in confidence_reason."
)


def verify_document(doc: FilteredDocument) -> VerificationResult:
    """Layer 3: classify document relevance and category using GPT-4o-mini."""
    client = instructor.from_openai(openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"]))

    system_prompt = _HIGH_SYSTEM if doc.confidence == "HIGH" else _CONFIRM_SYSTEM
    content = doc.abstract or doc.context_block or ""

    user_message = f"Title: {doc.title}\nContent: {content}"

    return client.chat.completions.create(
        model=config.AI_MODEL,
        max_tokens=config.AI_MAX_TOKENS,
        response_model=VerificationResult,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
