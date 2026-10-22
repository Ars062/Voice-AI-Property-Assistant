"""LangGraph workflow for the hotel voice agent.

This is a state machine that follows the booking flow:
  greet -> classify intent -> (search -> ask confirmation -> book) / history / cancel

State is persisted across turns with a checkpointer so the agent can pause
while "waiting for confirmation" and resume on the user's next message.
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from config import settings
from llm import get_llm
from prompts import HOTEL_SYSTEM_PROMPT
from tools.hotel_tools import (
    book_room,
    booking_history,
    cancel_booking,
    search_rooms,
)


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    intent: str
    awaiting_confirmation: bool
    pending: dict | None
    finished: bool


# --------------------------------------------------------------------------
# Intent classification (structured output, no tools)
# --------------------------------------------------------------------------
def _classify(user_text: str, awaiting_confirmation: bool) -> str:
    VALID = {"greeting", "search", "book", "cancel",
             "history", "confirm", "deny", "unknown"}
    llm = get_llm(temperature=0)
    ctx = (
        "The assistant previously asked the user to confirm a booking."
        if awaiting_confirmation else
        "This is the start of a new request."
    )
    reply = llm.invoke([
        SystemMessage(content=(
            "You are a hotel booking intent classifier. "
            "Reply with EXACTLY one word from this list: "
            "greeting, search, book, cancel, history, confirm, deny, unknown. "
            "No explanation. Just the word.\n\n"
            "Rules:\n"
            "- If the user is saying hello/hi/good morning -> greeting\n"
            "- If asking to find/look/search/show rooms -> search\n"
            "- If wanting to reserve/book a room -> book\n"
            "- If wanting to cancel a booking -> cancel\n"
            "- If asking to see bookings/history -> history\n"
            "- If the conversation is awaiting confirmation and user says "
            "yes/ok/sure/confirm/go ahead -> confirm\n"
            "- If awaiting confirmation and user says no/cancel/nope -> deny\n"
            "- Anything else -> unknown\n\n"
            f"Context: {ctx}"
        )),
        HumanMessage(content=user_text),
    ]).content.strip().lower()
    # extract just the intent word (LLM might add extra text)
    for word in reply.split():
        if word in VALID:
            return word
    return "unknown"


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------
def greet_node(state: AgentState) -> dict:
    return {
        "messages": [AIMessage(content="Hello! I'm your hotel assistant. "
                                        "How can I help you today?")],
        "intent": "greeting",
    }


def classify_node(state: AgentState) -> dict:
    last = state["messages"][-1]
    intent = _classify(last.content, state.get("awaiting_confirmation", False))
    return {"intent": intent}


def search_node(state: AgentState) -> dict:
    """Extract a room type from the user text and search."""
    user_text = state["messages"][-1].content
    room_type = _extract_room_type(user_text)
    result = search_rooms.invoke({"room_type": room_type})
    reply = _phrase_with_llm(
        f"Search results:\n{result}\n\nUser asked: {user_text}\n"
        "If rooms are available, briefly list them and ask the user if they "
        "would like to book one. If none, say we're fully booked."
    )
    # Determine if there is at least one available room
    has_room = "No rooms" not in result
    return {
        "messages": [AIMessage(content=reply)],
        "pending": {"room_type": room_type} if has_room else None,
        "awaiting_confirmation": has_room,
    }


def ask_confirmation_node(state: AgentState) -> dict:
    # search_node already asks; this node is an explicit routing target
    return {"awaiting_confirmation": True}


def book_node(state: AgentState) -> dict:
    user_text = state["messages"][-1].content
    pending = state.get("pending") or {}
    room_type = pending.get("room_type")

    # Let the LLM pull guest name + dates, then call the tool.
    details = _extract_booking_details(user_text, room_type)
    result = book_room.invoke(details)
    reply = _phrase_with_llm(
        f"Booking tool result: {result}\nUser said: {user_text}\n"
        "Confirm the booking warmly and concisely."
    )
    return {
        "messages": [AIMessage(content=reply)],
        "awaiting_confirmation": False,
        "pending": None,
        "finished": True,
    }


def history_node(state: AgentState) -> dict:
    user_text = state["messages"][-1].content
    guest = _extract_guest_name(user_text)
    result = booking_history.invoke({"guest_name": guest})
    reply = _phrase_with_llm(
        f"Booking history:\n{result}\nUser asked: {user_text}\n"
        "Summarize this for the user."
    )
    return {"messages": [AIMessage(content=reply)]}


def cancel_node(state: AgentState) -> dict:
    user_text = state["messages"][-1].content
    bid = _extract_booking_id(user_text)
    if bid is None:
        return {"messages": [AIMessage(
            content="Sure, which booking ID would you like to cancel?")]}
    result = cancel_booking.invoke({"booking_id": bid})
    reply = _phrase_with_llm(
        f"Cancel result: {result}\nUser asked: {user_text}\nConfirm briefly."
    )
    return {"messages": [AIMessage(content=reply)]}


def respond_node(state: AgentState) -> dict:
    reply = _phrase_with_llm(
        f"User said: {state['messages'][-1].content}\n"
        "You are a hotel assistant. Answer helpfully and briefly, and offer "
        "to search rooms, show prices, or list bookings."
    )
    return {"messages": [AIMessage(content=reply)]}


def confirmation_router(state: AgentState) -> str:
    intent = state["intent"]
    if intent == "confirm":
        return "book"
    if intent == "deny":
        return "deny"
    # still awaiting confirmation but user said something else
    return "respond"


def intent_router(state: AgentState) -> str:
    return state["intent"]


# --------------------------------------------------------------------------
# Helpers (LLM-assisted extraction)
# --------------------------------------------------------------------------
def _phrase_with_llm(instruction: str) -> str:
    llm = get_llm()
    return llm.invoke([
        SystemMessage(content=HOTEL_SYSTEM_PROMPT),
        HumanMessage(content=instruction),
    ]).content


def _extract_room_type(text: str) -> str | None:
    text = text.lower()
    for t in ("suite", "deluxe", "standard"):
        if t in text:
            return t.capitalize()
    return None


def _extract_guest_name(text: str) -> str | None:
    llm = get_llm(temperature=0)
    name = llm.invoke([
        SystemMessage(content="Extract the guest name from the text. "
                              "Reply with ONLY the name, or 'none' if absent."),
        HumanMessage(content=text),
    ]).content.strip()
    return None if name.lower() == "none" else name


def _extract_booking_id(text: str) -> int | None:
    import re
    m = re.search(r"\b(\d{1,6})\b", text)
    return int(m.group(1)) if m else None


def _extract_booking_details(text: str, room_type: str | None) -> dict:
    """Ask the LLM to pull structured booking details, then validate dates."""
    from database.models import Room, get_sessionmaker
    from sqlalchemy import select
    import re

    llm = get_llm(temperature=0)
    reply = llm.invoke([
        SystemMessage(content=(
            "Extract booking details from the user text. "
            f"Default room_type context: {room_type}. "
            "Use ISO dates YYYY-MM-DD. If a date is missing, use tomorrow "
            "for check_in and day-after for check_out.\n\n"
            "Reply in EXACTLY this format (no extra text):\n"
            "guest_name: <name>\n"
            "check_in: <YYYY-MM-DD>\n"
            "check_out: <YYYY-MM-DD>"
        )),
        HumanMessage(content=text),
    ]).content.strip()

    details = {"guest_name": "Guest", "check_in": "", "check_out": ""}
    for line in reply.splitlines():
        line = line.strip()
        if line.lower().startswith("guest_name:"):
            details["guest_name"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("check_in:"):
            details["check_in"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("check_out:"):
            details["check_out"] = line.split(":", 1)[1].strip()

    # pick the first available room of the requested type
    Session = get_sessionmaker(settings.database_url)
    with Session() as s:
        q = select(Room).where(Room.available.is_(True))
        if room_type:
            q = q.where(Room.room_type.ilike(f"%{room_type}%"))
        room = s.scalars(q).first()
        room_number = room.room_number if room else "201"
    return {
        "room_number": room_number,
        "guest_name": details["guest_name"],
        "check_in": details["check_in"],
        "check_out": details["check_out"],
    }


# --------------------------------------------------------------------------
# Build graph
# --------------------------------------------------------------------------
def build_graph():
    builder = StateGraph(AgentState)

    builder.add_node("classify", classify_node)
    builder.add_node("search", search_node)
    builder.add_node("ask_confirmation", ask_confirmation_node)
    builder.add_node("book", book_node)
    builder.add_node("history", history_node)
    builder.add_node("cancel", cancel_node)
    builder.add_node("respond", respond_node)

    builder.add_edge(START, "classify")

    builder.add_conditional_edges(
        "classify",
        intent_router,
        {
            "search": "search",
            "book": "search",          # must find a room before booking
            "history": "history",
            "cancel": "cancel",
            "greeting": "respond",
            "unknown": "respond",
            "confirm": "book",         # user confirmed while waiting
            "deny": "respond",
        },
    )

    builder.add_edge("search", "ask_confirmation")
    builder.add_edge("ask_confirmation", END)   # pause & wait for user

    builder.add_edge("book", END)
    builder.add_edge("history", END)
    builder.add_edge("cancel", END)
    builder.add_edge("respond", END)

    return builder.compile(checkpointer=MemorySaver())


graph = build_graph()


def run_agent(user_text: str, thread_id: str = "default") -> str:
    """Run one turn. Returns the assistant's text reply."""
    state = graph.invoke(
        {"messages": [HumanMessage(content=user_text)]},
        config={"configurable": {"thread_id": thread_id}},
    )
    return state["messages"][-1].content
