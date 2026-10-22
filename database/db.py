"""Database session management and seed data."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from database.models import Base, Booking, Room, get_engine, get_sessionmaker
from config import settings


def init_db(url: str | None = None) -> None:
    """Create tables."""
    url = url or settings.database_url
    engine = get_engine(url)
    Base.metadata.create_all(engine)


def seed_db(url: str | None = None) -> None:
    """Populate rooms + a sample booking if empty."""
    url = url or settings.database_url
    Session = get_sessionmaker(url)
    with Session() as s:
        if s.scalar(select(Room)) is not None:
            return

        rooms = [
            Room(room_number="101", room_type="Standard", price_per_night=80, available=True),
            Room(room_number="201", room_type="Deluxe", price_per_night=150, available=True),
            Room(room_number="202", room_type="Deluxe", price_per_night=150, available=True),
            Room(room_number="301", room_type="Suite", price_per_night=300, available=True),
            Room(room_number="302", room_type="Suite", price_per_night=320, available=False),
        ]
        s.add_all(rooms)
        s.commit()

        # a pre-existing booking to make booking_history non-empty
        deluxe = s.scalar(select(Room).where(Room.room_number == "201"))
        deluxe.available = False
        s.add(
            Booking(
                guest_name="Walk-in Guest",
                room_id=deluxe.id,
                check_in=date.today() + timedelta(days=5),
                check_out=date.today() + timedelta(days=7),
            )
        )
        s.commit()


def get_session():
    """Yield a session (context managed by caller)."""
    Session = get_sessionmaker(settings.database_url)
    return Session()
