"""System prompt for the hotel voice agent."""
from __future__ import annotations

import pathlib

_PROMPT_PATH = pathlib.Path(__file__).parent / "hotel_agent.txt"

with open(_PROMPT_PATH, "r", encoding="utf-8") as _f:
    HOTEL_SYSTEM_PROMPT = _f.read()
