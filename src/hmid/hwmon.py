"""Hardware-monitor sensors in MSI's order, and their encodings.

The panel-drawn monitor ("list" mode) has 16 sensor screens plus a network page and
takes 27 u16 values per update (protocol.hw_values). "multi" mode draws the same
sensors (plus a few extras) as tiles on the dynamic screen.
"""
from __future__ import annotations

from dataclasses import dataclass

from .sensors import Sample


@dataclass(frozen=True)
class Sensor:
    slot: int | None          # panel-drawn monitor screen (None = multi mode only)
    label: str
    unit: str


SENSORS: dict[str, Sensor] = {
    "cpu_clock":   Sensor(0, "CPU CLOCK", "MHz"),
    "cpu_load":    Sensor(1, "CPU LOAD", "%"),
    "cpu_temp":    Sensor(2, "CPU TEMP", "°C"),
    "cpu_fan":     Sensor(3, "CPU FAN", "RPM"),
    "pump":        Sensor(4, "PUMP", "RPM"),
    "gpu_clock":   Sensor(5, "GPU CLOCK", "MHz"),
    "gpu_load":    Sensor(6, "GPU LOAD", "%"),
    "gpu_temp":    Sensor(7, "GPU TEMP", "°C"),
    "gpu_fan":     Sensor(8, "GPU FAN", "RPM"),
    "ram_clock":   Sensor(9, "RAM CLOCK", "MHz"),
    "fps":         Sensor(10, "FPS", ""),
    "vrm_temp":    Sensor(11, "VRM TEMP", "°C"),
    "cpu_fan_pct": Sensor(12, "CPU FAN", "%"),
    "gpu_fan_pct": Sensor(13, "GPU FAN", "%"),
    "sys_fan":     Sensor(14, "SYSTEM FAN", "RPM"),
    "sys_fan_pct": Sensor(15, "SYSTEM FAN", "%"),
    "upload":      Sensor(None, "UPLOAD", ""),        # list mode: network page
    "download":    Sensor(None, "DOWNLOAD", ""),      # list mode: network page
    "ram_used":    Sensor(None, "MEMORY", "GB"),
    "cpu_power":   Sensor(None, "CPU POWER", "W"),
    "gpu_power":   Sensor(None, "GPU POWER", "W"),
}
NETWORK = ("upload", "download")
SLOTS = sorted((n for n, s in SENSORS.items() if s.slot is not None), key=lambda n: SENSORS[n].slot)

MULTI_DEFAULT = ["fps", "cpu_load", "cpu_temp", "cpu_clock", "cpu_fan", "gpu_load", "gpu_temp",
                 "gpu_clock", "gpu_fan_pct", "ram_used", "download", "upload"]   # fps only while gaming
MULTI_PER_PAGE = 12


def select(names, mode: str, missing: set[str] = frozenset(), log=None) -> list[str]:
    """Configured names -> the ones to show. names=None: list = all, multi = MULTI_DEFAULT."""
    if not names:
        names = list(MULTI_DEFAULT) if mode == "multi" else list(SENSORS)
    bad = [n for n in names if n not in SENSORS]
    if bad and log:
        log("hwmon: unknown sensor names ignored:", ", ".join(bad))
    out = [n for n in names if n in SENSORS]
    if mode == "list":
        out = [n for n in out if n in NETWORK or SENSORS[n].slot is not None]
    return [n for n in out if n not in missing] or out


def list_layout(names, style: int) -> tuple[bytes, bytes]:
    """SetDisplay data for the panel-drawn monitor: (mode 7 network page, mode 0 slots)."""
    style = max(1, min(3, int(style)))
    show = set(names)
    slots = bytes(style if n in show else 0 for n in SLOTS)
    net = bytes([style if "upload" in show else 0, style if "download" in show else 0]) + bytes(14)
    return net, slots


def _net(bps) -> int:
    """KB/s x10, flag 16384 = MB/s, 32768 = GB/s."""
    v = (bps or 0) / 1024 * 10
    unit = 0
    if v > 10240:
        v, unit = v / 1024, 1
    if v > 10240:
        v, unit = v / 1024, 2
    return min(int(v), 16383) | (16384 if unit == 1 else 32768 if unit == 2 else 0)


def encode(s: Sample) -> list[int]:
    """The 27 values MSI's panel-drawn monitor expects (MSI HWMonitor_UpdateTask order)."""
    g = s.gpu
    fan = lambda role: s.fans.get(role, (0, 0))
    v = [0] * 27
    v[0] = int((s.cpu_mhz or 0) / 100)
    v[1] = int(s.cpu_load or 0)
    v[2] = int(s.cpu_temp or 0)
    v[3] = fan("cpu_fan")[0]
    v[4] = fan("pump")[0]
    v[5] = g.clock if g else 0
    v[6] = int(g.load or 0) if g else 0
    v[7] = int(g.temp or 0) if g else 0
    v[8] = 0                                   # GPU fan RPM: not available
    v[9] = s.mem_mhz
    v[10] = int(round(s.game.fps)) if s.game else 0
    v[11] = int(s.vrm_temp or 0)
    v[12] = fan("cpu_fan")[1]
    v[13] = (g.fan_pct or 0) if g else 0
    v[14] = fan("sys_fan")[0]
    v[15] = fan("sys_fan")[1]
    v[16] = _net(s.net_up)
    v[17] = _net(s.net_down)
    return [max(0, min(int(x), 0xFFFF)) for x in v]


# ---- text for multi-mode tiles ------------------------------------------------------
def fmt_rate(bps) -> str:
    if bps is None:
        return "–"
    if bps >= 1e6:
        return f"{bps / 1e6:.1f} MB/s"
    if bps >= 1e3:
        return f"{bps / 1e3:.0f} KB/s"
    return f"{bps:.0f} B/s"


def load_state(pct, warn=65, crit=85):
    if pct is None:
        return None
    return "crit" if pct >= crit else "warn" if pct >= warn else "normal"


def temp_state(t):
    if t is None:
        return None
    return "crit" if t >= 80 else "warn" if t >= 65 else "normal"


@dataclass
class Reading:
    text: str
    unit: str
    pct: float | None = None       # draws a bar
    state: str | None = None       # normal / warn / crit


def readings(s: Sample) -> dict[str, Reading]:
    num = lambda v, d=0: "–" if v is None else f"{v:.{d}f}"
    g = s.gpu
    enc = encode(s)
    out = {}
    for name, sen in SENSORS.items():
        r = Reading(str(enc[sen.slot]) if sen.slot is not None else "–", sen.unit)
        if name == "cpu_clock":
            r.text = f"{enc[0] * 100}"
        elif name == "cpu_load":
            r.text, r.pct, r.state = num(s.cpu_load), s.cpu_load, load_state(s.cpu_load)
        elif name == "cpu_temp":
            r.text, r.state = num(s.cpu_temp), temp_state(s.cpu_temp)
        elif name == "vrm_temp":
            r.text, r.state = num(s.vrm_temp), temp_state(s.vrm_temp + 5 if s.vrm_temp else None)
        elif name == "gpu_load":
            v = g.load if g else None
            r.text, r.pct, r.state = num(v), v, load_state(v)
        elif name == "gpu_temp":
            v = g.temp if g else None
            r.text, r.state = num(v), temp_state(v)
        elif name in ("cpu_fan_pct", "gpu_fan_pct", "sys_fan_pct"):
            if name == "gpu_fan_pct":
                v = g.fan_pct if g else None
            else:
                f = s.fans.get(name[:-4])
                v = f[1] if f else None
            r.text, r.pct = num(v), v                  # no reading: "–", not "0 %"
        elif name == "fps":
            v = s.game.fps if s.game else None
            r.text, r.state = num(v), ("warn" if v is not None and v < 30 else None)
        elif name == "upload":
            r.text = fmt_rate(s.net_up)
        elif name == "download":
            r.text = fmt_rate(s.net_down)
        elif name == "ram_used":
            pct = 100 * s.mem_used / s.mem_total if s.mem_total else None
            r.text, r.pct, r.state = f"{s.mem_used:.1f}", pct, load_state(pct)
            r.unit = f"/ {s.mem_total:.0f} GB" if s.mem_total else "GB"
        elif name == "cpu_power":
            r.text = num(s.cpu_power)
        elif name == "gpu_power":
            r.text = num(g.power if g else None)
        out[name] = r
    return out
