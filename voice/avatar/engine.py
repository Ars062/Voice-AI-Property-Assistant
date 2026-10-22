"""Avatar engine selection (CPU-first)."""
from __future__ import annotations

import logging

from config import settings
from voice.avatar.base import BaseAvatar
from voice.avatar.puppet import PuppetAvatar

logger = logging.getLogger(__name__)


def build_avatar(kind: str | None = None) -> BaseAvatar:
    choice = (kind or settings.avatar_engine or "auto").lower()
    if choice in {"musetalk", "musetalk_cpu"}:
        try:
            from voice.avatar.musetalk_cpu import MuseTalkCPUAvatar
        except Exception as exc:  # noqa: BLE001 - torch/diffusers missing
            raise RuntimeError(f"musetalk engine unavailable: {exc}") from exc
        engine = MuseTalkCPUAvatar()
        if not engine.is_ready():
            raise RuntimeError(engine.reason())
        logger.info("avatar engine: musetalk_cpu (%s)", engine.weights_dir)
        return engine

    if choice == "auto":
        try:
            from voice.avatar.musetalk_cpu import MuseTalkCPUAvatar

            engine = MuseTalkCPUAvatar()
            if engine.is_ready():
                logger.info("avatar engine: musetalk_cpu")
                return engine
            logger.info("musetalk unavailable (%s); using puppet", engine.reason())
        except Exception as exc:  # noqa: BLE001
            logger.info("musetalk not installed (%s); using puppet", exc)
        return PuppetAvatar()

    if choice == "puppet":
        logger.info("avatar engine: puppet")
        return PuppetAvatar()

    raise ValueError(f"unknown AVATAR_ENGINE: {choice}")


def describe() -> dict[str, object]:
    info: dict[str, object] = {
        "configured": settings.avatar_engine,
        "cpu_render_fps": settings.avatar_cpu_render_fps,
        "fps": settings.avatar_fps,
    }
    try:
        from voice.avatar.musetalk_cpu import MuseTalkCPUAvatar

        engine = MuseTalkCPUAvatar()
        info["musetalk_ready"] = engine.is_ready()
        info["musetalk_reason"] = engine.reason()
    except Exception as exc:  # noqa: BLE001
        info["musetalk_ready"] = False
        info["musetalk_reason"] = str(exc)
    return info
