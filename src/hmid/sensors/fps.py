"""FPS of the running game, read from MangoHud's live CSV log.

MangoHud writes one row per `log_interval` and flushes it, so the newest row is the
current FPS. ~/.config/MangoHud/MangoHud.conf:
    fps_only
    alpha=0.0                 # invisible overlay (no_display stops logging in some versions)
    background_alpha=0.0
    autostart_log=1
    log_interval=1000
    output_folder=/tmp/hmi-fps
A log that stopped growing (game closed) counts as "no game". Files are only read,
never modified or deleted.
"""
from __future__ import annotations

import glob
import os
import time
from dataclasses import dataclass


@dataclass
class GameSample:
    fps: float
    frametime: float | None
    app: str


class MangoHudFps:
    def __init__(self, folder: str = "/tmp/hmi-fps", stale: float = 4.0):
        self.folder, self.stale = folder, stale
        self._cols: dict[str, tuple[int, int | None]] = {}

    def setup(self):
        """Create the shared log folder (sticky, world-writable like /tmp)."""
        try:
            os.makedirs(self.folder, exist_ok=True)
            os.chmod(self.folder, 0o1777)
        except OSError:
            pass

    def _newest(self) -> str | None:
        now, best = time.time(), None
        for f in glob.glob(os.path.join(self.folder, "*.csv")):
            if f.endswith("_summary.csv"):
                continue
            try:
                m = os.path.getmtime(f)
            except OSError:
                continue
            if now - m < self.stale and (best is None or m > best[0]):
                best = (m, f)
        return best[1] if best else None

    def read(self) -> GameSample | None:
        f = self._newest()
        if not f:
            return None
        try:
            with open(f, "rb") as fh:
                if f not in self._cols:
                    for line in fh.read(8192).decode(errors="replace").splitlines():
                        cols = line.strip().split(",")
                        if cols and cols[0] == "fps":
                            self._cols[f] = (0, cols.index("frametime") if "frametime" in cols else None)
                            break
                    else:
                        return None
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - 2048))
                rows = fh.read().decode(errors="replace").splitlines()
            row = next((r.split(",") for r in reversed(rows) if r and r[0].isdigit()), None)
            if not row:
                return None
            fi, ti = self._cols[f]
            fps = float(row[fi])
            ft = float(row[ti]) if ti is not None and ti < len(row) else None
        except (OSError, ValueError, IndexError):
            return None
        return GameSample(fps, ft, app_name(f))


def app_name(path: str) -> str:
    """<program>_<YYYY-MM-DD>_<HH-MM-SS>.csv -> program, without .exe / .x86_64 / ... suffixes."""
    name = os.path.basename(path)[:-4]
    parts = name.rsplit("_", 2)
    app = parts[0] if len(parts) == 3 else name
    for suffix in (".exe", ".x86_64", ".x86", ".bin", ".appimage"):
        if app.lower().endswith(suffix):
            return app[: -len(suffix)]
    return app
