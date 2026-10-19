"""High-level panel API: the commands MSI Center uses, nothing else.

Firmware update, rescue mode, file delete and settings-save commands exist in MSI's
software but are deliberately not implemented.
"""
from __future__ import annotations

import time

from . import protocol as P
from .protocol import Cmd, Mode


class Panel:
    def __init__(self, transport, verbose=False):
        self.t = transport
        self.verbose = verbose
        self.last_cmd = None

    @classmethod
    def open(cls, verbose=False):
        from .transport import UsbTransport
        return cls(UsbTransport(), verbose)

    def close(self):
        self.t.close()

    # ---- transport -----------------------------------------------------------
    def send(self, cmd, payload=b"", length=None):
        pkt = P.command(cmd, payload, length)
        if self.verbose:
            print("  >>", pkt[:24].hex(" "))
        self.last_cmd = (int(cmd), bytes(payload)[:24])
        self.t.control_out(pkt)

    def reply(self, want, tries=10):
        for _ in range(tries):
            buf = self.t.control_in()
            if self.verbose:
                print("  <<", buf[:24].hex(" "))
            r = P.parse_reply(buf, want)
            if r is not None:
                return r
        return None

    def read_event(self, timeout=0.2) -> P.Event | None:
        return P.parse_event(self.t.read_event(timeout))

    def read_raw_event(self, timeout=0.2) -> bytes | None:
        return self.t.read_event(timeout)

    def describe_last(self):
        if not self.last_cmd:
            return "none"
        cmd, body = self.last_cmd
        if cmd == Cmd.HOST_MSG:
            return "msg " + body.rstrip(b"\0").decode("ascii", "replace")
        if cmd == -1:
            return "file data packet"
        return f"cmd {cmd} {body[:8].hex(' ')}"

    # ---- queries ---------------------------------------------------------------
    def msg(self, text):
        self.send(Cmd.HOST_MSG, P.text(text), P.MAX_PAYLOAD)

    def lcid(self):
        self.msg(P.Msg.GET_LCID)
        self.send(Cmd.GET_DEVICE_ID, bytes(4))
        return self.reply(Cmd.GET_DEVICE_ID + 1)

    def version(self):
        self.msg(P.Msg.GET_VERSION)
        self.send(Cmd.GET_DEVICE_ID, bytes(4))
        return self.reply(Cmd.GET_DEVICE_ID + 1)

    def device_info(self):
        self.send(Cmd.GET_DEVICE_INFO, bytes(4))
        return self.reply(Cmd.GET_DEVICE_INFO + 1)

    def get_display(self, mode=Mode.DYNAMIC):
        self.send(Cmd.GET_DISPLAY, bytes([mode]))
        return self.reply(Cmd.GET_DISPLAY + 1)

    def active(self, mode) -> bool:
        return P.display_active(self.get_display(mode))

    # ---- control -------------------------------------------------------------------
    def set_display(self, mode, data=b"\x01", sub=0):
        self.send(Cmd.SET_DISPLAY, P.set_display(mode, data, sub), 19)

    def brightness(self, pct):
        import struct
        self.send(Cmd.SET_BACKLIGHT, struct.pack("<I", max(0, min(100, int(pct)))))

    def sync_time(self, fmt24=True):
        self.send(Cmd.HOST_TIME, P.host_time(fmt24))

    def clock(self, style=0, fmt24=True):
        self.sync_time(fmt24)
        d = bytearray(10)
        d[max(0, min(9, style))] = 1
        self.set_display(Mode.CLOCK, d)

    def handshake(self, user_scenario=False, mystic_light=True):
        for m in P.handshake(user_scenario, mystic_light):
            self.msg(m)

    def hw_values(self, values):
        a, b = P.hw_values(values)
        self.send(Cmd.HW_VALUES_A, a)
        self.send(Cmd.HW_VALUES_B, b, 32)

    def upload(self, data: bytes, name: str):
        """File upload exactly like MSI: node -> start -> 1023-byte chunks -> end."""
        node, n = P.file_node(len(data), name)
        self.send(Cmd.FILE_NODE, node, n)
        self.send(Cmd.START_DATA, bytes(P.MAX_PAYLOAD), len(data))
        for pkt in P.data_packets(data):
            self.last_cmd = (-1, pkt[:8])
            self.t.write_data(pkt)
        self.send(Cmd.END_DATA, bytes(P.MAX_PAYLOAD), 0)

    def show_picture(self, data: bytes | None = None, ext: str = ".png", slot: int = P.PICTURE_SLOT):
        """MSI's Set_SOLED_UploadGIF: loading -> upload to the slot -> picture mode on that slot.
        data=None shows what the slot already holds (slots 0-5: the panel's built-in pictures)."""
        self.set_display(Mode.LOADING)
        time.sleep(0.2)
        if data is not None:
            self.upload(data, P.picture_name(slot, ext))
        self.set_display(Mode.PICTURE, P.picture_select(slot))

    def show_video(self, data: bytes, slot: int = P.PICTURE_SLOT):
        """An animated picture (H.264 AVI), as MSI does it: loading, delete the slot's still
        pictures (they would win over the video), upload M1-S7-V-R0.avi, picture mode."""
        self.msg(P.Msg.SET_TEMP)
        self.set_display(Mode.LOADING)
        time.sleep(0.2)
        for name in P.deletable(slot):
            payload, n = P.delete_payload(name)
            self.send(Cmd.DELETE_FILE, payload, n)
            time.sleep(1.0)                      # MSI waits 1 s after each delete
        self.upload(data, P.video_name(slot))
        self.set_display(Mode.PICTURE, P.picture_select(slot))

    def power_screen(self, mode, backlight_off=False):
        self.set_display(mode, b"\x01\x01" if mode == Mode.SLEEP else b"\x01")
        if backlight_off:
            time.sleep(0.3)
            self.brightness(0)
