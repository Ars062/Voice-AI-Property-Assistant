"""Speech-to-Text using Faster Whisper (free, local)."""
from __future__ import annotations

import threading

from config import settings


class WhisperSTT:
    """Thin wrapper around faster-whisper. Loads the model lazily/once."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._model = None
        return cls._instance

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import Whisper

            self._model = Whisper(settings.whisper_model_size)

    def transcribe(self, audio_path: str) -> str:
        self._ensure_model()
        segments, _ = self._model.transcribe(audio_path, beam_size=5)
        return " ".join(seg.text for seg in segments).strip()


stt = WhisperSTT()


def transcribe_file(audio_path: str) -> str:
    return stt.transcribe(audio_path)
