from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def db_required():
    from database.db import health

    status = health()
    if not status.get("ok"):
        pytest.skip(f"PostgreSQL not available: {status.get('error')}")
    return status


@pytest.fixture
def admin_cleanup():
    from sqlalchemy import text

    from database.db import session

    keys: list[str] = []
    yield keys
    if not keys:
        return
    with session() as db:
        db.execute(
            text("DELETE FROM bookings WHERE idempotency_key = ANY(:keys)"),
            {"keys": keys},
        )
