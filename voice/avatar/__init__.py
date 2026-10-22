"""Avatar engines: puppet (default) and optional CPU MuseTalk."""
from voice.avatar.base import AvatarClip, AvatarError, BaseAvatar, to_gif_bytes, to_png_bytes
from voice.avatar.engine import build_avatar, describe
from voice.avatar.puppet import PuppetAvatar

__all__ = [
    "AvatarClip",
    "AvatarError",
    "BaseAvatar",
    "PuppetAvatar",
    "build_avatar",
    "describe",
    "to_gif_bytes",
    "to_png_bytes",
]
