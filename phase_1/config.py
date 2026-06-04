import os
from pathlib import Path

import yaml

_keywords_path = Path(__file__).parent / "keywords.yaml"
with open(_keywords_path) as f:
    _kw = yaml.safe_load(f)

ANCHOR_TERMS: list[str] = _kw["anchor_terms"]
CONTEXT_TERMS: list[str] = _kw["context_terms"]
NOISE_TITLE_KEYWORDS: list[str] = _kw["noise_title_keywords"]

TARGET_AGENCY_SLUGS = [
    "agricultural-marketing-service",
    "animal-and-plant-health-inspection-service",
    "food-safety-and-inspection-service",
    "food-and-drug-administration",
    "national-oceanic-and-atmospheric-administration",
    "fish-and-wildlife-service",
    "national-institutes-of-health",
]

# Only these document types are fetched. PRESDOCU excluded entirely.
TARGET_DOC_TYPES = ["RULE", "PRORULE", "NOTICE"]

CONTEXT_THRESHOLD = 2

AI_MODEL = "openai/gpt-4o-mini"
AI_MAX_TOKENS = 500

PIPELINE_RUN_HOUR = 7
PIPELINE_RUN_MINUTE = 30

FR_API_BASE = "https://www.federalregister.gov/api/v1"