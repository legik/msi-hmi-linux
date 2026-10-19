"""Mystic Light controller of the MSI MEG Trident X2 (USB 1462:931b).

The controller takes one 185-byte HID feature report (ID 0x52) holding all LED zones
(the layout OpenRGB uses for MSI boards; OpenRGB does not know this product ID).
Effect bytes were taken from MSI Center's own writes, so we send exactly what MSI sends:
  * basic effects (steady, breathing, flashing, double flashing) change bytes 11-63
    (five zones),
  * animated effects (rainbow, meteor, marquee, ...) change bytes 74-83 (one zone).
Each change is read-modify-write. Byte 184 ("save to flash") is always 0.
"""
from __future__ import annotations

import fcntl
import glob
import os

VID, PID = "1462", "931B"
REPORT, SIZE = 0x52, 185
BASIC_SLICE, STRIP_SLICE = (11, 64), (74, 84)
EFFECT_OFFSETS = (11, 21, 31, 42, 53, 74)          # effect byte of each zone used
STRIP_CONTROL = 82                                 # animated zone: 00 = off/basic, 0f/8f = animated
SAVE_BYTE = 184

# panel item -> (zone group, bytes) - from MSI Center's writes
EFFECTS = {
    81: ("basic", "00ff00002800ff00801000ff00002800ff00801826dc821428dc821480000926dc821428dc821480000926dc641428dc6414805009"),
    82: ("basic", "01ff000020ff0000801001ff000020ff0000801801ff000020ff000080000901ff000020ff000080000901ff000020ff0000820009"),
    83: ("basic", "02ff000020ff0000801002ff000020ff0000801802ff000020ff000080000902ff000020ff000080000902ff000020ff0000820009"),
    84: ("basic", "03ff000020ff0000801003ff000020ff0000801803ff000020ff000080000903ff000020ff000080000903ff000020ff0000820009"),
    85: ("basic", "04ff000020ff0000801004ff000020ff0000801804ff000020ff000080000904ff000020ff000080000904ff000020ff0000820009"),
    86: ("strip", "1bff000020ff00000f00"),   # Visor
    87: ("strip", "24ff000020ff00008f00"),   # Stack
    88: ("strip", "18ff000020ff00008f00"),   # Marquee
    89: ("strip", "0100ff002800ff008f00"),   # CPU temperature (colour updated by cpu_temp_color)
    90: ("strip", "07ff000020ff00008f00"),   # Meteor
    91: ("strip", "05ff000020ff00008f00"),   # Lightning
    92: ("strip", "1aff000020ff00000f00"),   # Rainbow
    93: ("strip", "0fff000020ff00000f00"),   # Color ring
    94: ("strip", "16ff000020ff00000f00"),   # Color shift
    95: ("strip", "02ff000020ff00008f00"),   # Random
    96: ("strip", "0aff000020ff00000f00"),   # POP
    97: ("strip", "0bff000020ff00000f00"),   # RAP
    98: ("strip", "0cff000020ff00008f00"),   # JAZZ
    99: ("strip", "0dff000020ff00000f00"),   # Play
    100: ("strip", "0eff000020ff00008f00"),  # Movie
}
STRIP_DEFAULT = "26ff00002800ff008000"       # MSI default for the animated zone

# MSI's CPU-temperature colours: (below degC, rgb)
CPU_TEMP_COLORS = ((70, (0, 255, 0)), (90, (0, 0, 255)), (999, (255, 0, 0)))

EFFECT_NAMES = {0: "off", 1: "steady", 2: "breathing", 3: "flashing", 4: "double flashing", 5: "lightning",
                7: "meteor", 10: "pop", 11: "rap", 12: "jazz", 13: "play", 14: "movie", 15: "color ring",
                22: "color shift", 24: "marquee", 26: "rainbow", 27: "visor", 36: "stack", 38: "MSI default"}


def _ioc(d, t, nr, size):
    return (d << 30) | (size << 16) | (ord(t) << 8) | nr


def HIDIOCGFEATURE(n):
    return _ioc(3, "H", 0x07, n)


def HIDIOCSFEATURE(n):
    return _ioc(3, "H", 0x06, n)


def find_node() -> str | None:
    for h in glob.glob("/sys/class/hidraw/hidraw*"):
        try:
            with open(f"{h}/device/uevent") as f:
                if f"0000{VID}:0000{PID}" in f.read().upper():
                    return "/dev/" + os.path.basename(h)
        except OSError:
            pass
    return None


class HidrawDevice:
    def __init__(self, node: str | None = None):
        self.node = node or find_node()
        if not self.node:
            raise OSError("Mystic Light controller 1462:931b not found")

    def read(self) -> bytearray:
        fd = os.open(self.node, os.O_RDWR)
        try:
            buf = bytearray(SIZE)
            buf[0] = REPORT
            fcntl.ioctl(fd, HIDIOCGFEATURE(SIZE), buf)
            return buf
        finally:
            os.close(fd)

    def write(self, buf: bytes):
        fd = os.open(self.node, os.O_RDWR)
        try:
            fcntl.ioctl(fd, HIDIOCSFEATURE(SIZE), bytearray(buf))
        finally:
            os.close(fd)


def _set_color(buf, offsets, rgb: bytes):
    for o in offsets:
        buf[o + 1:o + 4] = rgb          # colour 1
        buf[o + 5:o + 8] = rgb          # colour 2


def apply_effect(buf: bytearray, item: int, color: str | None = None) -> bytearray:
    """Pure: the report with panel item 80 (off) .. 100 applied."""
    buf = bytearray(buf)
    if buf[0] != REPORT:
        raise OSError(f"unexpected report from controller: {bytes(buf[:4]).hex()}")
    if item == 80:
        for o in EFFECT_OFFSETS:
            buf[o] = 0
    elif item == 81:
        a, b = BASIC_SLICE
        buf[a:b] = bytes.fromhex(EFFECTS[81][1])
        a, b = STRIP_SLICE
        buf[a:b] = bytes.fromhex(STRIP_DEFAULT)
    elif item in EFFECTS:
        group, data = EFFECTS[item]
        a, b = BASIC_SLICE if group == "basic" else STRIP_SLICE
        buf[a:b] = bytes.fromhex(data)
        if group == "basic":
            # MSI's basic-effect writes always switch the animated zone off,
            # otherwise e.g. Rainbow keeps overriding the new effect
            buf[STRIP_CONTROL] = 0x00
        if color:
            _set_color(buf, EFFECT_OFFSETS[:5] if group == "basic" else EFFECT_OFFSETS[5:],
                       bytes.fromhex(color.lstrip("#")))
    else:
        raise ValueError(f"no Mystic Light effect for item {item}")
    buf[SAVE_BYTE] = 0
    return buf


def temp_color(temp_c: float) -> tuple[int, int, int]:
    return next(c for limit, c in CPU_TEMP_COLORS if temp_c < limit)


class MysticLight:
    def __init__(self, device=None):
        self.dev = device or HidrawDevice()

    def apply(self, item: int, color: str | None = None):
        self.dev.write(apply_effect(self.dev.read(), item, color))

    def cpu_temp_color(self, temp_c: float):
        buf = self.dev.read()
        a = STRIP_SLICE[0]
        rgb = bytes(temp_color(temp_c))
        buf[a + 1:a + 4] = rgb
        buf[a + 5:a + 8] = rgb
        buf[SAVE_BYTE] = 0
        self.dev.write(buf)

    def describe(self) -> str:
        buf = self.dev.read()
        out = [f"zone@{o}: {EFFECT_NAMES.get(buf[o], hex(buf[o]))} #{bytes(buf[o + 1:o + 4]).hex()}"
               for o in EFFECT_OFFSETS]
        out.append(f"animated zone control byte: {buf[STRIP_CONTROL]:02x}")
        return "\n".join(out)
