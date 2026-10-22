"""Avatar engine contracts and helpers shared by puppet and MuseTalk."""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np


@dataclass
class AvatarClip:
    frames: list[np.ndarray] = field(default_factory=list)
    fps: int = 25
    width: int = 512
    height: int = 512

    def __len__(self) -> int:
        return len(self.frames)

    @property
    def duration(self) -> float:
        return len(self.frames) / float(max(1, self.fps))


class AvatarError(RuntimeError):
    pass


class BaseAvatar:
    name = "base"

    def __init__(self, width: int = 512, height: int = 512) -> None:
        self.width = width
        self.height = height

    def is_ready(self) -> bool:
        return True

    def reason(self) -> str:
        return ""

    def render(self, audio: np.ndarray, sample_rate: int, fps: int = 25) -> AvatarClip:
        raise NotImplementedError

    def idle_frame(self, blinking: bool = False) -> np.ndarray:
        raise NotImplementedError

    def warmup(self) -> None:
        return None


def to_gif_bytes(clip: AvatarClip, max_width: int = 384) -> bytes:
    """Encode frames as a looping GIF (small enough for a JSON/base64 response)."""
    if not clip.frames:
        return b""
    from PIL import Image

    frames = []
    step = max(1, clip.width // max_width) if clip.width > max_width else 1
    for frame in clip.frames:
        image = Image.fromarray(np.asarray(frame, dtype=np.uint8), mode="RGB")
        if step > 1:
            image = image.resize(
                (max(1, image.width // step), max(1, image.height // step)),
                Image.LANCZOS,
            )
        frames.append(image.convert("P", palette=Image.ADAPTIVE, colors=128))

    buf = io.BytesIO()
    delay = max(20, int(round(1000.0 / max(1, clip.fps))))
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=delay,
        loop=0,
        optimize=True,
    )
    return buf.getvalue()


def to_png_bytes(frame: np.ndarray) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(np.asarray(frame, dtype=np.uint8), mode="RGB").save(buf, format="PNG")
    return buf.getvalue()
