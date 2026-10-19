"""Last-resort recovery: logically disable and re-enable the panel's USB port.

Most boards have no real port power switching, so this only resets the connection.
"""
from __future__ import annotations

import glob
import os
import time

from .protocol import PID, VID


def port_disable_file():
    for d in glob.glob("/sys/bus/usb/devices/*"):
        try:
            with open(f"{d}/idVendor") as f:
                vid = f.read().strip()
            with open(f"{d}/idProduct") as f:
                pid = f.read().strip()
        except OSError:
            continue
        if (vid, pid) != (f"{VID:04x}", f"{PID:04x}"):
            continue
        bus, path = os.path.basename(d).split("-", 1)
        if "." in path:
            parent, port = path.rsplit(".", 1)
            f = f"/sys/bus/usb/devices/{bus}-{parent}:1.0/{bus}-{parent}-port{port}/disable"
        else:
            f = f"/sys/bus/usb/devices/{bus}-0:1.0/usb{bus}-port{path}/disable"
        if os.path.exists(f):
            return f
    return None


def cycle_port(log=print):
    from .transport import present
    f = port_disable_file()
    if not f:
        log("could not find the panel's USB port switch; skipping port cycle")
        return False
    with open(f, "w") as fh:
        fh.write("1")
    time.sleep(2)
    with open(f, "w") as fh:
        fh.write("0")
    for _ in range(100):
        time.sleep(0.1)
        if present():
            break
    time.sleep(1.0)
    return True
