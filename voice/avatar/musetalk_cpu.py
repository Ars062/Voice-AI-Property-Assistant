"""MuseTalk 1.5 lip-sync ported to run on CPU.

The upstream inference core assumes CUDA. This module keeps the same maths
(whisper features -> MuseTalk UNet -> SD-VAE decode -> feathered paste) but:

  * selects CPU automatically and uses float32 there (float16 is GPU-only);
  * renders fewer unique frames (``AVATAR_CPU_RENDER_FPS``) and repeats them to
    the target frame rate, which is the single biggest CPU saving;
  * optionally applies int8 dynamic quantization to the UNet;
  * never imports triton or any CUDA-only kernel;
  * caps work with ``torch.set_num_threads`` if configured.

Weights layout (``AVATAR_MUSETALK_DIR``):
  musetalkV15/unet.pth + musetalkV15/musetalk.json
  sd-vae-ft-mse/{config.json,diffusion_pytorch_model.bin}
  whisper/{config.json,pytorch_model.bin,preprocessor_config.json}
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time

import numpy as np

from config import settings
from voice.avatar.base import AvatarClip, AvatarError, BaseAvatar

logger = logging.getLogger(__name__)

AUDIO_SR = 16000
AUDIO_FPS = 50
PAD_LEFT = 2
PAD_RIGHT = 2
REQUIRED = (
    ("musetalkV15", "unet.pth"),
    ("musetalkV15", "musetalk.json"),
    ("sd-vae-ft-mse", "config.json"),
    ("sd-vae-ft-mse", "diffusion_pytorch_model.bin"),
    ("whisper", "config.json"),
    ("whisper", "pytorch_model.bin"),
)


def _resample_to_16k(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if sample_rate == AUDIO_SR or audio.size < 2:
        return audio
    n = audio.size
    target = max(1, int(round(n * AUDIO_SR / sample_rate)))
    return np.interp(
        np.linspace(0.0, n - 1.0, target),
        np.linspace(0.0, n - 1.0, n),
        audio,
    ).astype(np.float32)


class MuseTalkCore:
    def __init__(self, weights_dir: str, device: str | None = None,
                 batch_size: int = 1, quantize: bool = False, threads: int = 0) -> None:
        import torch
        import torch.nn as nn
        from diffusers import AutoencoderKL, UNet2DConditionModel
        from transformers import AutoFeatureExtractor, WhisperModel

        if threads and threads > 0:
            torch.set_num_threads(threads)

        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self.dtype = torch.float16 if self.device.type == "cuda" else torch.float32
        self.batch_size = max(1, int(batch_size))
        self.weights_dir = weights_dir
        started = time.time()

        vae_dir = os.path.join(weights_dir, "sd-vae-ft-mse")
        self.vae = AutoencoderKL.from_pretrained(vae_dir).to(self.device, self.dtype)
        self.vae.eval()
        self.scaling = float(self.vae.config.scaling_factor)

        with open(os.path.join(weights_dir, "musetalkV15", "musetalk.json"), encoding="utf-8") as handle:
            unet_cfg = json.load(handle)
        unet_cfg = {k: v for k, v in unet_cfg.items() if not k.startswith("_")}
        self.unet = UNet2DConditionModel(**unet_cfg)
        state = torch.load(
            os.path.join(weights_dir, "musetalkV15", "unet.pth"),
            map_location="cpu",
            weights_only=True,
        )
        self.unet.load_state_dict(state)
        del state
        self.unet = self.unet.to(self.device, self.dtype).eval()

        if quantize and self.device.type == "cpu":
            try:
                self.unet = torch.quantization.quantize_dynamic(
                    self.unet, {nn.Linear}, dtype=torch.qint8
                )
                logger.info("MuseTalk UNet quantized to int8 (dynamic)")
            except Exception as exc:  # noqa: BLE001
                logger.warning("MuseTalk quantization skipped: %s", exc)

        self.whisper = WhisperModel.from_pretrained(
            os.path.join(weights_dir, "whisper")
        ).to(self.device, self.dtype)
        self.whisper.eval()
        self.feature_extractor = AutoFeatureExtractor.from_pretrained(
            os.path.join(weights_dir, "whisper")
        )
        self.pe = PositionalEncoding(384).to(self.device)
        logger.info("MuseTalk core ready on %s in %.1fs", self.device, time.time() - started)

    # -- portrait ----------------------------------------------------------
    def prepare_portrait(self, base_bgr: np.ndarray, bbox) -> None:
        import cv2
        import torch

        with torch.inference_mode():
            x1, y1, x2, y2 = [int(v) for v in bbox]
            height, width = y2 - y1, x2 - x1
            crop = base_bgr[y1:y2, x1:x2]
            resized = cv2.resize(crop, (256, 256), interpolation=cv2.INTER_LANCZOS4)
            self.base_bgr = base_bgr
            self.bbox = (x1, y1, x2, y2)

            half = resized.copy()
            half[128:, :] = 0
            latents = torch.cat([self._encode(half), self._encode(resized)], dim=1)
            self.latents = latents

            mask = np.zeros((height, width), np.float32)
            top = int(height * 0.48)
            side = max(4, int(width * 0.12))
            bottom = max(top + 8, height - max(6, int(height * 0.04)))
            mask[top:bottom, side:width - side] = 1.0
            sigma = max(4.0, height / 8.0)
            mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=sigma, sigmaY=sigma)
            self.mask = mask[..., None]

    def _encode(self, image_bgr: np.ndarray):
        import torch

        x = image_bgr.astype(np.float32) / 255.0
        x = (x - 0.5) / 0.5
        tensor = torch.from_numpy(x.transpose(2, 0, 1)).unsqueeze(0).to(self.device, self.dtype)
        return self.vae.encode(tensor).latent_dist.mode() * self.scaling

    # -- audio -------------------------------------------------------------
    def audio_prompts(self, audio: np.ndarray, sample_rate: int, fps: int):
        import torch

        with torch.inference_mode():
            wav = _resample_to_16k(np.asarray(audio, np.float32).reshape(-1), sample_rate)
            n_samples = int(wav.shape[0])
            seg_len = 30 * AUDIO_SR

            features = []
            for start in range(0, max(n_samples, 1), seg_len):
                segment = wav[start:start + seg_len]
                if segment.size == 0:
                    segment = np.zeros(AUDIO_SR, np.float32)
                features.append(
                    self.feature_extractor(
                        segment, return_tensors="pt", sampling_rate=AUDIO_SR
                    ).input_features
                )

            per_frame = 2 * (PAD_LEFT + PAD_RIGHT + 1)
            layers = []
            for feature in features:
                hidden = self.whisper.encoder(
                    feature.to(self.device, self.dtype), output_hidden_states=True
                ).hidden_states
                layers.append(torch.stack(hidden, dim=2))
            stacked = torch.cat(layers, dim=1)
            stacked = stacked[:, : int(n_samples / AUDIO_SR * AUDIO_FPS)]

            multiplier = AUDIO_FPS / float(fps)
            num_frames = int(math.floor((n_samples / AUDIO_SR) * fps))
            pad = int(math.ceil(multiplier))
            stacked = torch.cat([
                torch.zeros_like(stacked[:, : pad * PAD_LEFT]),
                stacked,
                torch.zeros_like(stacked[:, : pad * 3 * PAD_RIGHT]),
            ], dim=1)

            clips = []
            for index in range(num_frames):
                start = int(math.floor(index * multiplier))
                clip = stacked[:, start:start + per_frame]
                if clip.shape[1] != per_frame:
                    missing = per_frame - clip.shape[1]
                    if missing <= 0:
                        continue
                    clip = torch.cat([clip, torch.zeros_like(clip[:, :missing])], dim=1)
                clips.append(clip)
            if not clips:
                return torch.zeros((0, per_frame * 5, 384), dtype=self.dtype, device=self.device)
            out = torch.cat(clips, dim=0)
            b, c, h, w = out.shape
            return out.reshape(b, c * h, w)

    # -- generation --------------------------------------------------------
    def render_batch(self, prompts) -> list[np.ndarray]:
        import cv2
        import torch

        if prompts.shape[0] == 0:
            return []
        with torch.inference_mode():
            batch = prompts.shape[0]
            embeds = self.pe(prompts.to(self.device, self.dtype))
            latents = self.latents.to(self.device, self.dtype).expand(batch, -1, -1, -1)
            timesteps = torch.zeros(batch, dtype=torch.long, device=self.device)
            predicted = self.unet(latents, timesteps, encoder_hidden_states=embeds).sample
            predicted = predicted.float() / self.scaling
            recon = self.vae.decode(predicted.to(self.dtype)).sample
            recon = (recon / 2 + 0.5).clamp(0, 1)
            images = (recon.permute(0, 2, 3, 1).float().cpu().numpy() * 255).round().astype(np.uint8)

            x1, y1, x2, y2 = self.bbox
            frames = []
            for image in images:
                frame = self.base_bgr.copy()
                generated = cv2.resize(image, (x2 - x1, y2 - y1), interpolation=cv2.INTER_LANCZOS4)
                region = frame[y1:y2, x1:x2].astype(np.float32)
                blended = region * (1.0 - self.mask) + generated.astype(np.float32) * self.mask
                frame[y1:y2, x1:x2] = blended.astype(np.uint8)
                frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            return frames


class PositionalEncoding:
    """Factory that builds the torch module lazily (torch is an optional dep)."""

    def __new__(cls, d_model: int = 384, max_len: int = 5000):
        import torch
        import torch.nn as nn

        class _PositionalEncoding(nn.Module):
            def __init__(self):
                super().__init__()
                pe = torch.zeros(max_len, d_model)
                position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
                div_term = torch.exp(
                    torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
                )
                pe[:, 0::2] = torch.sin(position * div_term)
                pe[:, 1::2] = torch.cos(position * div_term)
                self.register_buffer("pe", pe.unsqueeze(0))

            def forward(self, x):
                return x + self.pe[:, : x.size(1), :].to(device=x.device, dtype=x.dtype)

        return _PositionalEncoding()


class MuseTalkCPUAvatar(BaseAvatar):
    name = "musetalk_cpu"

    def __init__(self, width: int = 512, height: int = 512,
                 weights_dir: str | None = None, portrait: str | None = None) -> None:
        super().__init__(width, height)
        self.weights_dir = str(settings.abs_path(weights_dir or settings.avatar_musetalk_dir))
        self.portrait_path = str(settings.abs_path(portrait or settings.avatar_portrait))
        self._core: MuseTalkCore | None = None
        self._error = ""
        self._lock = threading.Lock()

    def is_ready(self) -> bool:
        missing = [
            os.path.join(self.weights_dir, folder, name)
            for folder, name in REQUIRED
            if not os.path.exists(os.path.join(self.weights_dir, folder, name))
        ]
        if missing:
            self._error = "MuseTalk weights missing: " + ", ".join(
                os.path.relpath(path, self.weights_dir) for path in missing
            )
            return False
        if not os.path.exists(self.portrait_path):
            self._error = f"portrait missing: {self.portrait_path}"
            return False
        return True

    def reason(self) -> str:
        return self._error

    def _bbox(self) -> tuple[int, int, int, int]:
        import cv2

        raw = settings.avatar_musetalk_bbox.strip()
        if raw:
            try:
                values = tuple(int(v) for v in raw.split(","))
                if len(values) == 4:
                    return values  # type: ignore[return-value]
            except ValueError:
                logger.warning("invalid AVATAR_MUSETALK_BBOX=%r; using defaults", raw)
        image = cv2.imread(self.portrait_path)
        if image is None:
            raise AvatarError(f"cannot read portrait: {self.portrait_path}")
        height, width = image.shape[:2]
        return (
            int(width * 0.30), int(height * 0.18),
            int(width * 0.70), int(height * 0.88),
        )

    def _ensure_core(self) -> MuseTalkCore:
        if self._core is not None:
            return self._core
        with self._lock:
            if self._core is not None:
                return self._core
            if self._error:
                raise AvatarError(self._error)
            import cv2

            core = MuseTalkCore(
                self.weights_dir,
                batch_size=settings.avatar_batch_size,
                quantize=settings.avatar_cpu_quantize,
                threads=settings.avatar_cpu_threads,
            )
            base = cv2.imread(self.portrait_path)
            if base is None:
                raise AvatarError(f"cannot read portrait: {self.portrait_path}")
            base = cv2.resize(base, (self.width, self.height))
            core.prepare_portrait(base, self._bbox())
            self._core = core
            return core

    def warmup(self) -> None:
        self._ensure_core()

    def render(self, audio: np.ndarray, sample_rate: int, fps: int = 25) -> AvatarClip:
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if audio.size == 0 or sample_rate <= 0:
            return AvatarClip([], fps, self.width, self.height)
        core = self._ensure_core()

        duration = audio.size / float(sample_rate)
        target_frames = max(1, int(math.floor(duration * fps)))
        render_fps = max(1, min(fps, settings.avatar_cpu_render_fps))
        prompts = core.audio_prompts(audio, sample_rate, render_fps)
        if prompts.shape[0] == 0:
            return AvatarClip([], fps, self.width, self.height)

        unique: list[np.ndarray] = []
        step = core.batch_size
        for start in range(0, prompts.shape[0], step):
            unique.extend(core.render_batch(prompts[start:start + step]))
        if not unique:
            return AvatarClip([], fps, self.width, self.height)

        frames = []
        for index in range(target_frames):
            source = min(len(unique) - 1, int(index * render_fps / float(fps)))
            frames.append(unique[source])
        return AvatarClip(frames, fps, self.width, self.height)
