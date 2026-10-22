"""Voice stack: local STT, TTS, avatar and the end-to-end pipeline."""
from voice.audio import (
    AudioError,
    duration_seconds,
    float32_to_wav,
    resample,
    rms,
    to_float32,
)
from voice.pipeline import VoicePipeline, get_pipeline
from voice.stt import STTError, SpeechToText, get_stt, transcribe
from voice.tts import TTSError, TTSResult, get_tts, synthesize, synthesize_pcm

__all__ = [
    "AudioError",
    "STTError",
    "SpeechToText",
    "TTSError",
    "TTSResult",
    "VoicePipeline",
    "duration_seconds",
    "float32_to_wav",
    "get_pipeline",
    "get_stt",
    "get_tts",
    "resample",
    "rms",
    "synthesize",
    "synthesize_pcm",
    "to_float32",
    "transcribe",
]
