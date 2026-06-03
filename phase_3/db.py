"""
phase_3/db.py
-------------
Async database engine and session factory for Phase 3.

Uses asyncpg (PostgreSQL) via SQLAlchemy async core — no ORM, just raw SQL
through text() to stay close to the schema as written in schema.sql.

DATABASE_URL must be set in the environment before the app starts, e.g.:
    DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname

Only Phase 3 code imports from this module. Phase 1 and Phase 2 manage their
own database connections independently.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Set it to a postgresql+asyncpg:// connection string before starting."
        )
    # Supabase / standard postgres URLs often come as postgresql:// — fix the driver.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def build_engine() -> AsyncEngine:
    """
    Build the SQLAlchemy async engine.
    Called once at application startup (see phase_3/lifespan.py or main.py).
    """
    return create_async_engine(
        _get_database_url(),
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,   # cheap health-check on checkout
        echo=False,
    )


# Module-level singletons — initialised by init_db() at startup.
_engine: AsyncEngine | None = None
_async_session_factory: sessionmaker | None = None


def init_db() -> None:
    """
    Initialise the module-level engine and session factory.
    Must be called once before any database operation, typically from the
    FastAPI lifespan handler or application startup event.
    """
    global _engine, _async_session_factory
    _engine = build_engine()
    _async_session_factory = sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine not initialised. Call init_db() first.")
    return _engine


def get_session_factory() -> sessionmaker:
    if _async_session_factory is None:
        raise RuntimeError("Session factory not initialised. Call init_db() first.")
    return _async_session_factory
