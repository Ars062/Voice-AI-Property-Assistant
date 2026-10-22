"""Local CPU speech-to-text with faster-whisper (lazy loaded)."""
from __future__ import annotations

import logging
import threading

import numpy as np

from config import settings

logger = logging.getLogger(__name__)


class STTError(RuntimeError):
    pass


class SpeechToText:
    def __init__(self, model_size: str | None = None, device: str | None = None,
                 compute_type: str | None = None, download_root: str | None = None) -> None:
        self.model_size = model_size or settings.whisper_model_size
        self.device = device or settings.whisper_device
        self.compute_type = compute_type or settings.whisper_compute_type
        self.download_root = str(settings.abs_path(download_root or settings.whisper_model_dir))
        self._model = None
        self._lock = threading.Lock()

    @property
    def model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from faster_whisper import WhisperModel

                    logger.info("loading whisper %s on %s (%s)",
                                self.model_size, self.device, self.compute_type)
                    self._model = WhisperModel(
                        self.model_size,
                        device=self.device,
                        compute_type=self.compute_type,
                        download_root=self.download_root,
                    )
        return self._model

    def transcribe(self, source, language: str = "en") -> str:
        """Transcribe a path, bytes, or mono float32 numpy array."""
        if isinstance(source, (bytes, bytearray)):
            from voice.audio import to_float32

            audio, _ = to_float32(bytes(source), sample_rate=16000)
        elif isinstance(source, np.ndarray):
            audio = np.asarray(source, dtype=np.float32)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
        else:
            audio = str(source)

        try:
            segments, _info = self.model.transcribe(
                audio,
                language=language,
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        except Exception as exc:  # noqa: BLE001 - surfaced to API
            raise STTError(f"transcription failed: {exc}") from exc
        return text.strip()


_default: SpeechToText | None = None


def get_stt() -> SpeechToText:
    global _default
    if _default is None:
        _default = SpeechToText()
    return _default


def transcribe(source, language: str = "en") -> str:
    return get_stt().transcribe(source, language=language)
