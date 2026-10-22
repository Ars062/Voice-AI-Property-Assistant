"""Offline text-to-speech.

Providers:
  sapi  - Windows System.Speech via PowerShell (default; zero extra dependency)
  piper - Piper neural voice (optional: pip install -r requirements-piper.txt)

``auto`` picks Piper when its model file exists, otherwise SAPI.
"""
from __future__ import annotations

import io
import logging
import os
import platform
import subprocess
import tempfile
import wave

import numpy as np

from config import settings

logger = logging.getLogger(__name__)


class TTSError(RuntimeError):
    pass


class TTSResult:
    def __init__(self, audio: bytes, sample_rate: int, provider: str) -> None:
        self.audio = audio
        self.sample_rate = sample_rate
        self.provider = provider

    def pcm(self) -> np.ndarray:
        from voice.audio import to_float32

        audio, _ = to_float32(self.audio, sample_rate=self.sample_rate)
        return audio


class SapiTTS:
    name = "sapi"

    def __init__(self, voice: str = "") -> None:
        self.voice = voice or settings.tts_sapi_voice

    def available(self) -> bool:
        return platform.system() == "Windows"

    def synthesize(self, text: str) -> TTSResult:
        text = (text or "").strip()
        if not text:
            raise TTSError("nothing to speak")

        import json

        txt_fd, txt_path = tempfile.mkstemp(suffix=".txt")
        wav_fd, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(wav_fd)
        try:
            with os.fdopen(txt_fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            cfg = json.dumps({"txt": txt_path, "wav": wav_path, "voice": self.voice}).replace("'", "''")
            script = (
                "$params = '" + cfg + "' | ConvertFrom-Json\n"
                "Add-Type -AssemblyName System.Speech\n"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                "if ($params.voice) { try { $s.SelectVoice($params.voice) } catch {} }\n"
                "$s.Rate = 0\n"
                "$s.SetOutputToWaveFile($params.wav)\n"
                "$s.Speak((Get-Content -Raw -Encoding UTF8 $params.txt))\n"
                "$s.Dispose()\n"
            )
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True,
                timeout=120,
            )
            if proc.returncode != 0:
                raise TTSError(proc.stderr.decode(errors="replace")[-400:] or "SAPI failed")
            with open(wav_path, "rb") as handle:
                audio = handle.read()
            if not audio:
                raise TTSError("SAPI produced no audio")
        finally:
            for path in (txt_path, wav_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass

        with wave.open(io.BytesIO(audio), "rb") as wf:
            rate = wf.getframerate()
        return TTSResult(audio, rate, self.name)


class PiperTTS:
    name = "piper"

    def __init__(self, voice: str = "") -> None:
        self.voice = voice or settings.tts_piper_voice
        base = settings.abs_path(settings.tts_piper_model_dir)
        self.model_path = str(base / f"{self.voice}.onnx")
        self._voice_model = None

    def available(self) -> bool:
        if not os.path.exists(self.model_path):
            return False
        try:
            import piper  # noqa: F401
        except Exception:
            return False
        return True

    def _load(self):
        if self._voice_model is None:
            try:
                from piper import PiperVoice
            except Exception as exc:  # pragma: no cover
                raise TTSError(f"piper is not installed: {exc}") from exc
            self._voice_model = PiperVoice.load(self.model_path)
        return self._voice_model

    def synthesize(self, text: str) -> TTSResult:
        text = (text or "").strip()
        if not text:
            raise TTSError("nothing to speak")
        voice = self._load()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voice.synthesize_wav(text, wf)
        audio = buf.getvalue()
        with wave.open(io.BytesIO(audio), "rb") as wf:
            rate = wf.getframerate()
        return TTSResult(audio, rate, self.name)


_PROVIDERS = {"sapi": SapiTTS, "piper": PiperTTS}


def get_tts() -> SapiTTS | PiperTTS:
    choice = (settings.tts_provider or "auto").lower()
    if choice == "auto":
        piper = PiperTTS()
        if piper.available():
            logger.info("TTS: piper (%s)", piper.voice)
            return piper
        sapi = SapiTTS()
        if sapi.available():
            logger.info("TTS: Windows SAPI")
            return sapi
        raise TTSError("no TTS available: install piper-tts or run on Windows")
    cls = _PROVIDERS.get(choice)
    if cls is None:
        raise TTSError(f"unknown TTS_PROVIDER: {choice}")
    return cls()


def describe() -> dict[str, object]:
    piper = PiperTTS()
    sapi = SapiTTS()
    return {
        "configured": settings.tts_provider,
        "piper_available": piper.available(),
        "piper_model": piper.model_path,
        "sapi_available": sapi.available(),
    }


def synthesize(text: str) -> TTSResult:
    return get_tts().synthesize(text)


def synthesize_pcm(text: str) -> tuple[np.ndarray, int, str]:
    result = synthesize(text)
    return result.pcm(), result.sample_rate, result.provider
