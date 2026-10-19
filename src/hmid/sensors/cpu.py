"""CPU load, package temperature, average clock and package power (Intel RAPL)."""
from __future__ import annotations

import glob
import os
import time

from .sysfs import input_of, read, read_int

RAPL = "/sys/class/powercap/intel-rapl:0/energy_uj"


def find_temp_input() -> str | None:
    """coretemp "Package id 0" (Intel) or k10temp/zenpower "Tctl"/"Tdie" (AMD)."""
    for hw in glob.glob("/sys/class/hwmon/hwmon*"):
        if read(f"{hw}/name", "") not in ("coretemp", "k10temp", "zenpower"):
            continue
        best = None
        for lab in sorted(glob.glob(f"{hw}/temp*_label")):
            name = read(lab, "")
            if name.startswith("Package") or name in ("Tctl", "Tdie"):
                return input_of(lab)
            best = best or input_of(lab)
        if best:
            return best
        if os.path.exists(f"{hw}/temp1_input"):
            return f"{hw}/temp1_input"
    return None


class Cpu:
    def __init__(self):
        self.temp_path = find_temp_input()
        self._prev = None
        self._rapl = None

    @property
    def has_power(self) -> bool:
        return os.path.exists(RAPL)

    def load(self) -> float | None:
        line = (read("/proc/stat", "") or "").splitlines()
        if not line:
            return None
        v = list(map(int, line[0].split()[1:]))
        idle, total = v[3] + v[4], sum(v)
        out = None
        if self._prev:
            dt, di = total - self._prev[0], idle - self._prev[1]
            out = 100.0 * (dt - di) / dt if dt else 0.0
        self._prev = (total, idle)
        return out

    def temp(self) -> float | None:
        t = read_int(self.temp_path) if self.temp_path else None
        return t / 1000 if t is not None else None

    @staticmethod
    def mhz() -> float | None:
        f = [read_int(p) or 0 for p in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")]
        return sum(f) / len(f) / 1000 if f else None

    def power(self) -> float | None:
        """Package power in W from the RAPL energy counter (readable by root only: when hmid
        runs as its own user, hmid-helper reads it)."""
        e = read_int(RAPL)
        if e is None and self.has_power:
            from .. import privileged
            if not privileged.direct():
                try:
                    e = int(privileged.call("cpu-energy", timeout=3))
                except (OSError, ValueError, TypeError):
                    e = None
        if e is None:
            return None
        now, prev = time.time(), self._rapl
        self._rapl = (now, e)
        if not prev or now <= prev[0] or e < prev[1]:
            return None
        return (e - prev[1]) / 1e6 / (now - prev[0])
