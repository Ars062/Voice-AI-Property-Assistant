"""Tool layer used by the orchestrator.

Read tools go through the restricted read-only role. The booking tool uses the
write connection and relies on the database exclusion constraint for
concurrency safety plus a unique idempotency key for retries.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from database.db import session
from property import repository
from property.query_plan import PropertyQueryPlan

logger = logging.getLogger(__name__)


class BookingError(RuntimeError):
    """Invalid booking request."""


class BookingConflict(BookingError):
    """Room is not available for the requested dates."""


def search_properties(plan: PropertyQueryPlan | dict) -> dict[str, Any]:
    if isinstance(plan, dict):
        plan = PropertyQueryPlan(**plan)
    rooms = repository.search_rooms(plan)
    return {"count": len(rooms), "plan": plan.model_dump(mode="json"), "rooms": rooms}


def room_details(room_id: int) -> dict[str, Any] | None:
    return repository.get_room(room_id)


def amenities() -> list[dict[str, str]]:
    return repository.list_amenities()


def properties() -> list[dict[str, Any]]:
    return repository.list_properties()


def availability(room_id: int, check_in: date | str, check_out: date | str) -> dict[str, Any]:
    ci = date.fromisoformat(check_in) if isinstance(check_in, str) else check_in
    co = date.fromisoformat(check_out) if isinstance(check_out, str) else check_out
    return repository.check_availability(room_id, ci, co)


def _booking_row(row) -> dict[str, Any]:
    return {
        "booking_id": row["id"],
        "room_id": row["room_id"],
        "guest_name": row["guest_name"],
        "check_in": row["check_in"].isoformat(),
        "check_out": row["check_out"].isoformat(),
        "status": row["status"],
        "idempotency_key": row["idempotency_key"],
    }


def create_booking(
    *,
    room_id: int,
    guest_name: str,
    check_in: date | str,
    check_out: date | str,
    guest_email: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    ci = date.fromisoformat(check_in) if isinstance(check_in, str) else check_in
    co = date.fromisoformat(check_out) if isinstance(check_out, str) else check_out
    guest_name = (guest_name or "").strip()
    if not guest_name:
        raise BookingError("guest name is required")
    if co <= ci:
        raise BookingError("check_out must be after check_in")

    with session() as db:
        if idempotency_key:
            existing = db.execute(
                text(
                    "SELECT id, room_id, guest_name, check_in, check_out, status, "
                    "idempotency_key FROM bookings WHERE idempotency_key = :key"
                ),
                {"key": idempotency_key},
            ).mappings().first()
            if existing:
                return {**_booking_row(existing), "duplicate": True}

        room = db.execute(
            text("SELECT id, is_active, available_from FROM rooms WHERE id = :id"),
            {"id": room_id},
        ).mappings().first()
        if room is None:
            raise BookingError(f"room {room_id} does not exist")
        if not room["is_active"]:
            raise BookingError(f"room {room_id} is not active")
        if room["available_from"] > ci:
            raise BookingError(
                f"room {room_id} is only available from {room['available_from'].isoformat()}"
            )

        self_check = repository.check_availability(room_id, ci, co)
        if not self_check["available"]:
            raise BookingConflict(self_check["reason"] or "room is unavailable")

        try:
            inserted = db.execute(
                text(
                    "INSERT INTO bookings "
                    "(room_id, guest_name, guest_email, check_in, check_out, "
                    " status, idempotency_key) "
                    "VALUES (:room_id, :guest_name, :guest_email, :check_in, "
                    "        :check_out, 'confirmed', :idempotency_key) "
                    "RETURNING id, room_id, guest_name, check_in, check_out, "
                    "          status, idempotency_key"
                ),
                {
                    "room_id": room_id,
                    "guest_name": guest_name,
                    "guest_email": guest_email,
                    "check_in": ci,
                    "check_out": co,
                    "idempotency_key": idempotency_key,
                },
            ).mappings().one()
        except IntegrityError as exc:
            db.rollback()
            message = str(getattr(exc, "orig", exc))
            if "bookings_no_overlap" in message or "exclusion" in message:
                raise BookingConflict("room was just booked for those dates") from exc
            if idempotency_key and "idempotency_key" in message:
                existing = db.execute(
                    text(
                        "SELECT id, room_id, guest_name, check_in, check_out, status, "
                        "idempotency_key FROM bookings WHERE idempotency_key = :key"
                    ),
                    {"key": idempotency_key},
                ).mappings().first()
                if existing:
                    return {**_booking_row(existing), "duplicate": True}
            raise BookingError(f"could not create booking: {exc}") from exc

        return {**_booking_row(inserted), "duplicate": False}


TOOLS = {
    "search_properties": search_properties,
    "room_details": room_details,
    "amenities": amenities,
    "properties": properties,
    "availability": availability,
    "create_booking": create_booking,
}
