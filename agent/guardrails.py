"""Small deterministic helpers used by the orchestrator and its tests."""
from __future__ import annotations

import re
from typing import Any

_AFFIRMATIVE = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed",
    "correct", "please do", "go ahead", "do it", "book it", "reserve it",
    "i confirm", "yes please", "absolutely", "definitely",
}
_NEGATIVE = {
    "no", "nope", "nah", "don't", "dont", "cancel", "stop", "not now",
    "no thanks", "no thank you", "negative",
}

_BOOKING_RE = re.compile(
    r"\b(book|booking|reserve|reservation|rent it|i'?ll take|sign me up|apply for)\b",
    re.IGNORECASE,
)
_POLICY_RE = re.compile(
    r"\b(polic(?:y|ies)|smok\w*|deposit|lease|rules?|allowed|permitted|included)\b",
    re.IGNORECASE,
)
_ORDINAL_RE = re.compile(r"\b(first|second|third|fourth|fifth|last)\b", re.IGNORECASE)
_QUESTION_RE = re.compile(
    r"\?|^\s*(what|which|how|is|are|does|do|can|could|would|tell me|compare|why|when|where)\b",
    re.IGNORECASE,
)


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9' ]+", " ", (text or "").lower()).strip()


def is_affirmative(text: str) -> bool:
    cleaned = _normalise(text)
    if not cleaned:
        return False
    if cleaned in _AFFIRMATIVE:
        return True
    return cleaned.split()[0] in _AFFIRMATIVE and len(cleaned.split()) <= 4


def is_negative(text: str) -> bool:
    cleaned = _normalise(text)
    if not cleaned:
        return False
    if cleaned in _NEGATIVE:
        return True
    return cleaned.split()[0] in _NEGATIVE and len(cleaned.split()) <= 4


def has_booking_intent(text: str) -> bool:
    return bool(_BOOKING_RE.search(text or ""))


def asks_about_policies(text: str) -> bool:
    return bool(_POLICY_RE.search(text or ""))


def is_specific_question(text: str) -> bool:
    """True when the user asks about a result rather than issuing a new search."""
    return bool(_QUESTION_RE.search((text or "").strip()))


def ordinal_index(text: str) -> int | None:
    match = _ORDINAL_RE.search(text or "")
    if not match:
        return None
    return {
        "first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4,
    }.get(match.group(1).lower())


def pick_cheapest(rooms: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rooms:
        return None
    return min(rooms, key=lambda r: (r.get("rent") or 0, r.get("room_id") or 0))


def pick_room(rooms: list[dict[str, Any]], room_id: int | None) -> dict[str, Any] | None:
    if not rooms:
        return None
    if room_id is not None:
        for room in rooms:
            if room.get("room_id") == room_id:
                return room
        return None
    return rooms[0]


def format_rooms(rooms: list[dict[str, Any]], limit: int = 5) -> str:
    if not rooms:
        return "No matching rooms."
    lines = []
    for room in rooms[:limit]:
        size = f"{room['size_sqm']:.0f} sqm" if room.get("size_sqm") else "size not listed"
        amenities = ", ".join(room.get("amenities", [])[:4]) or "no listed amenities"
        lines.append(
            f"Room {room['room_id']} at {room['property_name']} ({room['unit']}): "
            f"{room['room_type']}, ${room['rent']:.0f} per month, {size}, "
            f"up to {room['max_occupants']} people, available from "
            f"{room['available_from']}. Amenities: {amenities}."
        )
    return " ".join(lines)


def format_details(record: dict[str, Any]) -> str:
    parts = [
        f"Room {record['room_id']} at {record.get('property_name') or 'the property'} "
        f"({record.get('unit', '?')}) is a {record.get('room_type', 'room')} for "
        f"${float(record.get('rent') or 0):.0f} per month"
    ]
    if record.get("deposit"):
        parts.append(f"with a ${float(record['deposit']):.0f} deposit")
    if record.get("size_sqm"):
        parts.append(f"and {float(record['size_sqm']):.0f} square meters")
    text = ", ".join(parts) + "."
    if record.get("amenities"):
        text += " Amenities: " + ", ".join(record["amenities"]) + "."
    policies = record.get("policies") or []
    if policies:
        text += " Policies: " + "; ".join(
            f"{policy.get('type')}: {str(policy.get('description') or '').rstrip('.')}"
            for policy in policies
        ) + "."
    return text


def grounding_issues(reply: str, rooms: list[dict[str, Any]]) -> list[str]:
    """Return prices/room ids mentioned in a reply that are absent from records.

    Used by tests as a guard against fabricated numbers. It is intentionally
    conservative: only flags explicit `$amount` and `room N` mentions.
    """
    issues: list[str] = []
    prices = {round(float(r["rent"])) for r in rooms if r.get("rent") is not None}
    prices |= {round(float(r.get("deposit") or 0)) for r in rooms}
    ids = {int(r["room_id"]) for r in rooms if r.get("room_id") is not None}

    money_re = re.compile(r"\$\s*([0-9][0-9,]*)")
    for room in rooms:
        for policy in room.get("policies") or []:
            for match in money_re.finditer(str(policy.get("description") or "")):
                prices.add(int(match.group(1).replace(",", "")))
        for match in money_re.finditer(str(room.get("description") or "")):
            prices.add(int(match.group(1).replace(",", "")))

    for match in money_re.finditer(reply or ""):
        value = int(match.group(1).replace(",", ""))
        if value not in prices:
            issues.append(f"unknown price ${value}")
    for match in re.finditer(r"\broom\s+(\d+)\b", reply or "", re.IGNORECASE):
        value = int(match.group(1))
        if value not in ids:
            issues.append(f"unknown room {value}")
    return issues
