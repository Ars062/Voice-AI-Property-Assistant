from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from property.query_plan import PropertyQueryPlan
from property.sql_builder import build_search
from property.validator import UnsafeSQLError, validate_select_sql


def test_plan_rejects_bad_values():
    with pytest.raises(ValidationError):
        PropertyQueryPlan(max_rent=-10)
    with pytest.raises(ValidationError):
        PropertyQueryPlan(min_occupants=0)
    with pytest.raises(ValidationError):
        PropertyQueryPlan(sort_by="cheapest-ish")


def test_plan_normalises_amenities_and_dates():
    plan = PropertyQueryPlan(
        amenities=["WiFi", "Pet Friendly", "wifi"],
        available_from="2027-01-05",  # type: ignore[arg-type]
    )
    assert plan.amenities == ["wifi", "pet_friendly"]
    assert plan.available_from == date(2027, 1, 5)
    assert plan.is_empty() is False


def test_builder_parameterises_user_input():
    plan = PropertyQueryPlan(city="Austin'; DROP TABLE rooms; --", max_rent=1500)
    statement, params = build_search(plan)
    sql = str(statement)
    assert "Austin" not in sql
    assert "DROP" not in sql.upper()
    assert params["city"].startswith("%")
    assert "Austin" in params["city"]
    assert "LIMIT :limit" in sql


def test_builder_includes_availability_window():
    plan = PropertyQueryPlan(available_from=date(2027, 2, 1), available_to=date(2027, 3, 1))
    statement, params = build_search(plan)
    sql = str(statement)
    assert "room_blocked_ranges" in sql
    assert params["avail_from"] == date(2027, 2, 1)
    assert params["avail_to"] == date(2027, 3, 1)


@pytest.mark.parametrize(
    "sql",
    [
        "select id from rooms",
        "WITH x AS (select id from room_blocked_ranges) select * from x",
        "select id from amenities order by id",
    ],
)
def test_validator_allows_read_only_allowlist(sql):
    assert validate_select_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "select * from bookings",
        "select * from users",
        "select 1; drop table rooms",
        "select id from rooms -- comment",
        "delete from rooms",
        "update rooms set rent = 1",
        "select pg_sleep(5)",
        "select * from information_schema.tables",
        "select * from pg_catalog.pg_tables",
    ],
)
def test_validator_blocks_unsafe_sql(sql):
    with pytest.raises(UnsafeSQLError):
        validate_select_sql(sql)


def test_validator_adds_limit():
    assert "LIMIT 25" in validate_select_sql("select id from rooms")
