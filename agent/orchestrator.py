"""Grounded conversational orchestrator.

Flow per turn:
  1. If a booking is pending, handle yes/no/edits.
  2. If the user wants to book, extract a draft and ask for confirmation.
  3. Otherwise extract a structured `PropertyQueryPlan` with the LLM, run a
     parameterised read-only search, and ask the LLM to answer ONLY from those
     records. If the LLM is unavailable, fall back to a deterministic summary.
"""
from __future__ import annotations

import logging
import json
import re
import uuid
from datetime import date
from typing import Any

from agent import guardrails
from agent.context import ConversationState, store
from agent.prompts import (
    ANSWER_PROMPT,
    BOOKING_PROMPT,
    NO_MATCH_REPLY,
    PLAN_PROMPT,
    SYSTEM_PROMPT,
)
from llm import LLMError, get_llm
from property.query_plan import PropertyQueryPlan
from property.tools import (
    BookingConflict,
    BookingError,
    create_booking,
    room_details,
    search_properties,
)

logger = logging.getLogger(__name__)

_RESET_RE = re.compile(
    r"\b(start over|reset|new search|forget (?:it|everything|that)|clear (?:the )?(?:filters|search))\b",
    re.IGNORECASE,
)
_SORT_HINTS = (
    (re.compile(r"\bmost expensive\b", re.IGNORECASE), "rent_desc"),
    (re.compile(r"\bcheapest\b|\bleast expensive\b|\blowest rent\b", re.IGNORECASE), "rent_asc"),
    (re.compile(r"\blargest\b|\bbiggest\b|\bmost space\b", re.IGNORECASE), "size_desc"),
    (re.compile(r"\bnewest\b|\blatest\b", re.IGNORECASE), "newest"),
)
_SCALAR_FIELDS = (
    "city", "property_name", "property_type", "room_type",
    "min_rent", "max_rent", "min_size_sqm", "min_occupants",
    "available_from", "available_to",
)


def _sort_hint(message: str) -> str | None:
    for pattern, value in _SORT_HINTS:
        if pattern.search(message):
            return value
    return None


def _merge_plan(
    previous: PropertyQueryPlan | None,
    new: PropertyQueryPlan,
    message: str,
) -> PropertyQueryPlan:
    """Keep earlier constraints unless the user replaced or reset them.

    The LLM is asked to carry the previous plan forward, but small models
    sometimes drop filters on follow-ups. Merging here makes follow-ups
    deterministic: a turn like "which is cheapest?" can never broaden the search.
    """
    hint = _sort_hint(message)
    if previous is None or _RESET_RE.search(message or ""):
        if hint:
            new = new.model_copy(update={"sort_by": hint})
        return new

    data = previous.model_dump()
    for key in _SCALAR_FIELDS:
        value = getattr(new, key)
        if value is not None:
            data[key] = value
    if new.amenities:
        data["amenities"] = sorted(set(previous.amenities) | set(new.amenities))
    data["sort_by"] = hint or previous.sort_by
    data["limit"] = new.limit

    if data.get("min_rent") is not None and data.get("max_rent") is not None:
        if data["min_rent"] > data["max_rent"]:
            if new.max_rent is not None and new.min_rent is None:
                data["min_rent"] = None
            else:
                data["max_rent"] = None
    if data.get("available_from") and data.get("available_to"):
        if data["available_to"] <= data["available_from"]:
            data["available_to"] = None
    return PropertyQueryPlan(**data)


class Assistant:
    def __init__(self, llm=None) -> None:
        self._llm = llm

    @property
    def llm(self):
        return self._llm or get_llm()

    # -- public API --------------------------------------------------------
    def handle(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        state = store.get(session_id)
        message = (message or "").strip()
        if not message:
            return self._reply(state, "I didn't catch that. What are you looking for?", [])

        state.add("user", message)

        try:
            if state.pending_booking:
                return self._handle_pending(state, message)
            if guardrails.has_booking_intent(message):
                booking_response = self._start_booking(state, message)
                if booking_response is not None:
                    return booking_response
            return self._handle_search(state, message)
        except LLMError as exc:
            logger.warning("LLM unavailable: %s", exc)
            return self._reply(
                state,
                "I'm having trouble reaching the language model right now. "
                "Please try again in a moment.",
                [],
                error="llm_unavailable",
            )

    # -- search path -------------------------------------------------------
    def _handle_search(self, state: ConversationState, message: str) -> dict[str, Any]:
        plan = self._extract_plan(state, message)
        result = search_properties(plan)
        rooms = result["rooms"]

        state.last_plan = plan.model_dump(mode="json")
        state.last_rooms = rooms
        if rooms and state.selected_room_id not in {r["room_id"] for r in rooms}:
            state.selected_room_id = rooms[0]["room_id"]

        if not rooms:
            return self._reply(state, NO_MATCH_REPLY, [], plan=state.last_plan)

        selected = guardrails.pick_room(rooms, state.selected_room_id)
        if guardrails.ordinal_index(message) is not None:
            index = guardrails.ordinal_index(message)
            if index is not None and index < len(rooms):
                selected = rooms[index]
                state.selected_room_id = selected["room_id"]
        if "cheapest" in message.lower() or "least expensive" in message.lower():
            selected = guardrails.pick_cheapest(rooms)
            if selected:
                state.selected_room_id = selected["room_id"]

        records = rooms
        policy_question = guardrails.asks_about_policies(message)
        if policy_question and selected:
            details = room_details(selected["room_id"])
            if details:
                records = [details]

        if guardrails.is_specific_question(message) or policy_question:
            reply = self._answer(message, plan, records, rooms)
        else:
            noun = "room" if len(rooms) == 1 else "rooms"
            reply = f"I found {len(rooms)} matching {noun}. " + guardrails.format_rooms(rooms, limit=4)

        state.add("assistant", reply)
        return {
            "session_id": state.session_id,
            "reply": reply,
            "rooms": rooms,
            "selected_room_id": state.selected_room_id,
            "plan": state.last_plan,
            "pending_booking": state.pending_booking,
        }

    def _extract_plan(self, state: ConversationState, message: str) -> PropertyQueryPlan:
        conversation = "\n".join(f"{t.role}: {t.content}" for t in state.turns[-6:])
        summaries = [
            f"#{r['room_id']} {r['property_name']} {r['unit']} ${r['rent']:.0f} "
            f"{r['room_type']} {r['size_sqm']}sqm"
            for r in state.last_rooms[:10]
        ]
        prompt = PLAN_PROMPT.format(
            today=date.today().isoformat(),
            previous_plan=json.dumps(state.last_plan or {}, indent=2),
            current_results="\n".join(summaries) or "(none)",
            conversation=conversation,
            message=message,
        )
        schema_error = ""
        for _ in range(2):
            payload = self.llm.chat_json([
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt + schema_error},
            ])
            try:
                candidate = PropertyQueryPlan(**payload)
                previous = PropertyQueryPlan(**state.last_plan) if state.last_plan else None
                return _merge_plan(previous, candidate, message)
            except Exception as exc:  # noqa: BLE001 - Pydantic validation
                schema_error = f"\n\nYour previous JSON was invalid: {exc}. Fix it."
                logger.info("invalid plan, retrying: %s", exc)
        if state.last_plan:
            return PropertyQueryPlan(**state.last_plan)
        return PropertyQueryPlan()

    def _answer(
        self,
        question: str,
        plan: PropertyQueryPlan,
        records: list[dict[str, Any]],
        all_rooms: list[dict[str, Any]],
    ) -> str:
        try:
            text = self.llm.chat([
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": ANSWER_PROMPT.format(
                    today=date.today().isoformat(),
                    question=question,
                    count=len(records),
                    plan=json.dumps(plan.model_dump(mode="json"), indent=2),
                    records=json.dumps(records, indent=2, default=str),
                )},
            ])
            text = (text or "").strip()
            if text:
                issues = guardrails.grounding_issues(text, records)
                if not issues:
                    return text
                logger.warning("discarding ungrounded reply (%s): %s", issues, text[:200])
        except LLMError as exc:
            logger.warning("answer generation failed, using deterministic summary: %s", exc)
        if len(records) == 1 and records[0].get("policies") is not None:
            return guardrails.format_details(records[0])
        return guardrails.format_rooms(all_rooms, limit=4)

    # -- booking path ------------------------------------------------------
    def _start_booking(self, state: ConversationState, message: str) -> dict[str, Any] | None:
        if state.pending_booking:
            return None
        conversation = "\n".join(f"{t.role}: {t.content}" for t in state.turns[-6:])
        summaries = [
            f"#{r['room_id']} {r['property_name']} {r['unit']} {r['room_type']} "
            f"${r['rent']:.0f}/month"
            for r in state.last_rooms[:10]
        ]
        payload = self.llm.chat_json([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": BOOKING_PROMPT.format(
                today=date.today().isoformat(),
                results="\n".join(summaries) or "(none)",
                selected_room_id=state.selected_room_id,
                conversation=conversation,
                message=message,
            )},
        ])
        if not payload.get("wants_booking"):
            return None

        reference = (payload.get("reference") or "").lower()
        room_id = payload.get("room_id")
        if reference == "cheapest":
            cheapest = guardrails.pick_cheapest(state.last_rooms)
            room_id = cheapest["room_id"] if cheapest else None
        elif reference == "selected" and state.selected_room_id is not None:
            room_id = state.selected_room_id
        if room_id is None:
            room_id = state.selected_room_id
        if room_id is None and len(state.last_rooms) == 1:
            room_id = state.last_rooms[0]["room_id"]

        room = guardrails.pick_room(state.last_rooms, room_id) if room_id is not None else None
        if room is None:
            reply = (
                "I can help with that. Which room would you like to book? "
                "You can give me the room number from the results."
            )
            state.add("assistant", reply)
            return self._reply(state, reply, state.last_rooms)

        missing = []
        if not payload.get("guest_name"):
            missing.append("the guest's full name")
        if not payload.get("check_in"):
            missing.append("a move-in date")
        if not payload.get("check_out"):
            missing.append("a move-out date")
        if missing:
            reply = (
                f"I can prepare a booking for room {room_id} at "
                f"{room['property_name']}. I still need " + ", ".join(missing) + "."
            )
            state.add("assistant", reply)
            return self._reply(state, reply, state.last_rooms)

        token = uuid.uuid4().hex
        state.pending_booking = {
            "token": token,
            "room_id": room_id,
            "guest_name": payload["guest_name"].strip(),
            "check_in": payload["check_in"],
            "check_out": payload["check_out"],
            "property_name": room["property_name"],
            "rent": room["rent"],
        }
        reply = (
            f"Please confirm: book room {room_id} at {room['property_name']} "
            f"for {state.pending_booking['guest_name']}, from "
            f"{state.pending_booking['check_in']} to {state.pending_booking['check_out']}, "
            f"at ${room['rent']:.0f} per month. Reply yes to confirm."
        )
        state.add("assistant", reply)
        return self._reply(state, reply, state.last_rooms)

    def _handle_pending(self, state: ConversationState, message: str) -> dict[str, Any]:
        pending = state.pending_booking or {}
        if guardrails.is_negative(message):
            state.pending_booking = None
            reply = "No problem, I have not made a booking. Anything else I can help with?"
            state.add("assistant", reply)
            return self._reply(state, reply, state.last_rooms)

        if not guardrails.is_affirmative(message):
            reply = (
                "I have a booking waiting for your confirmation. "
                "Reply yes to confirm, or no to cancel."
            )
            state.add("assistant", reply)
            return self._reply(state, reply, state.last_rooms, pending_booking=pending)

        try:
            booking = create_booking(
                room_id=pending["room_id"],
                guest_name=pending["guest_name"],
                check_in=pending["check_in"],
                check_out=pending["check_out"],
                idempotency_key=f"{state.session_id}:{pending['token']}",
            )
        except BookingConflict as exc:
            state.pending_booking = None
            reply = f"Sorry, that room is no longer available: {exc}. Would you like another option?"
            state.add("assistant", reply)
            return self._reply(state, reply, state.last_rooms, error="booking_conflict")
        except BookingError as exc:
            state.pending_booking = None
            reply = f"I couldn't complete that booking: {exc}."
            state.add("assistant", reply)
            return self._reply(state, reply, state.last_rooms, error="booking_error")

        state.pending_booking = None
        reply = (
            f"Booked. Your booking id is {booking['booking_id']} for room "
            f"{booking['room_id']} at {pending['property_name']}, from "
            f"{booking['check_in']} to {booking['check_out']}. "
            "You'll receive the paperwork by email."
        )
        state.add("assistant", reply)
        return self._reply(state, reply, state.last_rooms, booking=booking)

    # -- helpers -----------------------------------------------------------
    def _reply(
        self,
        state: ConversationState,
        text: str,
        rooms: list[dict[str, Any]],
        *,
        plan: dict[str, Any] | None = None,
        pending_booking: dict[str, Any] | None = None,
        booking: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "session_id": state.session_id,
            "reply": text,
            "rooms": rooms,
            "selected_room_id": state.selected_room_id,
            "plan": plan if plan is not None else state.last_plan,
            "pending_booking": pending_booking if pending_booking is not None else state.pending_booking,
            "booking": booking,
            "error": error,
        }


assistant = Assistant()
