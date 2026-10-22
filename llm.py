"""Groq LLM client.

The project deliberately uses the Groq SDK directly (no OpenAI client and no
`langchain_openai`). Set `GROQ_API_KEY` in `.env`.

`qwen/qwen3.8-27b` is the default because it is fast, returns clean JSON when
asked, and is available on the current Groq account.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Sequence

from config import settings

logger = logging.getLogger(__name__)

_RETRYABLE = ("rate_limit", "429", "500", "502", "503", "504", "timeout", "connection")
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class LLMError(RuntimeError):
    """Raised when the Groq call fails after retries."""


@dataclass
class ChatResult:
    content: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)


class GroqLLM:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.groq_api_key
        self.model = model or settings.groq_model
        self.temperature = settings.groq_temperature if temperature is None else temperature
        self.max_tokens = max_tokens or settings.groq_max_tokens
        self.timeout = timeout or settings.groq_timeout_seconds
        self._client = None

    @property
    def client(self):
        if not self.api_key:
            raise LLMError("GROQ_API_KEY is not set in .env")
        if self._client is None:
            try:
                from groq import Groq
            except ImportError as exc:  # pragma: no cover - dependency error
                raise LLMError("The 'groq' package is not installed. Run: pip install groq") from exc
            self._client = Groq(api_key=self.api_key, timeout=self.timeout)
        return self._client

    def _create(self, messages: Sequence[dict[str, str]], *, json_mode: bool) -> ChatResult:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        for attempt in range(4):
            try:
                response = self.client.chat.completions.create(**kwargs)
                message = response.choices[0].message
                usage = response.usage.model_dump() if getattr(response, "usage", None) else {}
                return ChatResult(content=(message.content or "").strip(),
                                  model=self.model, usage=usage)
            except Exception as exc:  # noqa: BLE001 - normalise provider errors
                last_error = exc
                text = f"{type(exc).__name__}: {exc}".lower()
                retryable = any(token in text for token in _RETRYABLE)
                if attempt == 3 or not retryable:
                    break
                delay = 2 ** attempt
                logger.warning("Groq call failed (attempt %d), retrying in %ss: %s",
                               attempt + 1, delay, exc)
                time.sleep(delay)

        raise LLMError(f"Groq request failed: {last_error}") from last_error

    def chat(self, messages: Sequence[dict[str, str]], *, json_mode: bool = False) -> str:
        return self._create(messages, json_mode=json_mode).content

    def chat_json(self, messages: Sequence[dict[str, str]]) -> dict[str, Any]:
        raw = self._create(messages, json_mode=True).content
        cleaned = _FENCE_RE.sub("", raw).strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model did not return valid JSON: {raw[:300]!r}") from exc
        if not isinstance(parsed, dict):
            raise LLMError(f"Expected a JSON object, got {type(parsed).__name__}")
        return parsed

    def ping(self) -> dict[str, Any]:
        result = self._create(
            [{"role": "user", "content": "Reply with the single word OK."}],
            json_mode=False,
        )
        return {"ok": bool(result.content), "model": result.model, "reply": result.content[:40]}


_llm: GroqLLM | None = None
_lock = Lock()


def get_llm() -> GroqLLM:
    global _llm
    if _llm is None:
        with _lock:
            if _llm is None:
                _llm = GroqLLM()
    return _llm
