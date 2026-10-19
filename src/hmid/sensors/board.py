"""Motherboard fans and VRM temperature.

MSI boards use a Nuvoton NCT6687 chip. Linux reads it with the in-kernel `nct6683`
driver (`modprobe nct6683 force=1`) or the out-of-tree `nct6687d` driver.
MSI's header order: fan1 CPU fan, fan2 pump, fan3.. system fans; temperatures:
CPU, system, VRM MOS (3rd), PCH, socket, ...
"""
from __future__ import annotations

import glob
import os

from .sysfs import input_of, read, read_int

FAN_ROLES = ("cpu_fan", "pump", "sys_fan")
CHIPS = ("nct6687", "nct6683", "nct6686")


def find_chip() -> str | None:
    for hw in glob.glob("/sys/class/hwmon/hwmon*"):
        if (read(f"{hw}/name", "") or "").startswith(CHIPS):
            return hw
    return None


def _fan(hw: str, n) -> tuple[int, int] | None:
    rpm = read_int(f"{hw}/fan{n}_input")
    if rpm is None:
        return None
    pwm = read_int(f"{hw}/pwm{n}")
    return rpm, (min(100, round(pwm * 100 / 255)) if pwm is not None else 0)


def all_fans() -> list[tuple[str, int, int]]:
    """[(label, rpm, pct)] of every hwmon fan except GPU drivers (generic boards)."""
    out = []
    for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        if read(f"{hw}/name", "") in ("amdgpu", "nouveau"):
            continue
        for fi in sorted(glob.glob(f"{hw}/fan[0-9]*_input")):
            n = fi[len(hw) + 4:-6]
            r = _fan(hw, n)
            if r:
                out.append((read(f"{hw}/fan{n}_label", f"fan{n}"), *r))
    return out


class Board:
    def __init__(self, fan_map: dict[str, str] | None = None, vrm_label: str | None = None, chip: str | None = ...):
        self.fan_map = dict(fan_map or {})
        self.vrm_label = vrm_label
        self.chip = find_chip() if chip is ... else chip

    def fans(self) -> dict[str, tuple[int, int]]:
        """{"cpu_fan": (rpm, pct), "pump": ..., "sys_fan": ...}; missing = no reading."""
        hw = self.chip
        if not hw:
            f = all_fans()
            return {k: f[i][1:] for i, k in enumerate(FAN_ROLES) if i < len(f)}
        m = dict(self.fan_map)
        if not m:
            m = {"cpu_fan": "fan1", "pump": "fan2"}
            for n in range(3, 9):                   # first system fan that spins
                r = _fan(hw, n)
                if r and r[0] > 0:
                    m["sys_fan"] = f"fan{n}"
                    break
        out = {}
        for role, name in m.items():
            r = _fan(hw, name.replace("fan", ""))
            if r and r[0] > 0:
                out[role] = r
        return out

    def vrm_temp(self) -> float | None:
        hw = self.chip
        if not hw:
            return None
        labels = sorted(glob.glob(f"{hw}/temp*_label"), key=lambda p: int(os.path.basename(p)[4:-6]))
        for i, lab in enumerate(labels):
            if (self.vrm_label and read(lab, "") == self.vrm_label) or (not self.vrm_label and i == 2):
                t = read_int(input_of(lab))
                return t / 1000 if t is not None else None
        return None
