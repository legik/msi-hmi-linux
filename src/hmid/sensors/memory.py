from __future__ import annotations

import subprocess
import time

from .sysfs import read


def meminfo() -> dict[str, int]:
    """/proc/meminfo in kB."""
    out = {}
    for line in (read("/proc/meminfo", "") or "").splitlines():
        k, _, v = line.partition(":")
        if v:
            out[k] = int(v.split()[0])
    return out


def usage() -> tuple[float, float]:
    """(used GB, total GB); used = total - available."""
    m = meminfo()
    total, avail = m.get("MemTotal", 0) / 1048576, m.get("MemAvailable", 0) / 1048576
    return total - avail, total


def free_mb() -> float:
    return meminfo().get("MemFree", 0) / 1024


_mhz = None


_mhz_tried = 0.0


def clock_mhz() -> int:
    """Configured RAM speed (dmidecode needs root: hmid-helper asks it), cached; 0 if unknown."""
    global _mhz, _mhz_tried
    if _mhz is None:
        from .. import privileged
        if privileged.direct():
            _mhz = dmidecode_mhz()
        elif time.time() - _mhz_tried > 60:         # helper not up yet: ask again a minute later
            _mhz_tried = time.time()
            try:
                _mhz = int(privileged.call("ram-clock", timeout=10))
            except (OSError, ValueError, TypeError):
                return 0
        else:
            return 0
    return _mhz


def dmidecode_mhz() -> int:
    """Configured RAM speed from dmidecode (root); 0 if unknown."""
    try:
        out = subprocess.run(["dmidecode", "-t", "memory"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    for line in out.splitlines():
        line = line.strip()
        if line.startswith(("Configured Memory Speed:", "Configured Clock Speed:")):
            v = line.split(":")[1].split()[0]
            if v.isdigit():
                return int(v)
    return 0
