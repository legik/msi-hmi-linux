"""Pictures and animations for the panel's picture mode (slot 7).

Still pictures go up as a 480x800 PNG. Animated GIFs and videos are converted with ffmpeg
to what MSI Center uploads: H.264 Constrained Baseline (level 3.0, no B-frames) in an AVI
container, 480x800 - the panel plays it in a loop.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile

from .panel.protocol import HEIGHT, WIDTH

VIDEO_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v")
MODES = ("fill", "fit", "stretch")    # fill: cover the screen, crop the edges; fit: black borders
MAX_SECONDS = 30
MAX_BYTES = 10 * 1024 * 1024


def is_animated(path: str) -> bool:
    if path.lower().endswith(VIDEO_EXT):
        return True
    from PIL import Image
    try:
        with Image.open(path) as im:
            return bool(getattr(im, "is_animated", False)) and getattr(im, "n_frames", 1) > 1
    except OSError:
        return False


def still_png(path: str, mode: str = "fill", rotate: bool = False) -> bytes:
    """Any picture -> 480x800 PNG. rotate: turn 90 degrees first (wide pictures)."""
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        if rotate:
            im = im.transpose(Image.Transpose.ROTATE_270)
        if mode == "fit":
            im = ImageOps.pad(im, (WIDTH, HEIGHT), color=(0, 0, 0))
        elif mode == "stretch":
            im = im.resize((WIDTH, HEIGHT), Image.LANCZOS)
        else:
            im = ImageOps.fit(im, (WIDTH, HEIGHT), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, "PNG", compress_level=6)
    return b.getvalue()


def _video_filter(mode: str, rotate: bool, fps: int) -> str:
    size = {"fit": f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,pad={WIDTH}:{HEIGHT}:-1:-1:color=black",
            "stretch": f"scale={WIDTH}:{HEIGHT}",
            "fill": f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}"}
    return ("transpose=1," if rotate else "") + size.get(mode, size["fill"]) + f",setsar=1,fps={fps},format=yuv420p"


def animation_avi(path: str, mode: str = "fill", rotate: bool = False, fps: int = 30) -> bytes:
    """Animated GIF / video -> H.264 AVI the panel plays (needs ffmpeg)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is needed for animated pictures (sudo pacman -S ffmpeg)")
    vf = _video_filter(mode, rotate, fps)
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "anim.avi")
        r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", path, "-t", str(MAX_SECONDS), "-an",
                            "-vf", vf, "-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0",
                            "-bf", "0", "-refs", "1", "-g", str(fps * 10), "-crf", "23", out],
                           capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[:200]}")
        size = os.path.getsize(out)
        if size > MAX_BYTES:
            raise RuntimeError(f"animation too large ({size // 1024} KB, max {MAX_BYTES // 1024} KB) - use a shorter clip")
        with open(out, "rb") as f:
            return f.read()
