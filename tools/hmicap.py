#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Decode HMI panel USB traffic from a USBPcap (Windows) pcapng capture, for protocol research.

    hmicap.py capture.pcapng [timeline]       readable command/reply/event timeline
    hmicap.py capture.pcapng timeline --all   ... including keepalive polls
    hmicap.py capture.pcapng files <outdir>   save every uploaded file

Captures can contain personal data and MSI software traffic: never commit them.
"""
from __future__ import annotations

import collections
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from hmid.panel.protocol import MODE_NAMES, Cmd  # noqa: E402

USBPCAP_HEADER = struct.Struct("<HQIHBHHBBI")      # header len, irp, status, function, info, bus, dev, ep, type, len
TRANSFER_INTERRUPT, TRANSFER_CONTROL = 1, 2


def blocks(path):
    """(timestamp in microseconds, packet) for every Enhanced Packet Block."""
    with open(path, "rb") as f:
        data = f.read()
    i = 0
    while i + 8 <= len(data):
        btype, blen = struct.unpack_from("<II", data, i)
        if btype == 6:
            _, ts_hi, ts_lo, cap, _ = struct.unpack_from("<IIIII", data, i + 8)
            yield (ts_hi << 32) | ts_lo, data[i + 28:i + 28 + cap]
        i += max(blen, 12)


def urbs(path):
    t0, out = None, []
    for ts, p in blocks(path):
        if len(p) < USBPCAP_HEADER.size:
            continue
        hlen, irp, status, _func, info, _bus, dev, ep, ttype, _dlen = USBPCAP_HEADER.unpack_from(p)
        t0 = ts if t0 is None else t0
        out.append(dict(t=(ts - t0) / 1e6, status=status, info=info, dev=dev, ep=ep, type=ttype, data=p[hlen:]))
    return out


def events(path):
    """("SET"|"REPLY"|"DATA"|"IN"|"ERR", time, ...) for the panel's USB device."""
    rs = urbs(path)
    counts = collections.Counter(r["dev"] for r in rs if b"\x6b\x5a" in r["data"][:20])
    if not counts:
        sys.exit("no HMI panel traffic found in this capture")
    dev = counts.most_common(1)[0][0]
    out, want_reply = [], False
    for r in (r for r in rs if r["dev"] == dev):
        d, t = r["data"], r["t"]
        if r["type"] == TRANSFER_CONTROL and r["info"] == 0 and len(d) >= 8:
            if d[0] == 0x21 and d[1] == 0x09 and len(d) >= 17 and d[9:11] == b"\x6b\x5a":
                out.append(("SET", t, d[11], struct.unpack_from("<I", d, 13)[0], d[17:]))
            elif d[0] == 0xA1 and d[1] == 0x01:
                want_reply = True
        elif r["type"] == TRANSFER_CONTROL and r["info"] == 1 and want_reply and len(d) >= 8:
            want_reply = False
            if d[:2] == b"\x6b\x5a":
                n = struct.unpack_from("<I", d, 4)[0]
                out.append(("REPLY", t, d[2], n, d[8:8 + n]))
        elif r["ep"] == 0x02 and r["info"] == 0 and d:
            out.append(("DATA", t, d))
        elif r["ep"] == 0x81 and r["info"] == 1 and len(d) >= 8:
            out.append(("IN", t, d))
        elif r["status"]:
            out.append(("ERR", t, r["ep"], hex(r["status"])))
    return out


def describe(cmd, n, body):
    text = lambda b: b.rstrip(b"\0").decode("ascii", "replace")
    if cmd == Cmd.HOST_MSG:
        return f"MSG  {text(body[:55])}"
    if cmd == Cmd.FILE_NODE:
        return f"FILE size={struct.unpack_from('<I', body)[0]} name={text(body[4:n])}"
    if cmd == Cmd.START_DATA:
        return f"START_DATA len={n}"
    if cmd == Cmd.END_DATA:
        return "END_DATA"
    if cmd == Cmd.SET_DISPLAY:
        name = MODE_NAMES.get(body[0], "?")
        return f"SET_DISPLAY mode={body[0]} ({name}) sub={body[1]} data={body[3:3 + body[2]].hex(' ')}"
    if cmd == Cmd.GET_DISPLAY:
        return f"GET_DISPLAY mode={body[0]}"
    if cmd == Cmd.SET_BACKLIGHT:
        return f"BACKLIGHT {struct.unpack_from('<I', body)[0]}"
    if cmd == Cmd.HOST_TIME:
        fmt, _, epoch = struct.unpack_from("<IfI", body)
        return f"HOST_TIME fmt={fmt} epoch={epoch}"
    if cmd in (Cmd.HW_VALUES_A, Cmd.HW_VALUES_B):
        return f"HW_VALUES_{'A' if cmd == Cmd.HW_VALUES_A else 'B'} {list(struct.unpack_from('<16H', body.ljust(32, bytes(1))))}"
    return f"cmd={cmd} len={n} {body[:min(n, 24)].hex(' ')}"


def timeline(path, polls=False):
    last_in, data_n, data_t0 = None, 0, 0.0
    for e in events(path):
        kind, t = e[0], e[1]
        if kind == "DATA":
            data_t0 = t if data_n == 0 else data_t0
            data_n += 1
            continue
        if data_n:
            print(f"{data_t0:9.3f}   DATA x{data_n} ({t - data_t0:.2f}s)")
            data_n = 0
        if kind == "SET" and (polls or e[2] != Cmd.GET_DISPLAY):
            print(f"{t:9.3f} > {describe(e[2], e[3], e[4])}")
        elif kind == "REPLY" and (polls or e[2] != Cmd.GET_DISPLAY + 1):
            print(f"{t:9.3f} <   reply {e[2]} {e[4].hex(' ')}")
        elif kind == "IN" and e[2][2:8] != last_in:
            last_in = e[2][2:8]
            x, y = struct.unpack_from("<HH", e[2], 4)
            print(f"{t:9.3f}   IN item={e[2][2]} flag={e[2][3]} x={x} y={y}")
        elif kind == "ERR":
            print(f"{t:9.3f}   ERR ep={e[2]:#x} status={e[3]}")


def extract_files(path, outdir):
    os.makedirs(outdir, exist_ok=True)
    name, buf, size = None, b"", 0
    for e in events(path):
        if e[0] == "SET" and e[2] == Cmd.FILE_NODE:
            size = struct.unpack_from("<I", e[4])[0]
            name, buf = e[4][4:e[3]].decode("ascii", "replace"), b""
        elif e[0] == "DATA" and name:
            buf += e[2][1:]
        elif e[0] == "SET" and e[2] == Cmd.END_DATA and name:
            out = os.path.join(outdir, f"{e[1]:08.3f}_{os.path.basename(name)}")
            with open(out, "wb") as f:
                f.write(buf[:size])
            print(f"{e[1]:9.3f} {name} {size} bytes -> {out}")
            name = None


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path, mode = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "timeline")
    if mode == "timeline":
        timeline(path, polls="--all" in sys.argv)
    elif mode == "files" and len(sys.argv) > 3:
        extract_files(path, sys.argv[3])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
