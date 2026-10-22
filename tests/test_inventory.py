from __future__ import annotations

from datetime import date, timedelta

from property.query_plan import PropertyQueryPlan
from property.tools import room_details, search_properties


def test_inventory_is_seeded(db_required):
    result = search_properties(PropertyQueryPlan(limit=25))
    assert result["count"] == 12


def test_filter_city_rent_and_amenity(db_required):
    rooms = search_properties(
        PropertyQueryPlan(city="austin", max_rent=1500, amenities=["wifi"])
    )["rooms"]
    assert {room["room_id"] for room in rooms} == {1, 2, 5, 6}
    assert all(float(room["rent"]) <= 1500 for room in rooms)


def test_filter_room_type_and_amenity(db_required):
    rooms = search_properties(
        PropertyQueryPlan(room_type="2 bedroom", amenities=["pet_friendly"])
    )["rooms"]
    assert {room["room_id"] for room in rooms} == {4, 11}


def test_no_match_returns_empty(db_required):
    rooms = search_properties(PropertyQueryPlan(city="Atlantis"))["rooms"]
    assert rooms == []


def test_availability_excludes_booked_room(db_required):
    start = date.today() + timedelta(days=1)
    end = start + timedelta(days=60)
    rooms = search_properties(
        PropertyQueryPlan(
            available_from=start.isoformat(),
            available_to=end.isoformat(),
            limit=25,
        )
    )["rooms"]
    ids = {room["room_id"] for room in rooms}
    assert 1 in ids
    assert 2 not in ids, "room 2 has a seeded booking in this window"
    assert 12 not in ids, "room 12 has a seeded block in this window"


def test_room_details_include_policies(db_required):
    detail = room_details(3)
    assert detail is not None
    assert detail["room_id"] == 3
    assert "parking" in detail["amenities"]
    assert any(policy["type"] == "pets" for policy in detail["policies"])
