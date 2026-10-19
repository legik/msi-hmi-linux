import struct

import pytest

from hmid.panel import protocol as P
from hmid.panel.device import Panel


class FakeTransport:
    """Records what the host sends and answers queries like the real panel."""

    def __init__(self):
        self.sent = []                  # ("cmd", cmd, payload, length) | ("data", packet)
        self.display = {}               # mode -> GetDisplay reply bytes
        self.events = []
        self._pending = None

    def control_out(self, pkt):
        cmd = pkt[3]
        length = struct.unpack_from("<I", pkt, 5)[0]
        self.sent.append(("cmd", cmd, bytes(pkt[9:]), length))
        if cmd == P.Cmd.GET_DISPLAY:
            self._pending = (cmd + 1, self.display.get(pkt[9], bytes([0, 0, 0, 0])))
        elif cmd == P.Cmd.GET_DEVICE_INFO:
            self._pending = (cmd + 1, bytes([0, 0x26, 1, 0x24, 50]))
        elif cmd == P.Cmd.GET_DEVICE_ID:
            self._pending = (cmd + 1, bytes([9, 4, 0, 0]))

    def control_in(self):
        if not self._pending:
            return bytes(64)
        cmd, data = self._pending
        self._pending = None
        return (b"\x6B\x5A" + bytes([cmd, 0]) + struct.pack("<I", len(data)) + data).ljust(64, b"\0")

    def read_event(self, timeout):
        return self.events.pop(0) if self.events else None

    def write_data(self, pkt):
        self.sent.append(("data", bytes(pkt)))

    def close(self):
        pass

    # ---- helpers for assertions -----------------------------------------------
    def commands(self):
        return [s for s in self.sent if s[0] == "cmd"]

    def script(self):
        """Readable sequence: text messages, display switches, uploads, queries."""
        out = []
        for s in self.sent:
            if s[0] == "data":
                continue
            _, cmd, body, length = s
            if cmd == P.Cmd.HOST_MSG:
                out.append("msg " + body.rstrip(b"\0").decode())
            elif cmd == P.Cmd.SET_DISPLAY:
                out.append(f"display {body[0]} sub={body[1]} " + body[3:3 + body[2]].hex())
            elif cmd == P.Cmd.FILE_NODE:
                out.append("upload " + body[4:length].decode())
            elif cmd == P.Cmd.GET_DISPLAY:
                out.append(f"get_display {body[0]}")
            elif cmd in (P.Cmd.START_DATA, P.Cmd.END_DATA):
                continue
            else:
                out.append(f"cmd {cmd}")
        return out


@pytest.fixture
def fake():
    return FakeTransport()


@pytest.fixture
def panel(fake):
    return Panel(fake)


@pytest.fixture
def no_sleep(monkeypatch):
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
