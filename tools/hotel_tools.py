"""LangChain tools that read/write the hotel database."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from langchain_core.tools import tool
from sqlalchemy import select

from database.models import Booking, Room, get_sessionmaker
from config import settings


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


@tool
def search_rooms(room_type: Optional[str] = None,
                 check_in: Optional[str] = None,
                 check_out: Optional[str] = None) -> str:
    """Search for available rooms. Optionally filter by room_type
    (Standard/Deluxe/Suite) and a date range (YYYY-MM-DD)."""
    Session = get_sessionmaker(settings.database_url)
    with Session() as s:
        q = select(Room).where(Room.available.is_(True))
        if room_type:
            q = q.where(Room.room_type.ilike(f"%{room_type}%"))
        rooms = s.scalars(q).all()

        if not rooms:
            return "No rooms are currently available."

        lines = []
        for r in rooms:
            lines.append(
                f"Room {r.room_number} | {r.room_type} | "
                f"${r.price_per_night}/night"
            )
        return "Available rooms:\n" + "\n".join(lines)


@tool
def check_price(room_type: Optional[str] = None) -> str:
    """Return nightly prices, optionally for a single room_type."""
    Session = get_sessionmaker(settings.database_url)
    with Session() as s:
        q = select(Room)
        if room_type:
            q = q.where(Room.room_type.ilike(f"%{room_type}%"))
        rooms = s.scalars(q).all()
        lines = [f"{r.room_type} (Room {r.room_number}): ${r.price_per_night}/night"
                 for r in rooms]
        return "Prices:\n" + "\n".join(lines)


@tool
def book_room(room_number: str, guest_name: str,
              check_in: str, check_out: str) -> str:
    """Book a specific room for a guest between check_in and check_out
    (both YYYY-MM-DD). Returns a confirmation message."""
    ci = _parse_date(check_in)
    co = _parse_date(check_out)
    if not ci or not co:
        return "Error: check_in and check_out must be YYYY-MM-DD."
    if co <= ci:
        return "Error: check_out must be after check_in."

    Session = get_sessionmaker(settings.database_url)
    with Session() as s:
        room = s.scalar(select(Room).where(Room.room_number == room_number))
        if not room:
            return f"Error: room {room_number} does not exist."
        if not room.available:
            return f"Error: room {room_number} is not available."

        booking = Booking(guest_name=guest_name, room_id=room.id,
                          check_in=ci, check_out=co)
        room.available = False
        s.add(booking)
        s.commit()
        return (f"Booked room {room_number} ({room.room_type}) for {guest_name} "
                f"from {ci} to {co}. Booking ID: {booking.id}.")


@tool
def cancel_booking(booking_id: int) -> str:
    """Cancel a booking by its ID and free the room."""
    Session = get_sessionmaker(settings.database_url)
    with Session() as s:
        booking = s.get(Booking, booking_id)
        if not booking:
            return f"Error: booking {booking_id} not found."
        room = s.get(Room, booking.room_id)
        if room:
            room.available = True
        s.delete(booking)
        s.commit()
        return f"Cancelled booking {booking_id}. Room {room.room_number} is now available."


@tool
def booking_history(guest_name: Optional[str] = None) -> str:
    """List bookings, optionally filtered by guest_name."""
    Session = get_sessionmaker(settings.database_url)
    with Session() as s:
        q = select(Booking)
        bookings = s.scalars(q).all()
        if guest_name:
            bookings = [b for b in bookings if guest_name.lower() in b.guest_name.lower()]
        if not bookings:
            return "No bookings found."
        lines = []
        for b in bookings:
            room = s.get(Room, b.room_id)
            lines.append(
                f"ID {b.id} | {b.guest_name} | Room {room.room_number} "
                f"({room.room_type}) | {b.check_in} -> {b.check_out}"
            )
        return "Bookings:\n" + "\n".join(lines)


ALL_TOOLS = [search_rooms, check_price, book_room, cancel_booking, booking_history]
