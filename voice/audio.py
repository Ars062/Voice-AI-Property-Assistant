"""Audio helpers: decode browser uploads, convert WAV, resample, measure level."""
from __future__ import annotations

import io
import tempfile
import uuid
import wave
from pathlib import Path

import numpy as np


class AudioError(RuntimeError):
    pass


def _decode_wav(data: bytes) -> tuple[np.ndarray, int] | None:
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError, ValueError):
        return None

    if width == 1:
        audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 3:
        buf = np.frombuffer(raw, dtype=np.uint8)
        buf = buf[: len(buf) // 3 * 3].reshape(-1, 3)
        ints = (
            buf[:, 0].astype(np.int32)
            | (buf[:, 1].astype(np.int32) << 8)
            | (buf[:, 2].astype(np.int32) << 16)
        )
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        audio = ints.astype(np.float32) / float(1 << 23)
    elif width == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / float(1 << 31)
    else:
        return None

    if channels > 1 and audio.size:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(audio, dtype=np.float32), int(rate)


def _decode_with_av(data: bytes, sample_rate: int = 16000) -> tuple[np.ndarray, int]:
    try:
        from faster_whisper.audio import decode_audio
    except Exception as exc:  # pragma: no cover - dependency guard
        raise AudioError(f"cannot decode audio: {exc}") from exc

    tmp = Path(tempfile.gettempdir()) / f"voice-upload-{uuid.uuid4().hex}.bin"
    try:
        tmp.write_bytes(data)
        audio = decode_audio(str(tmp), sampling_rate=sample_rate)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return np.asarray(audio, dtype=np.float32), sample_rate


def to_float32(data: bytes, sample_rate: int = 16000) -> tuple[np.ndarray, int]:
    """Decode WAV or compressed audio (webm/opus/mp3) to mono float32."""
    if not data:
        raise AudioError("empty audio")
    decoded = _decode_wav(data)
    if decoded is not None:
        audio, rate = decoded
        if sample_rate and rate != sample_rate:
            audio = resample(audio, rate, sample_rate)
            rate = sample_rate
        return audio, rate
    return _decode_with_av(data, sample_rate)


def resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate or audio.size == 0:
        return np.asarray(audio, dtype=np.float32)
    n = audio.size
    target = max(1, int(round(n * dst_rate / src_rate)))
    x_old = np.linspace(0.0, n - 1.0, n, dtype=np.float64)
    x_new = np.linspace(0.0, n - 1.0, target, dtype=np.float64)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def float32_to_wav(audio: np.ndarray, sample_rate: int) -> bytes:
    clipped = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))


def duration_seconds(audio: np.ndarray, sample_rate: int) -> float:
    return float(audio.size) / float(max(1, sample_rate))
