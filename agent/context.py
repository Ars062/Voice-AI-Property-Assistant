"""Conversation state and in-memory session store."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Turn:
    role: str
    content: str

    def as_message(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class ConversationState:
    session_id: str
    turns: list[Turn] = field(default_factory=list)
    last_plan: dict[str, Any] | None = None
    last_rooms: list[dict[str, Any]] = field(default_factory=list)
    selected_room_id: int | None = None
    pending_booking: dict[str, Any] | None = None
    last_updated: float = field(default_factory=time.time)

    def add(self, role: str, content: str) -> None:
        self.turns.append(Turn(role=role, content=content))
        self.turns = self.turns[-12:]
        self.last_updated = time.time()

    def recent(self, limit: int = 6) -> list[dict[str, str]]:
        return [t.as_message() for t in self.turns[-limit:]]

    def clear_results(self) -> None:
        self.last_rooms = []
        self.selected_room_id = None


class SessionStore:
    def __init__(self, ttl_seconds: int = 7200, max_sessions: int = 500) -> None:
        self._states: dict[str, ConversationState] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max = max_sessions

    def get(self, session_id: str | None = None) -> ConversationState:
        sid = session_id or uuid.uuid4().hex
        with self._lock:
            self._evict()
            state = self._states.get(sid)
            if state is None:
                state = ConversationState(session_id=sid)
                self._states[sid] = state
            return state

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._states.pop(session_id, None)

    def _evict(self) -> None:
        now = time.time()
        expired = [k for k, s in self._states.items() if now - s.last_updated > self._ttl]
        for key in expired:
            self._states.pop(key, None)
        if len(self._states) > self._max:
            oldest = sorted(self._states.items(), key=lambda kv: kv[1].last_updated)
            for key, _ in oldest[: len(self._states) - self._max]:
                self._states.pop(key, None)


store = SessionStore()
