import os
import re

ANCHOR_TERMS: list[str] = []
CONTEXT_TERMS: list[str] = []
NOISE_TITLE_KEYWORDS: list[str] = []
ANCHOR_WB_PATTERN: re.Pattern | None = None

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


def load_keywords_from_db() -> None:
    """Fetch enabled keywords from the DB and populate module-level lists."""
    import psycopg2
    import psycopg2.extras

    global ANCHOR_TERMS, CONTEXT_TERMS, NOISE_TITLE_KEYWORDS, ANCHOR_WB_PATTERN

    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT term, list_type FROM keywords WHERE enabled = true ORDER BY list_type, term"
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    ANCHOR_TERMS = [r["term"].lower() for r in rows if r["list_type"] == "anchor"]
    CONTEXT_TERMS = [r["term"].lower() for r in rows if r["list_type"] == "context"]
    NOISE_TITLE_KEYWORDS = [r["term"].lower() for r in rows if r["list_type"] == "noise_title"]

    wb_terms = [r["term"].lower() for r in rows if r["list_type"] == "anchor_wb"]
    ANCHOR_WB_PATTERN = (
        re.compile(r"\b(" + "|".join(re.escape(t) for t in wb_terms) + r")\b")
        if wb_terms else None
    )
