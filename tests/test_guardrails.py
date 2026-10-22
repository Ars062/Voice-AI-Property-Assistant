from __future__ import annotations

from agent import guardrails


def test_affirmative_and_negative():
    for text in ("yes", "Yes please.", "go ahead", "confirm", "sure"):
        assert guardrails.is_affirmative(text), text
    for text in ("no", "nope", "cancel", "no thanks", "don't"):
        assert guardrails.is_negative(text), text
    assert not guardrails.is_affirmative("no")
    assert not guardrails.is_negative("yes")


def test_booking_intent():
    assert guardrails.has_booking_intent("I want to book room 3")
    assert guardrails.has_booking_intent("can I reserve it")
    assert not guardrails.has_booking_intent("how much is the rent")


def test_ordinal_and_cheapest():
    rooms = [{"room_id": 3, "rent": 1650}, {"room_id": 9, "rent": 1050}]
    assert guardrails.ordinal_index("the second one") == 1
    assert guardrails.pick_cheapest(rooms)["room_id"] == 9
    assert guardrails.pick_room(rooms, 3)["room_id"] == 3
    assert guardrails.pick_room(rooms, 99) is None


def test_grounding_flags_unknown_numbers():
    rooms = [{"room_id": 4, "rent": 1720.0}]
    assert guardrails.grounding_issues("Room 4 costs $1720.", rooms) == []
    issues = guardrails.grounding_issues("Room 7 costs $999.", rooms)
    assert any("room 7" in issue for issue in issues)
    assert any("999" in issue for issue in issues)


def test_policy_question_detection():
    assert guardrails.asks_about_policies("are pets allowed?")
    assert guardrails.asks_about_policies("what is the deposit")
    assert not guardrails.asks_about_policies("how big is the balcony")
    assert not guardrails.asks_about_policies("2 bedroom pet friendly with parking")

def test_policy_deposit_is_grounded():
    rooms = [{
        "room_id": 3,
        "rent": 1650,
        "deposit": 1650,
        "policies": [{"type": "pets", "description": "Cats and small dogs allowed with a $300 deposit."}],
    }]
    assert guardrails.grounding_issues("Pets need a $300 deposit.", rooms) == []
    assert guardrails.grounding_issues("Pets need a $999 deposit.", rooms)
