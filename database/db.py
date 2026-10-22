"""Database engines and session helpers (PostgreSQL only).

Two engines:
  * ``engine``        - admin/write connection (``DATABASE_URL``)
  * ``read_engine``   - restricted read-only role (``DATABASE_READONLY_URL``)

Every property search MUST use ``read_session``.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config import settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_read_engine: Engine | None = None


def _make_engine(url: str, *, readonly: bool = False) -> Engine:
    connect_args = {}
    if url.startswith("postgresql"):
        opts = "-c statement_timeout=%d" % settings.query_statement_timeout_ms
        if readonly:
            opts += " -c default_transaction_read_only=on"
        connect_args["options"] = opts
        connect_args["connect_timeout"] = 5
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
        connect_args=connect_args,
        future=True,
    )


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _make_engine(settings.database_url)
    return _engine


def get_read_engine() -> Engine:
    global _read_engine
    if _read_engine is None:
        _read_engine = _make_engine(settings.database_readonly_url, readonly=True)
    return _read_engine


@contextmanager
def session() -> Iterator[Session]:
    maker = sessionmaker(bind=get_engine(), expire_on_commit=False)
    db = maker()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def read_session() -> Iterator[Session]:
    maker = sessionmaker(bind=get_read_engine(), expire_on_commit=False)
    db = maker()
    try:
        yield db
    finally:
        db.close()


def health() -> dict:
    """Return database health and row counts. Never raises."""
    try:
        with read_session() as db:
            counts = {}
            for table in ("properties", "rooms", "amenities", "policies"):
                counts[table] = int(db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())
        return {"ok": True, "counts": counts}
    except Exception as exc:  # noqa: BLE001 - health probes must not raise
        logger.warning("database health check failed: %s", exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
