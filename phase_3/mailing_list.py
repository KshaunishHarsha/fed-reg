"""
phase_3/mailing_list.py
-----------------------
Mailing list subscriber management backed by the `mailing_list` Supabase table.
Uses the same SQLAlchemy async engine as the rest of Phase 3.

Table DDL lives in phase_1/schema.sql — run that once in Supabase to create it.
"""

from __future__ import annotations

from typing import List

from sqlalchemy import text

from phase_3.db import get_session_factory


async def add_subscriber(email: str) -> dict:
    """
    Upsert an email into mailing_list.
    If the address already exists but is disabled, re-enables it.
    Returns {"id": int, "email": str}.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text("""
                INSERT INTO mailing_list (email, enabled)
                VALUES (:email, true)
                ON CONFLICT (email) DO UPDATE SET enabled = true
                RETURNING id, email
            """),
            {"email": email},
        )
        row = result.fetchone()
        await session.commit()
    return {"id": row[0], "email": row[1]}


async def get_active_recipients() -> List[str]:
    """
    Return all enabled email addresses, ordered by subscription date.
    Returns an empty list if the table is empty or no enabled rows exist.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT email FROM mailing_list WHERE enabled = true ORDER BY created_at")
        )
        rows = result.fetchall()
    return [row[0] for row in rows]


async def get_active_subscribers() -> List[dict]:
    """
    Return full subscriber rows for enabled addresses.
    Each dict has "email" and "created_at" (ISO string or None).
    Used by the demo frontend to render the live subscriber list.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT email, created_at FROM mailing_list WHERE enabled = true ORDER BY created_at")
        )
        rows = result.fetchall()
    return [
        {"email": row[0], "created_at": row[1].isoformat() if row[1] else None}
        for row in rows
    ]


async def disable_subscriber(email: str) -> dict:
    """
    Set enabled=false for the given email (soft-delete / unsubscribe).
    Returns {"email": str, "disabled": bool} — disabled=False means address not found.
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
