"""Wire format of the MSI HMI 2.0 panel (USB 1462:922c, "MS-B922C").

Pure functions only (no I/O), so everything here is unit-testable.
See docs/PROTOCOL.md for the full description.

    command   host -> panel  USB control SET_REPORT (0x21, 0x09, wValue 0x0201), 64 bytes
              01 6B 5A <cmd> 00 <u32 LE length> <payload, max 55 bytes>
    reply     panel -> host  USB control GET_REPORT (0xA1, 0x01, wValue 0x0101), 64 bytes
              6B 5A <cmd+1> 00 <u32 LE length> <payload>   (sometimes shifted by one byte)
    file data host -> panel  interrupt OUT 0x02, 1024-byte packets: 02 <1023 bytes>
    events    panel -> host  interrupt IN 0x81, 64 bytes:
              01 <counter> <item> <flag> <X u16 LE> <Y u16 LE>
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from enum import IntEnum

VID, PID = 0x1462, 0x922C
WIDTH, HEIGHT = 480, 800

PACKET = 64
MAX_PAYLOAD = 55
DATA_PACKET = 1024
DATA_CHUNK = DATA_PACKET - 1

# USB requests (identical to MSI Center on Windows)
CTRL_OUT = (0x21, 0x09, 0x0201)      # bmRequestType, bRequest (SET_REPORT), wValue
CTRL_IN = (0xA1, 0x01, 0x0101)       # GET_REPORT
EP_DATA_OUT = 0x02
EP_EVENTS_IN = 0x81


class Cmd(IntEnum):
    GET_DEVICE_ID = 16      # reply 17; answers the preceding 55AAGET... text command
    GET_DEVICE_INFO = 20    # reply 21; byte 4 = brightness
    SET_BACKLIGHT = 24      # u32 0..100
    FILE_NODE = 32          # u32 size + ascii file name
    START_DATA = 34         # length field = file size, then data packets on EP 0x02
    END_DATA = 38
    DELETE_FILE = 42        # file name, 32 bytes - only used for slot-7 pictures (see delete_payload)
    HW_VALUES_A = 48        # hardware monitor values 0..15 (16 x u16)
    HW_VALUES_B = 60        # hardware monitor values 16..26 (11 x u16, padded to 32 bytes)
    HOST_TIME = 54          # u32 format, f32 0, u32 local epoch seconds
    WEATHER = 56
    HOST_MSG = 58           # ascii "55AA....5AA5" text commands, 55 bytes
    SET_DISPLAY = 80        # [mode, sub, n, data...] 19 bytes
    GET_DISPLAY = 82        # [mode] -> reply 83, byte 0 = 1 if that screen is showing


class Mode(IntEnum):
    HWMON = 0               # panel-drawn hardware monitor (one sensor per screen)
    PICTURE = 1
    CLOCK = 5
    HWMON_NETWORK = 7       # network page of the panel-drawn monitor
    MAIN_MENU = 8
    NAHIMIC = 11
    VOLUME = 12
    USER_SCENARIO = 13
    MUSIC = 14
    FREE_MEMORY = 15
    COUNTDOWN = 16
    MYSTIC_LIGHT = 17
    GAMING_MODE = 18
    OSD = 19
    SLEEP = 20              # S3
    HIBERNATE = 21          # S4
    SHUTDOWN = 22           # S5
    RESTART = 23
    LOADING = 24
    DYNAMIC = 25            # background video + uploaded 480x800 PNG overlay
    POWER = 26


MODE_NAMES = {
    Mode.HWMON: "hw-monitor", Mode.PICTURE: "picture", Mode.CLOCK: "clock",
    Mode.HWMON_NETWORK: "hw-monitor-network", Mode.MAIN_MENU: "menu", Mode.NAHIMIC: "nahimic",
    Mode.VOLUME: "volume", Mode.USER_SCENARIO: "user-scenario", Mode.MUSIC: "music",
    Mode.FREE_MEMORY: "free-memory", Mode.COUNTDOWN: "countdown", Mode.MYSTIC_LIGHT: "mystic-light",
    Mode.GAMING_MODE: "gaming-mode", Mode.OSD: "osd", Mode.LOADING: "loading",
    Mode.DYNAMIC: "dynamic", Mode.POWER: "power",
}

# File names the panel firmware expects on the dynamic screen
DYNAMIC_VIDEO = "M25-S0-V-R0.mp4"
DYNAMIC_OVERLAY = "M25-S0-O-R000.png"
PICTURE_SLOT = 7                      # MSI uploads user pictures to slot 7; 0-5 are built-in pictures


def picture_name(slot: int = PICTURE_SLOT, ext: str = ".png", rotated: bool = False) -> str:
    """M1-S<slot>-O-R0.png (R1 for 90/270 degree rotation), as MSI's UploadImage names them."""
    return f"M1-S{slot}-O-R{1 if rotated else 0}{ext}"


def video_name(slot: int = PICTURE_SLOT, ext: str = ".avi") -> str:
    """M1-S<slot>-V-R0.avi - an animated picture (MSI converts GIFs to H.264 AVI)."""
    return f"M1-S{slot}-V-R0{ext}"


def deletable(slot: int = PICTURE_SLOT) -> list[str]:
    """The only files hmid ever deletes: the still pictures of a slot, which MSI removes
    before uploading a video there (a still picture would be shown instead)."""
    return [picture_name(slot, ext) for ext in (".png", ".jpg", ".bmp", ".gif")]


def delete_payload(name: str) -> tuple[bytes, int]:
    if name not in deletable(PICTURE_SLOT):
        raise ValueError(f"refusing to delete {name!r}: only slot-{PICTURE_SLOT} still pictures can be deleted")
    return name.encode("ascii").ljust(32, b"\0"), 32


def picture_select(slot: int) -> bytes:
    """SetDisplay(1) data: 8 bytes, the shown slot set to 1."""
    d = bytearray(8)
    d[slot] = 1
    return bytes(d)


# ---- packets ------------------------------------------------------------------
def command(cmd: int, payload: bytes = b"", length: int | None = None) -> bytes:
    payload = bytes(payload)
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload too long ({len(payload)} > {MAX_PAYLOAD})")
    length = len(payload) if length is None else length
    return (bytes([0x01, 0x6B, 0x5A, cmd, 0]) + struct.pack("<I", length) + payload).ljust(PACKET, b"\0")


def parse_reply(buf: bytes, want: int) -> bytes | None:
    """Payload of reply `want` in a GET_REPORT buffer, or None. The firmware sometimes
    prefixes the report ID, so the header is accepted at offset 0 or 1."""
    for off in (0, 1):
        if len(buf) >= off + 8 and buf[off:off + 2] == b"\x6B\x5A" and buf[off + 2] == want:
            n = struct.unpack_from("<I", buf, off + 4)[0]
            return bytes(buf[off + 8:off + 8 + n])
    return None


def data_packets(data: bytes):
    """File data as 1024-byte interrupt packets: 0x02 + 1023 bytes (zero padded)."""
    for i in range(0, len(data), DATA_CHUNK):
        yield (b"\x02" + data[i:i + DATA_CHUNK]).ljust(DATA_PACKET, b"\0")


def file_node(size: int, name: str) -> tuple[bytes, int]:
    nb = name.encode("ascii")
    if len(nb) > 32:
        raise ValueError("file name too long")
    return (struct.pack("<I", size) + nb).ljust(MAX_PAYLOAD, b"\0"), 4 + len(nb)


def set_display(mode: int, data: bytes = b"\x01", sub: int = 0) -> bytes:
    return (bytes([mode, sub, len(data)]) + bytes(data)).ljust(19, b"\0")


def host_time(fmt24: bool = True, now: float | None = None) -> bytes:
    now = time.time() if now is None else now
    local_epoch = int(now + time.localtime(now).tm_gmtoff)
    return struct.pack("<IfI", 1 if fmt24 else 0, 0.0, local_epoch & 0xFFFFFFFF)


def hw_values(values) -> tuple[bytes, bytes]:
    """27 u16 values for the panel-drawn monitor -> (cmd 48 payload, cmd 60 payload)."""
    v = [max(0, min(int(x), 0xFFFF)) for x in list(values)[:27]]
    v += [0] * (27 - len(v))
    return struct.pack("<16H", *v[:16]), struct.pack("<11H", *v[16:27]).ljust(32, b"\0")


# ---- text commands (cmd 58) -----------------------------------------------------
def text(msg: str) -> bytes:
    b = msg.encode("ascii")
    if len(b) > 46:
        raise ValueError("text command too long")
    return b.ljust(MAX_PAYLOAD, b"\0")


class Msg:
    """The 55AA...5AA5 text commands MSI Center sends."""
    GET_LCID = "55AAGETLCID5AA5"
    GET_VERSION = "55AAGETNANDFATVERSION5AA5"
    SET_TEMP = "55AASETTEMP05AA5"           # sent before switching screens

    @staticmethod
    def last_hwmon(mode: int) -> str:
        """Which screen the panel's own "Hardware Monitor" button opens (0 or 25)."""
        return f"55AASETLASTHWM{mode:d}5AA5" if mode else "55AASETLASTHWM005AA5"

    @staticmethod
    def mode_status(item: int, value: int) -> str:
        return f"55AAMODESTATUS{item:02d}_{value}5AA5"

    @staticmethod
    def memory(freed_mb: int) -> str:
        """Result for the Free Up Memory page, e.g. 55AAMEMORY4_062985AA5."""
        mb = max(0, min(int(freed_mb), 99999))
        return f"55AAMEMORY{5 if mb > 9999 else 4}_{mb:05d}5AA5"


def handshake(user_scenario: bool = False, mystic_light: bool = True) -> list[str]:
    """Status messages MSI Center sends after connecting.
    MODESTATUS08 must stay 1 ("MSI Center present"), otherwise the panel shows
    "install MSI Center". 13 / 17 show or hide the User Scenario / Mystic Light menus."""
    return [
        "55AASCREENSTATUS10_01_0015AA5", "55AASCREENSTATUS10_02_0005AA5",
        Msg.SET_TEMP,
        Msg.mode_status(8, 1), Msg.mode_status(9, 1),
        Msg.mode_status(13, int(user_scenario)), Msg.mode_status(17, int(mystic_light)),
        Msg.mode_status(18, 0), "55AASCREENSTATUS18_00_0015AA5",
        Msg.mode_status(19, 0),
    ]


# ---- events ------------------------------------------------------------------------
@dataclass(frozen=True)
class Event:
    """Status packet from EP 0x81. `item` is the panel's current menu function
    (see actions.items); flag 1 = finger down."""
    counter: int
    item: int
    flag: int
    x: int
    y: int


def parse_event(buf: bytes | None) -> Event | None:
    if not buf or len(buf) < 8 or buf[0] != 1:
        return None
    x, y = struct.unpack_from("<HH", buf, 4)
    return Event(buf[1], buf[2], buf[3], x, y)


def display_active(reply: bytes | None) -> bool:
    """GetDisplay reply: byte 0 == 1 means the queried screen is showing."""
    return bool(reply) and reply[0] == 1


def dynamic_ready(reply: bytes | None) -> bool:
    """GetDisplay(25) reply: MSI only uploads an overlay when bytes 0 and 3 are 1.
    Uploading onto any other page (e.g. the countdown alarm) freezes the firmware."""
    return bool(reply) and len(reply) > 3 and reply[0] == 1 and reply[3] == 1
