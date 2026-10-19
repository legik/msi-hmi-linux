#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Make a background video for the dynamic screen.

The panel plays an MP4 behind the uploaded overlay. It accepts H.264 Constrained
Baseline, 480x800, yuv420p (15 fps works). Without an image argument this rebuilds the
built-in background (the theme's dark teal canvas):

    python3 tools/make_background.py out.mp4 [picture.png]

then set "background": "/path/out.mp4" in /etc/hmid.json. Needs ffmpeg.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    out = sys.argv[1]
    with tempfile.TemporaryDirectory() as tmp:
        frame = os.path.join(tmp, "frame.png")
        from PIL import Image, ImageOps
        if len(sys.argv) > 2:
            im = ImageOps.fit(Image.open(sys.argv[2]).convert("RGB"), (480, 800))
        else:
            from hmid.render import draw
            im = draw.background().resize((480, 800), Image.LANCZOS).convert("RGB")
        im.save(frame)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", frame, "-t", "5", "-r", "15",
                        "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                        out], check=True)
    print(f"wrote {out} ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
