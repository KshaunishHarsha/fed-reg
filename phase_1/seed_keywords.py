"""
seed_keywords.py — populate the keywords table from keywords.yaml.

Run once after creating the table, or re-run to sync any YAML edits to the DB.
Terms are upserted: existing rows are re-enabled, new rows are inserted.
Terms removed from the YAML are NOT deleted — disable them manually if needed.

Usage:
    cd phase_1 && python seed_keywords.py
"""
import os
from pathlib import Path

import psycopg2
import psycopg2.extras
import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

_YAML_PATH = Path(__file__).parent / "keywords.yaml"

_LIST_MAP = {
    "anchor_terms": "anchor",
    "anchor_terms_word_boundary": "anchor_wb",
    "context_terms": "context",
    "noise_title_keywords": "noise_title",
}


def seed() -> None:
    with open(_YAML_PATH) as f:
        kw = yaml.safe_load(f)

    rows = [
        (term.strip(), list_type)
        for yaml_key, list_type in _LIST_MAP.items()
        for term in kw.get(yaml_key, [])
    ]

    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO keywords (term, list_type)
                VALUES %s
                ON CONFLICT (term, list_type) DO UPDATE SET enabled = true
                """,
                rows,
            )
        conn.commit()
        print(f"[seed_keywords] {len(rows)} keyword rows inserted/updated.")
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
