"""The few things hmid needs root for, done by hmid-helper.

hmid runs as its own user ("hmid") with access to just its two USB devices. Anything that
needs root goes through the helper's socket as a fixed operation with references, never a
command line: "action 242" (the helper looks the command up in /etc/hmid.json itself),
"source <layout file> <name>" (the helper reads the command from the root-owned layout).

When hmid itself runs as root (older installs, development), the operations are done
directly in this process instead.
"""
from __future__ import annotations

import base64
import json
import os
import socket

SOCKET = "/run/hmid-helper/helper.sock"
OPS = ("action", "alarm-stop", "source", "drop-caches", "ram-clock", "usb-cycle", "cpu-energy")


class HelperError(OSError):
    pass


def direct() -> bool:
    """True when this process may do the privileged work itself."""
    return os.geteuid() == 0


def call(op: str, *args, timeout: float = 30, path: str | None = None):
    """Run one privileged operation and return its result (bytes for "source")."""
    if op not in OPS:
        raise ValueError(f"unknown privileged operation {op!r}")
    if path is None and direct():
        from . import helper
        return helper.do(op, [str(a) for a in args])
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path or SOCKET)
    except PermissionError:
        s.close()
        raise HelperError("no access to hmid-helper (only root and the hmid user)") from None
    except OSError as e:
        s.close()
        raise HelperError(f"hmid-helper is not running ({e}); check: systemctl status hmid-helper") from None
    with s:
        s.sendall((json.dumps({"op": op, "args": [str(a) for a in args]}) + "\n").encode())
        line = s.makefile("rb").readline()
    try:
        r = json.loads(line)
    except ValueError:
        raise HelperError(f"hmid-helper gave no answer to {op}") from None
    if not r.get("ok"):
        raise HelperError(r.get("error") or f"{op} failed")
    out = r.get("out")
    return base64.b64decode(out) if r.get("b64") else out
