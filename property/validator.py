"""Defence-in-depth validator for any model-generated SQL.

The primary path never uses model SQL (it uses `sql_builder`). This validator
exists so that a future "advanced query" feature cannot escape the allow-list.
It rejects multiple statements, comments, DDL/DML, dangerous functions, and any
table outside `ALLOWED_TABLES`.
"""
from __future__ import annotations

import re

from config import settings
from property.schema import (
    ALLOWED_TABLES,
    FORBIDDEN_KEYWORDS,
    FORBIDDEN_TABLES,
    FORBIDDEN_TOKENS,
)

_SELECT_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_TABLE_REF_RE = re.compile(r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE)
_CTE_RE = re.compile(r"(?:^with|,)\s+([a-z_][a-z0-9_]*)\s+as\s*\(", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\blimit\s+(\d+)\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z_]+")


class UnsafeSQLError(ValueError):
    """Raised when generated SQL violates the read-only allow-list."""


def validate_select_sql(sql: str, max_rows: int | None = None) -> str:
    max_rows = max_rows or settings.query_max_rows
    raw = (sql or "").strip()
    if not raw:
        raise UnsafeSQLError("empty SQL")

    candidate = raw.rstrip(";").strip()
    lowered = candidate.lower()

    if ";" in candidate:
        raise UnsafeSQLError("multiple statements are not allowed")
    if "--" in candidate or "/*" in candidate or "*/" in candidate:
        raise UnsafeSQLError("SQL comments are not allowed")
    if not _SELECT_RE.match(candidate):
        raise UnsafeSQLError("only SELECT / WITH queries are allowed")

    words = {w.lower() for w in _WORD_RE.findall(lowered)}
    forbidden = words & FORBIDDEN_KEYWORDS
    if forbidden:
        raise UnsafeSQLError(f"forbidden keyword(s): {', '.join(sorted(forbidden))}")
    if "into" in words and re.search(r"\bselect\b[\s\S]*\binto\b", lowered):
        raise UnsafeSQLError("SELECT INTO is not allowed")

    for token in FORBIDDEN_TOKENS:
        if token == ";":
            continue
        if token in lowered:
            raise UnsafeSQLError(f"forbidden token: {token}")

    refs = _TABLE_REF_RE.findall(candidate)
    if not refs:
        raise UnsafeSQLError("query must reference an allow-listed table")

    cte_names = {name.lower() for name in _CTE_RE.findall(lowered)}
    real_tables = [ref for ref in refs if ref.split(".")[-1].lower() not in cte_names]
    if not real_tables:
        raise UnsafeSQLError("query must reference an allow-listed table")

    for ref in real_tables:
        parts = ref.split(".")
        table = parts[-1].lower()
        if len(parts) > 1 and parts[0].lower() != "public":
            raise UnsafeSQLError(f"schema-qualified access is not allowed: {ref}")
        if table in FORBIDDEN_TABLES:
            raise UnsafeSQLError(f"table is not readable: {table}")
        if table not in ALLOWED_TABLES:
            raise UnsafeSQLError(f"table is not allow-listed: {table}")

    match = _LIMIT_RE.search(candidate)
    if not match:
        candidate = candidate + f" LIMIT {max_rows}"
    elif int(match.group(1)) > max_rows:
        candidate = _LIMIT_RE.sub(f"LIMIT {max_rows}", candidate)

    return candidate
