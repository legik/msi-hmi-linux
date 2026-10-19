"""hmid-helper: the small root part of hmid (see privileged.py).

It answers only the operations in privileged.OPS, only to root and the hmid user, and never
runs a command it was sent: touch actions come from /etc/hmid.json and layout commands from
root-owned layout files in the built-in folder or /etc/hmid/layouts, read here.
"""
from __future__ import annotations

import base64
import json
import os
import pwd
import socket
import socketserver
import struct
import sys
import threading

from .privileged import OPS, SOCKET

_lock = threading.Lock()
_actions = None


def log(*a):
    print(*a, flush=True)


def _get_actions():
    global _actions
    with _lock:
        if _actions is None:
            from .actions import Actions
            _actions = Actions({}, log=log)
        from . import config
        from .actions import DEFAULT_ACTIONS
        conf = config.load(warn=lambda *a: None)
        _actions.map = {**DEFAULT_ACTIONS, **{int(k): v for k, v in conf["touch_actions"].items()}}
        return _actions


# actions the helper runs for hmid: commands, and the alarm (sound and notification in the
# desktop session). Everything else (lights, themes, Free Up Memory's reply) stays in hmid.
_HELPER_ACTIONS = ("user:", "root:", "builtin:timer_alarm", "builtin:timer_stop")


def run_action(item: int) -> str:
    acts = _get_actions()
    action = acts.map.get(item, "none")
    if not action.startswith(_HELPER_ACTIONS):
        return f"not a helper action: {action}"
    log(f"action {item}: {action}")
    threading.Thread(target=acts.run, args=(action, item), daemon=True).start()
    return action


def run_source(layout_path: str, name: str) -> bytes:
    """A layout's command source, read from the root-owned layout file itself."""
    from .layouts import BUILTIN, DIR, trusted, validate
    from .layouts.sources import Source
    real = os.path.realpath(layout_path)
    allowed = {os.path.realpath(BUILTIN), os.path.realpath(DIR)}
    if os.path.dirname(real) not in allowed or not real.endswith(".json"):
        raise PermissionError(f"{layout_path}: layouts with commands must be in {DIR}")
    if not trusted(real):
        raise PermissionError(f"{layout_path}: commands only run from layout files only root can change")
    with open(real) as f:
        data = json.load(f)
    if validate(data):
        raise ValueError(f"{layout_path} has errors")
    spec = (data.get("sources") or {}).get(name)
    if not isinstance(spec, dict) or spec.get("type") != "command":
        raise ValueError(f"{layout_path} has no command source '{name}'")
    return Source(name, spec, allow_commands=True, log=log).fetch_local()


def do(op: str, args: list[str]):
    if op == "action":
        return run_action(int(args[0]))
    if op == "alarm-stop":
        _get_actions().alarm.stop()
        return "ok"
    if op == "source":
        return run_source(args[0], args[1])
    if op == "drop-caches":
        with open("/proc/sys/vm/drop_caches", "w") as f:
            f.write("3\n")
        return "ok"
    if op == "ram-clock":
        from .sensors import memory
        return memory.dmidecode_mhz()
    if op == "usb-cycle":
        from .panel import recovery
        return recovery.cycle_port(log)
    if op == "cpu-energy":
        from .sensors.cpu import RAPL
        with open(RAPL) as f:
            return int(f.read().strip())
    raise ValueError(f"unknown operation {op!r}")


def _peer_uid(sock) -> int:
    creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", creds)[1]


def serve(path: str = SOCKET, allowed_uids: set[int] | None = None):
    if allowed_uids is None:
        allowed_uids = {0}
        try:
            allowed_uids.add(pwd.getpwnam("hmid").pw_uid)
        except KeyError:
            log("warning: no 'hmid' user - only root can use the helper")

    class H(socketserver.StreamRequestHandler):
        def handle(self):
            uid = _peer_uid(self.request)
            try:
                if uid not in allowed_uids:
                    raise PermissionError(f"uid {uid} may not use hmid-helper")
                req = json.loads(self.rfile.readline())
                op, args = req.get("op"), req.get("args") or []
                if op not in OPS or not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                    raise ValueError("bad request")
                out = do(op, args)
                r = {"ok": True, "b64": True, "out": base64.b64encode(out).decode()} if isinstance(out, bytes) \
                    else {"ok": True, "out": out}
            except Exception as e:                  # answer, never die
                r = {"ok": False, "error": str(e) or type(e).__name__}
            self.wfile.write((json.dumps(r) + "\n").encode())

    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    srv = socketserver.ThreadingUnixStreamServer(path, H)
    srv.daemon_threads = True
    os.chmod(path, 0o660)                   # root and the hmid group (the unit runs with Group=hmid)
    log(f"hmid-helper ready on {path}")
    srv.serve_forever()


def main():
    if os.geteuid() != 0:
        print("hmid-helper must run as root (it is started by systemd)", file=sys.stderr)
        return 1
    serve()
    return 0
