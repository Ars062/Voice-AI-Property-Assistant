"""Fetch optional local models.

  python scripts/fetch_assets.py --whisper          # pre-download faster-whisper
  python scripts/fetch_assets.py --piper            # Piper neural voice (~65 MB)
  python scripts/fetch_assets.py --musetalk         # MuseTalk weights (large)
  python scripts/fetch_assets.py --all

The app runs without any of these: STT downloads on first use, TTS falls back to
Windows SAPI, and the avatar falls back to the CPU puppet engine.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
MUSETALK_REQUIRED = (
    "musetalkV15/unet.pth",
    "musetalkV15/musetalk.json",
    "sd-vae-ft-mse/config.json",
    "sd-vae-ft-mse/diffusion_pytorch_model.bin",
    "whisper/config.json",
    "whisper/pytorch_model.bin",
)


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        print(f"  exists  {destination.relative_to(ROOT)}")
        return
    print(f"  fetching {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "voice-property-assistant/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        with open(destination, "wb") as handle:
            shutil.copyfileobj(response, handle)
    print(f"  saved   {destination.relative_to(ROOT)} ({destination.stat().st_size / 1e6:.1f} MB)")


def fetch_piper() -> None:
    from config import settings

    target = settings.abs_path(settings.tts_piper_model_dir)
    voice = settings.tts_piper_voice
    print(f"Piper voice: {voice} -> {target}")
    _download(f"{PIPER_BASE}/{voice}.onnx", target / f"{voice}.onnx")
    _download(f"{PIPER_BASE}/{voice}.onnx.json", target / f"{voice}.onnx.json")
    print("Install the runtime with: pip install -r requirements-piper.txt")


def fetch_whisper() -> None:
    from config import settings

    print(f"Whisper model: {settings.whisper_model_size} -> {settings.whisper_model_dir}")
    from faster_whisper import WhisperModel

    WhisperModel(
        settings.whisper_model_size,
        device="cpu",
        compute_type=settings.whisper_compute_type,
        download_root=str(settings.abs_path(settings.whisper_model_dir)),
    )
    print("  ready")


def fetch_musetalk() -> None:
    from config import settings

    target = settings.abs_path(settings.avatar_musetalk_dir)
    print(f"MuseTalk weights -> {target}")
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub is not installed. Install it with:")
        print("  pip install huggingface_hub")
        print("Then re-run, or download TMElyralab/MuseTalk manually.")
        return

    try:
        snapshot_download(repo_id="TMElyralab/MuseTalk", local_dir=str(target))
    except Exception as exc:  # noqa: BLE001
        print(f"automatic download failed: {exc}")
        print("Download https://huggingface.co/TMElyralab/MuseTalk manually and keep this layout:")
        for item in MUSETALK_REQUIRED:
            print(f"  {target / item}")
        return

    missing = [item for item in MUSETALK_REQUIRED if not (target / item).exists()]
    if missing:
        print("Downloaded, but the layout differs. Move or copy these files into place:")
        for item in missing:
            print(f"  {target / item}")
    else:
        print("MuseTalk weights look complete.")
    print("Install the runtime with: pip install -r requirements-avatar.txt")
    print("Then set AVATAR_ENGINE=musetalk (or leave auto) in .env.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download optional local models")
    parser.add_argument("--whisper", action="store_true")
    parser.add_argument("--piper", action="store_true")
    parser.add_argument("--musetalk", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if not any((args.whisper, args.piper, args.musetalk, args.all)):
        parser.print_help()
        return

    if args.whisper or args.all:
        fetch_whisper()
    if args.piper or args.all:
        fetch_piper()
    if args.musetalk or args.all:
        fetch_musetalk()


if __name__ == "__main__":
    main()
