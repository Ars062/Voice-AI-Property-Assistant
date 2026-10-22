"""Text-to-Speech using Kokoro (free, local, high quality)."""
from __future__ import annotations

import threading

from config import settings


class KokoroTTS:
    """Lazily-loaded Kokoro TTS. Returns raw 24kHz PCM audio bytes (WAV)."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._pipeline = None
        return cls._instance

    def _ensure(self):
        if self._pipeline is None:
            from kokoro import KPipeline

            # 'a' = American English; other codes: b=UK, etc.
            self._pipeline = KPipeline(lang_code="a")

    def synthesize(self, text: str) -> bytes:
        """Return WAV audio bytes for the given text."""
        self._ensure()
        import io
        import soundfile as sf

        audio_chunks = []
        for _, _, audio in self._pipeline(
            text, voice=settings.kokoro_voice, speed=1.0
        ):
            audio_chunks.append(audio)

        if not audio_chunks:
            return b""

        import numpy as np

        full = np.concatenate(audio_chunks)
        buf = io.BytesIO()
        sf.write(buf, full, 24000, format="WAV")
        return buf.getvalue()


tts = KokoroTTS()


def synthesize(text: str) -> bytes:
    return tts.synthesize(text)
