"""
phase_3/mailing_list.py
-----------------------
Mailing list subscriber management backed by the `mailing_list` table.
Uses the same SQLAlchemy async engine as the rest of Phase 3.

Table DDL lives in schema.sql. Run migrations to add preference columns to
an existing deployment.

Category preference columns (pref_*):
  pref_welfare, pref_wildlife, pref_agriculture, pref_agricultural_subsidies,
  pref_research_animals, pref_marine, pref_trade
  All default to True (opt-in to all categories on subscribe).

Agency preference columns (pref_agency_*):
  pref_agency_ams, pref_agency_aphis, pref_agency_fsis, pref_agency_fda,
  pref_agency_noaa, pref_agency_fws, pref_agency_nih
  All default to True (opt-in to all agencies on subscribe).
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

# Maps DB column names → canonical agency name strings (matched against DigestEntry.agency_names)
AGENCY_PREF_COLUMNS: Dict[str, str] = {
    "pref_agency_ams":   "Agricultural Marketing Service",
    "pref_agency_aphis": "Animal and Plant Health Inspection Service",
    "pref_agency_fsis":  "Food Safety and Inspection Service",
    "pref_agency_fda":   "Food and Drug Administration",
    "pref_agency_noaa":  "National Oceanic and Atmospheric Administration",
    "pref_agency_fws":   "Fish and Wildlife Service",
    "pref_agency_nih":   "National Institutes of Health",
}

ALL_PREF_COLUMNS: Dict[str, str] = {**PREF_COLUMNS, **AGENCY_PREF_COLUMNS}
_ALL_PREF_COLS_SQL = ", ".join(ALL_PREF_COLUMNS.keys())

_CAT_KEYS = list(PREF_COLUMNS.keys())
_AGENCY_KEYS = list(AGENCY_PREF_COLUMNS.keys())
_ALL_KEYS = list(ALL_PREF_COLUMNS.keys())
_N_CAT = len(_CAT_KEYS)
_N_AGENCY = len(_AGENCY_KEYS)


async def add_subscriber(email: str, preferences: Optional[Dict[str, bool]] = None) -> dict:
    """
    Upsert an email into mailing_list.
    If the address already exists but is disabled, re-enables it and updates prefs.
    preferences: dict of {pref_column_name: bool} for any combination of category
                 and agency columns. Missing keys default to True.
    Returns {id, email, preferences}.
    """
    prefs = {col: preferences.get(col, True) if preferences else True for col in ALL_PREF_COLUMNS}
    pref_set_clause = ", ".join(f"{col} = :{col}" for col in ALL_PREF_COLUMNS)
    pref_cols = ", ".join(ALL_PREF_COLUMNS.keys())
    pref_placeholders = ", ".join(f":{col}" for col in ALL_PREF_COLUMNS)

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text(f"""
                INSERT INTO mailing_list (email, enabled, {pref_cols})
                VALUES (:email, true, {pref_placeholders})
                ON CONFLICT (email) DO UPDATE SET
                    enabled = true,
                    {pref_set_clause}
                RETURNING id, email, {_ALL_PREF_COLS_SQL}
            """),
            {"email": email, **prefs},
        )
        row = result.fetchone()
        await session.commit()

    return {
        "id": row[0],
        "email": row[1],
        "preferences": {_ALL_KEYS[i]: bool(row[2 + i]) for i in range(len(_ALL_KEYS))},
    }


async def update_preferences(email: str, preferences: Dict[str, bool]) -> dict:
    """
    Update category and/or agency preferences for an existing subscriber.
    Only updates the columns present in the preferences dict.
    Accepts any mix of pref_* and pref_agency_* keys.
    Returns {email, preferences} or raises ValueError if not found.
    """
    valid_prefs = {k: v for k, v in preferences.items() if k in ALL_PREF_COLUMNS}
    if not valid_prefs:
        raise ValueError("No valid preference columns provided.")

    set_clause = ", ".join(f"{col} = :{col}" for col in valid_prefs)
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text(f"""
                UPDATE mailing_list SET {set_clause}
                WHERE email = :email AND enabled = true
                RETURNING id, email, {_ALL_PREF_COLS_SQL}
            """),
            {"email": email, **valid_prefs},
        )
        row = result.fetchone()
        await session.commit()

    if row is None:
        raise ValueError(f"{email} not found in mailing list or is not enabled.")

    return {
        "email": row[1],
        "preferences": {_ALL_KEYS[i]: bool(row[2 + i]) for i in range(len(_ALL_KEYS))},
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
    Return all enabled subscribers with their category and agency preferences.
    Each dict: {email: str, allowed_categories: set[str], allowed_agencies: set[str]}
    Used by the orchestrator to send personalized digests.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text(f"""
                SELECT email, {_ALL_PREF_COLS_SQL}
                FROM mailing_list
                WHERE enabled = true
                ORDER BY created_at
            """)
        )
        rows = result.fetchall()

    subscribers = []
    for row in rows:
        # row[0]=email, row[1..N_CAT]=category prefs, row[N_CAT+1..]=agency prefs
        allowed_categories = {
            PREF_COLUMNS[_CAT_KEYS[i]]
            for i in range(_N_CAT)
            if bool(row[1 + i])
        }
        allowed_agencies = {
            AGENCY_PREF_COLUMNS[_AGENCY_KEYS[i]]
            for i in range(_N_AGENCY)
            if bool(row[1 + _N_CAT + i])
        }
        subscribers.append({
            "email": row[0],
            "allowed_categories": allowed_categories,
            "allowed_agencies": allowed_agencies,
        })
    return subscribers


async def get_active_subscribers() -> List[dict]:
    """
    Return full subscriber rows for the demo frontend subscriber list.
    Each dict: {email, created_at, preferences}.
    preferences includes both category (pref_*) and agency (pref_agency_*) columns.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text(f"""
                SELECT email, created_at, {_ALL_PREF_COLS_SQL}
                FROM mailing_list
                WHERE enabled = true
                ORDER BY created_at
            """)
        )
        rows = result.fetchall()

    return [
        {
            "email": row[0],
            "created_at": row[1].isoformat() if row[1] else None,
            "preferences": {_ALL_KEYS[i]: bool(row[2 + i]) for i in range(len(_ALL_KEYS))},
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
