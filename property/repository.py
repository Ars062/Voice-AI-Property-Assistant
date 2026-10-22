"""Read-only repository. Every property read goes through the restricted role."""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text

from database.db import read_session
from database.models import Policy, Room, RoomBlock
from property.query_plan import PropertyQueryPlan
from property.sql_builder import build_search

logger = logging.getLogger(__name__)


class RepositoryError(RuntimeError):
    """Raised when a read fails (e.g. database unavailable)."""


def _number(value: Decimal | float | int | None) -> float | None:
    return float(value) if value is not None else None


def _row_to_room(row) -> dict[str, Any]:
    return {
        "room_id": row["id"],
        "unit": row["unit_label"],
        "room_type": row["room_type"],
        "rent": _number(row["monthly_rent"]),
        "deposit": _number(row["deposit"]),
        "size_sqm": _number(row["size_sqm"]),
        "max_occupants": row["max_occupants"],
        "available_from": row["available_from"].isoformat(),
        "description": row["description"],
        "property_id": row["property_id"],
        "property_name": row["property_name"],
        "city": row["city"],
        "region": row["region"],
        "address": row["address_line"],
        "amenities": sorted(row["amenities"] or []),
    }


def search_rooms(plan: PropertyQueryPlan) -> list[dict[str, Any]]:
    clause, params = build_search(plan)
    try:
        with read_session() as db:
            rows = db.execute(clause, params).mappings().all()
    except Exception as exc:  # noqa: BLE001 - surface a typed error
        logger.exception("property search failed")
        raise RepositoryError(f"Property search failed: {exc}") from exc
    return [_row_to_room(row) for row in rows]


def get_room(room_id: int) -> dict[str, Any] | None:
    try:
        with read_session() as db:
            room = db.get(Room, room_id)
            if room is None:
                return None
            property_ = room.property
            result = {
                "room_id": room.id,
                "unit": room.unit_label,
                "room_type": room.room_type,
                "rent": _number(room.monthly_rent),
                "deposit": _number(room.deposit),
                "size_sqm": _number(room.size_sqm),
                "max_occupants": room.max_occupants,
                "available_from": room.available_from.isoformat(),
                "description": room.description,
                "property_id": room.property_id,
                "property_name": property_.name if property_ else None,
                "city": property_.city if property_ else None,
                "region": property_.region if property_ else None,
                "address": property_.address_line if property_ else None,
                "amenities": sorted(a.name for a in room.amenities),
            }
            if property_ is not None:
                result["policies"] = [
                    {"type": p.policy_type, "description": p.description}
                    for p in db.scalars(
                        select(Policy).where(Policy.property_id == property_.id)
                    ).all()
                ]
            blocks = db.scalars(
                select(RoomBlock).where(RoomBlock.room_id == room_id)
            ).all()
            result["blocked_ranges"] = [
                {"start": b.start_date.isoformat(), "end": b.end_date.isoformat(),
                 "reason": b.reason}
                for b in blocks
            ]
            return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("room detail failed")
        raise RepositoryError(f"Room lookup failed: {exc}") from exc


def list_amenities() -> list[dict[str, str]]:
    try:
        with read_session() as db:
            rows = db.execute(
                text("SELECT name, category FROM amenities ORDER BY name")
            ).mappings().all()
        return [{"name": r["name"], "category": r["category"]} for r in rows]
    except Exception as exc:  # noqa: BLE001
        raise RepositoryError(f"Amenity lookup failed: {exc}") from exc


def list_properties() -> list[dict[str, Any]]:
    try:
        with read_session() as db:
            rows = db.execute(
                text(
                    "SELECT id, name, city, region, property_type, description "
                    "FROM properties ORDER BY name"
                )
            ).mappings().all()
        return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        raise RepositoryError(f"Property lookup failed: {exc}") from exc


def check_availability(room_id: int, check_in: date, check_out: date) -> dict[str, Any]:
    if check_out <= check_in:
        return {"available": False, "reason": "check_out must be after check_in"}
    try:
        with read_session() as db:
            row = db.execute(
                text(
                    "SELECT r.is_active, r.available_from, "
                    "EXISTS ("
                    "  SELECT 1 FROM room_blocked_ranges br"
                    "  WHERE br.room_id = r.id"
                    "    AND br.start_date < :check_out"
                    "    AND br.end_date > :check_in"
                    ") AS is_blocked "
                    "FROM rooms r WHERE r.id = :room_id"
                ),
                {"room_id": room_id, "check_in": check_in, "check_out": check_out},
            ).mappings().first()
    except Exception as exc:  # noqa: BLE001
        raise RepositoryError(f"Availability check failed: {exc}") from exc

    if row is None:
        return {"available": False, "reason": f"room {room_id} does not exist"}
    if not row["is_active"]:
        return {"available": False, "reason": "room is not active"}
    if row["available_from"] > check_in:
        return {
            "available": False,
            "reason": f"room is only available from {row['available_from'].isoformat()}",
        }
    if row["is_blocked"]:
        return {"available": False, "reason": "room is already booked or blocked for those dates"}
    return {"available": True, "reason": None}
