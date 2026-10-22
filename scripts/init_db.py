"""Apply schema, restricted role, and synthetic seed to PostgreSQL.

Usage:
    python scripts/init_db.py            # create if missing + seed
    python scripts/init_db.py --reset    # drop app objects, recreate, reseed
    python scripts/init_db.py --check    # print row counts only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings

SQL_DIR = ROOT / "sql"
SQL_FILES = ["001_schema.sql", "002_roles.sql", "003_seed.sql"]

RESET_SQL = """
DROP VIEW IF EXISTS room_blocked_ranges CASCADE;
DROP TABLE IF EXISTS bookings CASCADE;
DROP TABLE IF EXISTS room_blocks CASCADE;
DROP TABLE IF EXISTS room_amenities CASCADE;
DROP TABLE IF EXISTS policies CASCADE;
DROP TABLE IF EXISTS amenities CASCADE;
DROP TABLE IF EXISTS rooms CASCADE;
DROP TABLE IF EXISTS properties CASCADE;
"""

TABLES = ["properties", "rooms", "amenities", "room_amenities", "policies",
          "bookings", "room_blocks"]


def _admin_dsn() -> str:
    dsn = settings.database_url
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgresql://"):
        if dsn.startswith(prefix):
            return "postgresql://" + dsn[len(prefix):]
    return dsn


def _connect():
    import psycopg

    return psycopg.connect(_admin_dsn(), autocommit=True)


def _run_sql_file(conn, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)


def apply_all(reset: bool = False) -> None:
    with _connect() as conn:
        if reset:
            print("resetting application objects ...")
            with conn.cursor() as cur:
                cur.execute(RESET_SQL)
        for name in SQL_FILES:
            path = SQL_DIR / name
            print(f"applying {name} ...")
            _run_sql_file(conn, path)


def print_counts() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            for table in TABLES:
                cur.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 - fixed names
                print(f"  {table:16s} {cur.fetchone()[0]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize the property database")
    parser.add_argument("--reset", action="store_true", help="drop and recreate all app objects")
    parser.add_argument("--check", action="store_true", help="only print row counts")
    args = parser.parse_args()

    try:
        if args.check:
            print_counts()
            return 0
        apply_all(reset=args.reset)
        print("\nrow counts:")
        print_counts()
        print("\ndone.")
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level CLI
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"\nIs PostgreSQL running? Expected: {settings.database_url}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
