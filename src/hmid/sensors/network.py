from __future__ import annotations

import time

from .sysfs import read


class Network:
    """Total download/upload rate over all interfaces except loopback, in bytes/s."""

    def __init__(self):
        self._prev = None

    def rates(self) -> tuple[float | None, float | None]:
        rx = tx = 0
        for line in (read("/proc/net/dev", "") or "").splitlines()[2:]:
            name, _, data = line.partition(":")
            if name.strip() == "lo" or not data:
                continue
            f = data.split()
            rx += int(f[0])
            tx += int(f[8])
        now, down, up = time.time(), None, None
        if self._prev:
            dt = now - self._prev[0]
            if dt > 0:
                down, up = (rx - self._prev[1]) / dt, (tx - self._prev[2]) / dt
        self._prev = (now, rx, tx)
        return down, up
