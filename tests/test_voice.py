from __future__ import annotations

import numpy as np

from voice.audio import duration_seconds, float32_to_wav, resample, rms, to_float32
from voice.avatar.base import to_gif_bytes
from voice.avatar.puppet import PuppetAvatar


def test_wav_roundtrip():
    rate = 16000
    t = np.linspace(0, 1.0, rate, endpoint=False, dtype=np.float32)
    tone = (0.25 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    wav = float32_to_wav(tone, rate)
    decoded, decoded_rate = to_float32(wav, sample_rate=rate)
    assert decoded_rate == rate
    assert abs(duration_seconds(decoded, rate) - 1.0) < 0.01
    assert abs(rms(decoded) - rms(tone)) < 0.01


def test_resample_preserves_duration():
    rate = 22050
    tone = np.zeros(rate, dtype=np.float32)
    out = resample(tone, rate, 16000)
    assert abs(out.size - 16000) <= 1


def test_puppet_renders_expected_frames(tmp_path):
    avatar = PuppetAvatar(256, 256, portrait=str(tmp_path / "portrait.png"))
    rate = 16000
    audio = (0.2 * np.sin(2 * np.pi * 180 * np.arange(rate, dtype=np.float32) / rate))
    clip = avatar.render(audio, rate, fps=12)
    assert len(clip.frames) == 12
    assert clip.frames[0].shape == (256, 256, 3)
    assert clip.frames[0].dtype == np.uint8
    assert not np.array_equal(clip.frames[0], clip.frames[-1])


def test_puppet_idle_frame(tmp_path):
    avatar = PuppetAvatar(256, 256, portrait=str(tmp_path / "portrait.png"))
    idle = avatar.idle_frame(blinking=False)
    blink = avatar.idle_frame(blinking=True)
    assert idle.shape == blink.shape == (256, 256, 3)
    assert not np.array_equal(idle, blink)


def test_gif_encoding(tmp_path):
    avatar = PuppetAvatar(256, 256, portrait=str(tmp_path / "portrait.png"))
    audio = np.zeros(8000, dtype=np.float32)
    clip = avatar.render(audio, 16000, fps=8)
    data = to_gif_bytes(clip, max_width=128)
    assert data.startswith(b"GIF8")
    assert len(data) > 100
