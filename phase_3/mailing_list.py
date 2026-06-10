"""
phase_3/mailing_list.py
-----------------------
Mailing list subscriber management backed by the `mailing_list` table.
Uses the same SQLAlchemy async engine as the rest of Phase 3.

Table DDL lives in schema.sql. Run migrate_add_preferences.py to add
category preference columns to an existing deployment.

Category preference columns:
  pref_welfare, pref_wildlife, pref_agriculture, pref_agricultural_subsidies,
  pref_research_animals, pref_marine, pref_trade
  All default to True (opt-in to all categories on subscribe).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import text

from phase_3.db import get_session_factory

# Maps DB column names → regulation_category values used by Phase 2 / digest_builder
PREF_COLUMNS: Dict[str, str] = {
    "pref_welfare":                "welfare",
    "pref_wildlife":               "wildlife",
    "pref_agriculture":            "agriculture",
    "pref_agricultural_subsidies": "agricultural_subsidies",
    "pref_research_animals":       "research_animals",
    "pref_marine":                 "marine",
    "pref_trade":                  "trade",
}

_PREF_COLS_SQL = ", ".join(PREF_COLUMNS.keys())


def _prefs_from_row(row) -> Dict[str, bool]:
    """Extract preference dict from a DB row tuple (after id, email, enabled, created_at)."""
    # Row layout: id, email, enabled, pref_welfare, pref_wildlife, ..., created_at
    pref_keys = list(PREF_COLUMNS.keys())
    return {pref_keys[i]: bool(row[3 + i]) for i in range(len(pref_keys))}


async def add_subscriber(email: str, preferences: Optional[Dict[str, bool]] = None) -> dict:
    """
    Upsert an email into mailing_list.
    If the address already exists but is disabled, re-enables it and updates prefs.
    preferences: dict of {pref_column_name: bool}, e.g. {"pref_wildlife": True}.
                 Missing keys default to True.
    Returns {id, email, preferences}.
    """
    prefs = {col: preferences.get(col, True) if preferences else True for col in PREF_COLUMNS}
    pref_set_clause = ", ".join(f"{col} = :{col}" for col in PREF_COLUMNS)
    pref_cols = ", ".join(PREF_COLUMNS.keys())
    pref_placeholders = ", ".join(f":{col}" for col in PREF_COLUMNS)

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text(f"""
                INSERT INTO mailing_list (email, enabled, {pref_cols})
                VALUES (:email, true, {pref_placeholders})
                ON CONFLICT (email) DO UPDATE SET
                    enabled = true,
                    {pref_set_clause}
                RETURNING id, email, {_PREF_COLS_SQL}
            """),
            {"email": email, **prefs},
        )
        row = result.fetchone()
        await session.commit()

    pref_keys = list(PREF_COLUMNS.keys())
    return {
        "id": row[0],
        "email": row[1],
        "preferences": {pref_keys[i]: bool(row[2 + i]) for i in range(len(pref_keys))},
    }


async def update_preferences(email: str, preferences: Dict[str, bool]) -> dict:
    """
    Update category preferences for an existing subscriber.
    Only updates the columns that are present in the preferences dict.
    Returns {email, preferences} or raises ValueError if not found.
    """
    valid_prefs = {k: v for k, v in preferences.items() if k in PREF_COLUMNS}
    if not valid_prefs:
        raise ValueError("No valid preference columns provided.")

    set_clause = ", ".join(f"{col} = :{col}" for col in valid_prefs)
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text(f"""
                UPDATE mailing_list SET {set_clause}
                WHERE email = :email AND enabled = true
                RETURNING id, email, {_PREF_COLS_SQL}
            """),
            {"email": email, **valid_prefs},
        )
        row = result.fetchone()
        await session.commit()

    if row is None:
        raise ValueError(f"{email} not found in mailing list or is not enabled.")

    pref_keys = list(PREF_COLUMNS.keys())
    return {
        "email": row[1],
        "preferences": {pref_keys[i]: bool(row[2 + i]) for i in range(len(pref_keys))},
    }


async def get_active_recipients() -> List[str]:
    """
    Return all enabled email addresses (for the zero-result / non-filtered digest).
    Used by the circuit-breaker zero-result path.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT email FROM mailing_list WHERE enabled = true ORDER BY created_at")
        )
        rows = result.fetchall()
    return [row[0] for row in rows]


async def get_active_recipients_with_prefs() -> List[Dict]:
    """
    Return all enabled subscribers with their category preferences.
    Each dict: {email: str, allowed_categories: set[str]}
    Used by the orchestrator to send personalized digests.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text(f"""
                SELECT email, {_PREF_COLS_SQL}
                FROM mailing_list
                WHERE enabled = true
                ORDER BY created_at
            """)
        )
        rows = result.fetchall()

    pref_keys = list(PREF_COLUMNS.keys())
    subscribers = []
    for row in rows:
        allowed = {
            PREF_COLUMNS[pref_keys[i]]
            for i in range(len(pref_keys))
            if bool(row[1 + i])
        }
        subscribers.append({"email": row[0], "allowed_categories": allowed})
    return subscribers


async def get_active_subscribers() -> List[dict]:
    """
    Return full subscriber rows for the demo frontend subscriber list.
    Each dict: {email, created_at, preferences}.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text(f"""
                SELECT email, created_at, {_PREF_COLS_SQL}
                FROM mailing_list
                WHERE enabled = true
                ORDER BY created_at
            """)
        )
        rows = result.fetchall()

    pref_keys = list(PREF_COLUMNS.keys())
    return [
        {
            "email": row[0],
            "created_at": row[1].isoformat() if row[1] else None,
            "preferences": {pref_keys[i]: bool(row[2 + i]) for i in range(len(pref_keys))},
        }
        for row in rows
    ]


async def disable_subscriber(email: str) -> dict:
    """
    Set enabled=false for the given email (soft-delete / unsubscribe).
    Returns {email, disabled} — disabled=False means address not found.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text("UPDATE mailing_list SET enabled = false WHERE email = :email RETURNING email"),
            {"email": email},
        )
        row = result.fetchone()
        await session.commit()
    return {"email": email, "disabled": row is not None}
