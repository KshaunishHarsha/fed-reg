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
    relevancy: Literal["HIGH", "MEDIUM", "LOW"]


_HIGH_SYSTEM = (
    "You are a regulatory data extraction assistant for an animal law advocacy organization. "
    "This document has already been confirmed relevant by a strong keyword match. "
    "Always set is_relevant=true and relevancy=HIGH. Your only tasks are: populate "
    "regulation_category and write one sentence in confidence_reason describing what the "
    "document covers."
)

_CONFIRM_SYSTEM = (
    "You are a relevance classifier for an animal law advocacy organization. "
    "This document matched only weaker contextual keywords, so judge it carefully. "
    "Evaluate whether it is relevant to animal welfare, animal law, wildlife protection, "
    "or related policy, and set is_relevant accordingly. "
    "Then grade relevancy: use MEDIUM when the document is clearly on-topic for animal "
    "advocacy, and LOW when the connection is tangential, incidental, or uncertain. "
    "Do not use HIGH — that level is reserved for direct keyword matches. "
    "Populate regulation_category and write one sentence in confidence_reason."
)


def verify_document(doc: FilteredDocument) -> VerificationResult:
    """Layer 3: classify document relevance and category via OpenRouter."""
    client = instructor.from_openai(openai.OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    ))

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
