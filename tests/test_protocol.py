import struct

import pytest

from hmid.panel import protocol as P


def test_command_packet_layout():
    pkt = P.command(P.Cmd.SET_BACKLIGHT, struct.pack("<I", 50))
    assert len(pkt) == 64
    assert pkt[:9] == bytes([0x01, 0x6B, 0x5A, 24, 0, 4, 0, 0, 0])
    assert pkt[9:13] == bytes([50, 0, 0, 0])
    assert pkt[13:] == bytes(51)


def test_command_explicit_length_and_limit():
    pkt = P.command(P.Cmd.START_DATA, bytes(55), 123456)
    assert struct.unpack_from("<I", pkt, 5)[0] == 123456
    with pytest.raises(ValueError):
        P.command(1, bytes(56))


@pytest.mark.parametrize("off", [0, 1])
def test_parse_reply_offsets(off):
    buf = bytes(off) + b"\x6B\x5A" + bytes([21, 0]) + struct.pack("<I", 3) + b"abc"
    assert P.parse_reply(buf.ljust(64, b"\0"), 21) == b"abc"
    assert P.parse_reply(buf.ljust(64, b"\0"), 83) is None


def test_data_packets():
    data = bytes(range(256)) * 9            # 2304 bytes -> 3 packets
    pk = list(P.data_packets(data))
    assert len(pk) == 3 and all(len(p) == 1024 and p[0] == 2 for p in pk)
    assert b"".join(p[1:] for p in pk)[:len(data)] == data


def test_file_node():
    payload, n = P.file_node(1000, "M25-S0-O-R000.png")
    assert n == 4 + 17 and len(payload) == 55
    assert struct.unpack_from("<I", payload)[0] == 1000 and payload[4:21] == b"M25-S0-O-R000.png"


def test_set_display_payload():
    assert P.set_display(7, bytes([2, 2]) + bytes(14), sub=2)[:5] == bytes([7, 2, 16, 2, 2])
    assert len(P.set_display(25)) == 19


def test_hw_values_split():
    a, b = P.hw_values(list(range(27)))
    assert struct.unpack("<16H", a) == tuple(range(16))
    assert len(b) == 32 and struct.unpack_from("<11H", b) == tuple(range(16, 27))
    a, _ = P.hw_values([70000, -5])
    assert struct.unpack_from("<2H", a) == (0xFFFF, 0)


def test_text_messages():
    assert P.Msg.last_hwmon(25) == "55AASETLASTHWM255AA5"
    assert P.Msg.last_hwmon(0) == "55AASETLASTHWM005AA5"
    assert P.Msg.memory(6298) == "55AAMEMORY4_062985AA5"
    assert P.Msg.memory(12345) == "55AAMEMORY5_123455AA5"
    assert P.Msg.mode_status(8, 1) == "55AAMODESTATUS08_15AA5"
    with pytest.raises(ValueError):
        P.text("x" * 47)


def test_handshake_keeps_msi_center_flag():
    hs = P.handshake(user_scenario=False, mystic_light=True)
    assert "55AAMODESTATUS08_15AA5" in hs          # 0 makes the panel ask for MSI Center
    assert "55AAMODESTATUS13_05AA5" in hs and "55AAMODESTATUS17_15AA5" in hs


def test_parse_event():
    buf = bytes([1, 7, 60, 1]) + struct.pack("<HH", 240, 400) + bytes(56)
    ev = P.parse_event(buf)
    assert (ev.counter, ev.item, ev.flag, ev.x, ev.y) == (7, 60, 1, 240, 400)
    assert P.parse_event(bytes([2]) + bytes(63)) is None
    assert P.parse_event(None) is None


def test_dynamic_ready_guard():
    assert P.dynamic_ready(bytes([1, 0, 0, 1]))
    assert not P.dynamic_ready(bytes([1, 0, 0, 0]))
    assert not P.dynamic_ready(bytes([0, 0, 0, 1]))
    assert not P.dynamic_ready(None)
