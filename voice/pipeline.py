"""End-to-end voice turn: audio -> text -> grounded answer -> speech -> avatar."""
from __future__ import annotations

import base64
import logging
import threading
from typing import Any

import numpy as np

from agent.orchestrator import Assistant, assistant as default_assistant
from config import settings
from voice import audio as audio_utils
from voice.avatar.base import AvatarError, to_gif_bytes
from voice.avatar.engine import build_avatar
from voice.stt import SpeechToText, STTError, get_stt
from voice.tts import TTSError, get_tts

logger = logging.getLogger(__name__)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class VoicePipeline:
    def __init__(
        self,
        *,
        stt: SpeechToText | None = None,
        assistant: Assistant | None = None,
        avatar_kind: str | None = None,
    ) -> None:
        self._stt = stt
        self._assistant = assistant or default_assistant
        self._avatar_kind = avatar_kind
        self._avatar = None
        self._avatar_error = ""
        self._avatar_lock = threading.Lock()

    # -- lazy components ---------------------------------------------------
    @property
    def stt(self) -> SpeechToText:
        if self._stt is None:
            self._stt = get_stt()
        return self._stt

    @property
    def assistant(self) -> Assistant:
        return self._assistant

    def avatar(self):
        if self._avatar is not None:
            return self._avatar
        if self._avatar_error:
            return None
        with self._avatar_lock:
            if self._avatar is None and not self._avatar_error:
                try:
                    self._avatar = build_avatar(self._avatar_kind)
                except Exception as exc:  # noqa: BLE001 - avatar is optional
                    self._avatar_error = str(exc)
                    logger.warning("avatar disabled: %s", exc)
        return self._avatar

    # -- entry points ------------------------------------------------------
    def process_text(
        self,
        text: str,
        session_id: str | None = None,
        *,
        speak: bool = True,
        with_avatar: bool = True,
    ) -> dict[str, Any]:
        result = self.assistant.handle(text, session_id=session_id)
        return self._finish(result, speak=speak, with_avatar=with_avatar)

    def process_audio(
        self,
        data: bytes,
        session_id: str | None = None,
        *,
        speak: bool = True,
        with_avatar: bool = True,
    ) -> dict[str, Any]:
        try:
            transcript = self.stt.transcribe(data)
        except STTError as exc:
            logger.warning("stt failed: %s", exc)
            return {
                "session_id": session_id,
                "transcript": "",
                "reply": "Sorry, I couldn't transcribe that. Please try again.",
                "rooms": [],
                "error": "stt_failed",
            }
        if not transcript:
            return {
                "session_id": session_id,
                "transcript": "",
                "reply": "I didn't hear anything. Hold the button and speak again.",
                "rooms": [],
                "error": "empty_transcript",
            }
        result = self.assistant.handle(transcript, session_id=session_id)
        result["transcript"] = transcript
        return self._finish(result, speak=speak, with_avatar=with_avatar)

    # -- shared output -----------------------------------------------------
    def _finish(self, result: dict[str, Any], *, speak: bool, with_avatar: bool) -> dict[str, Any]:
        result.setdefault("audio", None)
        result.setdefault("avatar", None)
        if not speak:
            return result

        reply = result.get("reply") or ""
        try:
            tts = get_tts().synthesize(reply)
        except TTSError as exc:
            logger.warning("tts failed: %s", exc)
            result["speech_error"] = str(exc)
            return result

        result["audio"] = {
            "wav_b64": _b64(tts.audio),
            "sample_rate": tts.sample_rate,
            "provider": tts.provider,
        }
        if not with_avatar:
            return result

        engine = self.avatar()
        if engine is None:
            result["avatar"] = {"available": False, "reason": self._avatar_error}
            return result

        try:
            pcm, rate = audio_utils.to_float32(tts.audio, sample_rate=tts.sample_rate)
            max_samples = int(settings.avatar_max_seconds * rate)
            if pcm.size > max_samples:
                pcm = pcm[:max_samples]
            clip = engine.render(pcm, rate, fps=settings.avatar_fps)
            gif = to_gif_bytes(clip, max_width=settings.avatar_max_width)
            result["avatar"] = {
                "available": bool(gif),
                "engine": engine.name,
                "gif_b64": _b64(gif),
                "fps": clip.fps,
                "frames": len(clip),
            }
        except (AvatarError, ValueError, RuntimeError) as exc:
            logger.warning("avatar render failed: %s", exc)
            result["avatar"] = {"available": False, "engine": engine.name, "reason": str(exc)}
        return result


_pipeline: VoicePipeline | None = None
_lock = threading.Lock()


def get_pipeline() -> VoicePipeline:
    global _pipeline
    if _pipeline is None:
        with _lock:
            if _pipeline is None:
                _pipeline = VoicePipeline()
    return _pipeline
