import os
import re
from pathlib import Path

import yaml

_keywords_path = Path(__file__).parent / "keywords.yaml"
with open(_keywords_path) as f:
    _kw = yaml.safe_load(f)

ANCHOR_TERMS: list[str] = [t.lower() for t in _kw["anchor_terms"]]
CONTEXT_TERMS: list[str] = [t.lower() for t in _kw["context_terms"]]
NOISE_TITLE_KEYWORDS: list[str] = [t.lower() for t in _kw["noise_title_keywords"]]

_wb_terms = [t.lower() for t in _kw.get("anchor_terms_word_boundary", [])]
ANCHOR_WB_PATTERN: re.Pattern | None = (
    re.compile(r"\b(" + "|".join(re.escape(t) for t in _wb_terms) + r")\b")
    if _wb_terms else None
)

TARGET_AGENCY_SLUGS = [
    "agricultural-marketing-service",
    "animal-and-plant-health-inspection-service",
    "food-safety-and-inspection-service",
    "food-and-drug-administration",
    "national-oceanic-and-atmospheric-administration",
    "fish-and-wildlife-service",
    "national-institutes-of-health",
]

TARGET_DOC_TYPES = ["RULE", "PRORULE", "NOTICE"]

CONTEXT_THRESHOLD = 2

AI_MODEL = "openai/gpt-4o-mini"
AI_MAX_TOKENS = 500

PIPELINE_RUN_HOUR = 7
PIPELINE_RUN_MINUTE = 30

FR_API_BASE = "https://www.federalregister.gov/api/v1"
