"""Central configuration loaded from the project `.env` (Groq + PostgreSQL)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM: Groq only ---------------------------------------------------
    llm_provider: str = "groq"
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.8-27b"
    groq_temperature: float = 0.1
    groq_max_tokens: int = 900
    groq_timeout_seconds: float = 60.0

    # --- PostgreSQL -------------------------------------------------------
    postgres_admin_user: str = "postgres"
    postgres_admin_password: str = "postgres"
    postgres_db: str = "voice_property"
    postgres_port: int = 5433

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5433/voice_property"
    database_readonly_url: str = (
        "postgresql+psycopg://voice_readonly:voice_readonly_pw@localhost:5433/voice_property"
    )

    # --- Query safety -----------------------------------------------------
    query_max_rows: int = 25
    query_timeout_seconds: int = 10
    query_statement_timeout_ms: int = 8000

    # --- Voice: STT -------------------------------------------------------
    whisper_model_size: str = "base"
    whisper_compute_type: str = "int8"
    whisper_device: str = "cpu"
    whisper_model_dir: str = "models/whisper"

    # --- Voice: TTS -------------------------------------------------------
    tts_provider: str = "auto"
    tts_piper_voice: str = "en_US-lessac-medium"
    tts_piper_model_dir: str = "models/piper"
    tts_sapi_voice: str = "Microsoft David Desktop"

    # --- Avatar -----------------------------------------------------------
    avatar_engine: str = "auto"
    avatar_musetalk_dir: str = "models/musetalk"
    avatar_musetalk_bbox: str = ""
    avatar_portrait: str = "assets/portrait.png"
    avatar_fps: int = 25
    avatar_cpu_render_fps: int = 6
    avatar_cpu_threads: int = 0
    avatar_cpu_quantize: bool = False
    avatar_batch_size: int = 2
    avatar_max_seconds: int = 15
    avatar_max_width: int = 384

    # --- Server -----------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    # --- Derived helpers --------------------------------------------------
    @property
    def root(self) -> Path:
        return ROOT

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    def abs_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else ROOT / path


settings = Settings()
