"""CPU 'puppet' avatar: amplitude-driven mouth over a generated portrait.

No neural network and no weights: a pre-rendered strip of mouth shapes is
composited per video frame from the smoothed RMS of that frame's audio slice.
This is the default engine because it renders hundreds of frames per second.
"""
from __future__ import annotations

import math
import os
import threading

import numpy as np

from config import settings
from voice.avatar.base import AvatarClip, BaseAvatar


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _draw_portrait(width: int, height: int) -> np.ndarray:
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.new("RGB", (width, height), (18, 26, 36))
    px = img.load()
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(_lerp(34, 10, t))
        g = int(_lerp(50, 16, t))
        b = int(_lerp(70, 24, t))
        for x in range(width):
            px[x, y] = (r, g, b)

    glow = Image.new("RGB", (width, height), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((width * 0.18, height * 0.06, width * 0.82, height * 0.74),
               fill=(70, 96, 124))
    glow = glow.filter(ImageFilter.GaussianBlur(width * 0.12))
    img = Image.blend(img, glow, 0.35)

    d = ImageDraw.Draw(img, "RGBA")
    skin = (232, 189, 148)
    skin_shadow = (206, 160, 122)
    hair = (44, 34, 32)
    shirt = (46, 66, 92)

    d.ellipse((width * 0.10, height * 0.84, width * 0.90, height * 1.30), fill=shirt)
    d.ellipse((width * 0.38, height * 0.66, width * 0.62, height * 0.86), fill=skin_shadow)
    d.ellipse((width * 0.285, height * 0.215, width * 0.715, height * 0.780), fill=skin)
    d.ellipse((width * 0.265, height * 0.145, width * 0.735, height * 0.500), fill=hair)
    d.ellipse((width * 0.285, height * 0.215, width * 0.715, height * 0.560), fill=skin)
    d.ellipse((width * 0.255, height * 0.195, width * 0.400, height * 0.520), fill=hair)
    d.ellipse((width * 0.600, height * 0.195, width * 0.745, height * 0.520), fill=hair)
    d.ellipse((width * 0.245, height * 0.270, width * 0.300, height * 0.400), fill=skin_shadow)
    d.ellipse((width * 0.700, height * 0.270, width * 0.755, height * 0.400), fill=skin_shadow)

    for cx in (width * 0.402, width * 0.598):
        d.ellipse((cx - width * 0.062, height * 0.500, cx + width * 0.062, height * 0.566),
                  fill=(250, 248, 244))
        d.ellipse((cx - width * 0.024, height * 0.508, cx + width * 0.024, height * 0.558),
                  fill=(74, 104, 112))
        d.ellipse((cx - width * 0.011, height * 0.518, cx + width * 0.011, height * 0.548),
                  fill=(18, 20, 22))
        d.ellipse((cx - width * 0.017, height * 0.513, cx - width * 0.004, height * 0.528),
                  fill=(255, 255, 255, 220))
        d.arc((cx - width * 0.078, height * 0.448, cx + width * 0.078, height * 0.500),
              start=200, end=340, fill=(52, 40, 36), width=max(3, width // 110))

    d.line((width * 0.500, height * 0.545, width * 0.482, height * 0.622,
            width * 0.512, height * 0.636),
           fill=skin_shadow, width=max(3, width // 120), joint="curve")

    d.ellipse((width * 0.352, height * 0.688, width * 0.648, height * 0.760),
              fill=(178, 92, 92))
    d.line((width * 0.376, height * 0.722, width * 0.624, height * 0.722),
           fill=(120, 52, 56), width=max(2, width // 170))
    return np.asarray(img, dtype=np.uint8)


class PuppetAvatar(BaseAvatar):
    name = "puppet"

    def __init__(self, width: int = 512, height: int = 512, portrait: str | None = None) -> None:
        super().__init__(width, height)
        self.portrait_path = str(settings.abs_path(portrait or settings.avatar_portrait))
        self._lock = threading.Lock()
        self._base = self._load_base()
        self._mouth_box = (
            int(self.width * 0.383),
            int(self.height * 0.673),
            int(self.width * 0.234),
            int(self.height * 0.115),
        )
        self._levels, self._blink = self._build_props()

    def _load_base(self) -> np.ndarray:
        from PIL import Image

        if not os.path.exists(self.portrait_path):
            os.makedirs(os.path.dirname(self.portrait_path) or ".", exist_ok=True)
            base = _draw_portrait(self.width, self.height)
            Image.fromarray(base, mode="RGB").save(self.portrait_path)
            return base
        image = Image.open(self.portrait_path).convert("RGB").resize((self.width, self.height))
        return np.asarray(image, dtype=np.uint8)

    def _build_props(self) -> tuple[list[np.ndarray], np.ndarray]:
        from PIL import Image, ImageDraw

        mx, my, mw, mh = self._mouth_box
        skin = (232, 189, 148)
        lip = (150, 74, 78)
        cavity = (72, 24, 30)
        teeth = (246, 242, 236)

        levels: list[np.ndarray] = []
        count = 8
        for index in range(count + 1):
            opening = int(3 + index * (mh * 0.62) / count)
            canvas = self._base[my:my + mh, mx:mx + mw].copy()
            canvas[:] = skin
            pil = Image.fromarray(canvas)
            draw = ImageDraw.Draw(pil)
            draw.ellipse((mw * 0.10, mh * 0.22, mw * 0.90, mh * 0.30), fill=lip)
            top = mh * 0.36
            draw.rounded_rectangle(
                (mw * 0.15, top, mw * 0.85, top + opening),
                radius=max(4, opening // 3),
                fill=cavity,
            )
            draw.rectangle((mw * 0.19, top + 2, mw * 0.81, top + max(4, opening * 0.35)), fill=teeth)
            levels.append(np.asarray(pil, dtype=np.uint8))

        blink_image = self._base.copy()
        pil = Image.fromarray(blink_image)
        draw = ImageDraw.Draw(pil)
        for cx in (self.width * 0.402, self.width * 0.598):
            draw.ellipse(
                (cx - self.width * 0.070, self.height * 0.492,
                 cx + self.width * 0.070, self.height * 0.574),
                fill=skin,
            )
            draw.arc(
                (cx - self.width * 0.070, self.height * 0.482,
                 cx + self.width * 0.070, self.height * 0.566),
                start=15, end=165, fill=(168, 118, 96), width=max(3, self.width // 120),
            )
        return levels, np.asarray(pil, dtype=np.uint8)

    def render(self, audio: np.ndarray, sample_rate: int, fps: int = 25) -> AvatarClip:
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if audio.size == 0 or sample_rate <= 0:
            return AvatarClip([self._base.copy()], fps, self.width, self.height)

        duration = audio.size / float(sample_rate)
        n_frames = max(1, int(round(duration * fps)))
        overall = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64)))) if audio.size else 0.0
        gate = max(0.006, overall * 0.14)
        span = max(0.02, overall)
        mx, my, mw, mh = self._mouth_box
        slices = np.array_split(audio, n_frames) if n_frames > 1 else [audio]

        frames: list[np.ndarray] = []
        level = 0.0
        last = len(self._levels) - 1
        for chunk in slices:
            chunk_rms = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64)))) if chunk.size else 0.0
            target = 0.0 if chunk_rms < gate else min(1.0, (chunk_rms - gate) / span)
            level += (target - level) * (0.60 if target > level else 0.12)
            index = int(round(level * last))
            canvas = self._base.copy()
            canvas[my:my + mh, mx:mx + mw] = self._levels[index]
            frames.append(canvas)
        return AvatarClip(frames, fps, self.width, self.height)

    def idle_frame(self, blinking: bool = False) -> np.ndarray:
        if blinking:
            return self._blink.copy()
        dy = int(round(1.5 * math.sin(1.1)))
        return np.roll(self._base, dy, axis=0)
