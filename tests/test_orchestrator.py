from __future__ import annotations

import pytest
from sqlalchemy import text

from agent.orchestrator import Assistant
from database.db import session
from property.tools import BookingConflict, create_booking
from tests.helpers import ScriptedLLM, plan_from_prompt

BOOKING = {
    "wants_booking": True,
    "room_id": None,
    "guest_name": "Test Guest",
    "check_in": "2030-04-01",
    "check_out": "2030-09-01",
    "reference": "cheapest",
}


def _cleanup_guest(name: str) -> None:
    with session() as db:
        db.execute(text("DELETE FROM bookings WHERE guest_name = :name"), {"name": name})


@pytest.fixture(autouse=True)
def _clean_test_guest(db_required):
    yield
    _cleanup_guest("Test Guest")


def test_search_turn_returns_grounded_rooms(db_required):
    llm = ScriptedLLM(plan_fn=plan_from_prompt, answer="Room 4 at Maple Court is $1720.")
    result = Assistant(llm=llm).handle("2 bedroom pet friendly in Austin", session_id="t-search")
    assert result["reply"]
    assert {room["room_id"] for room in result["rooms"]} == {4, 11}


def test_follow_up_cheapest_keeps_filters(db_required):
    llm = ScriptedLLM(plan_fn=plan_from_prompt)
    assistant = Assistant(llm=llm)
    first = assistant.handle("2 bedroom pet friendly in Austin", session_id="t-follow")
    assert {room["room_id"] for room in first["rooms"]} == {4, 11}
    result = assistant.handle("which is the cheapest?", session_id="t-follow")
    assert result["plan"]["sort_by"] == "rent_asc"
    assert result["plan"]["room_type"] == "2 bedroom"
    assert result["plan"]["amenities"] == ["pet_friendly"]
    assert {room["room_id"] for room in result["rooms"]} == {4, 11}
    assert result["rooms"][0]["room_id"] == 11


def test_follow_up_ignores_llm_dropped_filters(db_required):
    """The merge layer must keep filters even if the model omits them."""

    class ForgetfulLLM(ScriptedLLM):
        def chat_json(self, messages):
            prompt = messages[-1]["content"]
            if "property-search plan" in prompt and "PREVIOUS PLAN" in prompt:
                if "cheapest" in prompt.rsplit("USER:", 1)[-1].lower():
                    return {"sort_by": "rent_asc", "limit": 10}
            return super().chat_json(messages)

    llm = ForgetfulLLM(plan_fn=plan_from_prompt)
    assistant = Assistant(llm=llm)
    assistant.handle("2 bedroom pet friendly in Austin", session_id="t-drop")
    result = assistant.handle("which is cheapest?", session_id="t-drop")
    assert result["plan"]["room_type"] == "2 bedroom"
    assert result["plan"]["amenities"] == ["pet_friendly"]
    assert {room["room_id"] for room in result["rooms"]} == {4, 11}


def test_reset_clears_previous_filters(db_required):
    llm = ScriptedLLM(plan_fn=plan_from_prompt)
    assistant = Assistant(llm=llm)
    assistant.handle("2 bedroom pet friendly in Austin", session_id="t-reset")
    result = assistant.handle("start over", session_id="t-reset")
    assert result["plan"]["room_type"] is None
    assert result["plan"]["city"] is None


def test_no_match_turn(db_required):
    llm = ScriptedLLM(plan_fn=plan_from_prompt)
    result = Assistant(llm=llm).handle("anything in Atlantis?", session_id="t-none")
    assert result["rooms"] == []
    assert "couldn't find" in result["reply"].lower()


def test_booking_requires_confirmation_then_creates(db_required):
    llm = ScriptedLLM(plan_fn=plan_from_prompt, booking=BOOKING)
    assistant = Assistant(llm=llm)
    assistant.handle("2 bedroom pet friendly in Austin", session_id="t-book")
    draft = assistant.handle("book the cheapest one for Test Guest from 2030-04-01 "
                             "to 2030-09-01", session_id="t-book")
    assert draft["pending_booking"]["room_id"] == 11
    assert draft["booking"] is None

    confirmed = assistant.handle("yes", session_id="t-book")
    assert confirmed["booking"]["room_id"] == 11
    assert confirmed["booking"]["status"] == "confirmed"
    assert confirmed["pending_booking"] is None


def test_booking_can_be_cancelled(db_required):
    llm = ScriptedLLM(plan_fn=plan_from_prompt, booking=BOOKING)
    assistant = Assistant(llm=llm)
    assistant.handle("2 bedroom pet friendly in Austin", session_id="t-cancel")
    assistant.handle("book the cheapest one for Test Guest from 2030-04-01 "
                     "to 2030-09-01", session_id="t-cancel")
    result = assistant.handle("no thanks", session_id="t-cancel")
    assert result["pending_booking"] is None
    assert result["booking"] is None


def test_booking_missing_name_asks(db_required):
    payload = dict(BOOKING, guest_name=None)
    llm = ScriptedLLM(plan_fn=plan_from_prompt, booking=payload)
    assistant = Assistant(llm=llm)
    assistant.handle("2 bedroom pet friendly in Austin", session_id="t-missing")
    result = assistant.handle("book it", session_id="t-missing")
    assert result["pending_booking"] is None
    assert "name" in result["reply"].lower()


def test_idempotent_booking_returns_duplicate(db_required, admin_cleanup):
    key = "test:idempotent:001"
    admin_cleanup.append(key)
    first = create_booking(
        room_id=1, guest_name="Test Guest", check_in="2030-01-01",
        check_out="2030-02-01", idempotency_key=key,
    )
    second = create_booking(
        room_id=1, guest_name="Test Guest", check_in="2030-01-01",
        check_out="2030-02-01", idempotency_key=key,
    )
    assert first["booking_id"] == second["booking_id"]
    assert second["duplicate"] is True


def test_overlapping_booking_raises_conflict(db_required, admin_cleanup):
    keys = ["test:conflict:001", "test:conflict:002"]
    admin_cleanup.extend(keys)
    create_booking(
        room_id=1, guest_name="Test Guest", check_in="2030-03-01",
        check_out="2030-04-01", idempotency_key=keys[0],
    )
    with pytest.raises(BookingConflict):
        create_booking(
            room_id=1, guest_name="Test Guest", check_in="2030-03-15",
            check_out="2030-04-15", idempotency_key=keys[1],
        )


def test_back_to_back_booking_is_allowed(db_required, admin_cleanup):
    keys = ["test:adjacent:001", "test:adjacent:002"]
    admin_cleanup.extend(keys)
    create_booking(
        room_id=1, guest_name="Test Guest", check_in="2030-05-01",
        check_out="2030-06-01", idempotency_key=keys[0],
    )
    booking = create_booking(
        room_id=1, guest_name="Test Guest", check_in="2030-06-01",
        check_out="2030-07-01", idempotency_key=keys[1],
    )
    assert booking["check_in"] == "2030-06-01"

def test_deterministic_search_reply_counts_rooms(db_required):
    llm = ScriptedLLM(plan_fn=plan_from_prompt)
    result = Assistant(llm=llm).handle(
        "2 bedroom pet friendly in Austin", session_id="t-count"
    )
    assert "2 matching rooms" in result["reply"]
    assert "Room 4" in result["reply"] and "Room 11" in result["reply"]


def test_ungrounded_answer_is_replaced(db_required):
    llm = ScriptedLLM(
        plan_fn=plan_from_prompt,
        answer="Room 4 costs $9999 per month and is in Paris.",
    )
    assistant = Assistant(llm=llm)
    assistant.handle("2 bedroom pet friendly in Austin", session_id="t-ground")
    result = assistant.handle("which is the cheapest?", session_id="t-ground")
    assert "$9999" not in result["reply"]
    assert "Paris" not in result["reply"]
    assert "1450" in result["reply"]
