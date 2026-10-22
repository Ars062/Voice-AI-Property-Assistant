from __future__ import annotations

import json


class ScriptedLLM:
    """Deterministic stand-in for GroqLLM used by orchestrator tests."""

    def __init__(self, plan=None, answer="Here are the matching rooms.", booking=None,
                 plan_fn=None) -> None:
        self.plan = plan if plan is not None else {}
        self.answer = answer
        self.booking = booking if booking is not None else {"wants_booking": False}
        self.plan_fn = plan_fn
        self.calls: list[str] = []

    def chat(self, messages):
        self.calls.append("chat")
        return self.answer

    def chat_json(self, messages):
        self.calls.append("json")
        prompt = messages[-1]["content"]
        if "property-search plan" in prompt:
            if self.plan_fn is not None:
                return self.plan_fn(prompt)
            return dict(self.plan)
        return dict(self.booking)


def user_line(prompt: str) -> str:
    return prompt.rsplit("USER:", 1)[-1].strip()


def plan_from_prompt(prompt: str) -> dict:
    """Tiny keyword planner so multi-turn tests stay readable."""
    message = user_line(prompt).lower()
    if "atlantis" in message:
        return {"city": "Atlantis", "limit": 10}
    if "cheapest" in message or "least expensive" in message:
        previous = prompt.split("PREVIOUS PLAN:", 1)[-1].split("CURRENT RESULTS", 1)[0].strip()
        try:
            plan = json.loads(previous)
        except json.JSONDecodeError:
            plan = {}
        plan["sort_by"] = "rent_asc"
        return plan
    if "2 bedroom" in message:
        return {"room_type": "2 bedroom", "max_rent": 1800,
                "amenities": ["pet_friendly"], "limit": 10}
    if "austin" in message:
        return {"city": "austin", "max_rent": 1500, "amenities": ["wifi"], "limit": 10}
    return {"limit": 10}
