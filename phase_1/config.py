import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

# ── Keyword lists — loaded from keywords.yaml (single source of truth) ─────────
_yaml_path = Path(__file__).parent / "keywords.yaml"
with open(_yaml_path, encoding="utf-8") as _f:
    _kw = yaml.safe_load(_f)

ANCHOR_TERMS: list[str] = [t.lower() for t in (_kw.get("anchor_terms") or [])]
CONTEXT_TERMS: list[str] = [t.lower() for t in (_kw.get("context_terms") or [])]
NOISE_TITLE_KEYWORDS: list[str] = [t.lower() for t in (_kw.get("noise_title_keywords") or [])]

_wb_terms = [t.lower() for t in (_kw.get("anchor_terms_word_boundary") or [])]
ANCHOR_WB_PATTERN: re.Pattern | None = (
    re.compile(r"\b(" + "|".join(re.escape(t) for t in _wb_terms) + r")\b")
    if _wb_terms else None
)


@dataclass
class AgencyFilter:
    extra_anchor_terms: list[str] = field(default_factory=list)
    extra_context_terms: list[str] = field(default_factory=list)
    context_threshold_override: Optional[int] = None


def _load_agency_filters(raw: dict) -> dict[str, AgencyFilter]:
    result: dict[str, AgencyFilter] = {}
    for slug, cfg in (raw or {}).items():
        result[slug] = AgencyFilter(
            extra_anchor_terms=[t.lower() for t in (cfg.get("extra_anchor_terms") or [])],
            extra_context_terms=[t.lower() for t in (cfg.get("extra_context_terms") or [])],
            context_threshold_override=cfg.get("context_threshold_override"),
        )
    return result


AGENCY_FILTERS: dict[str, AgencyFilter] = _load_agency_filters(_kw.get("agency_filters"))

# ── Static pipeline config ─────────────────────────────────────────────────────
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

