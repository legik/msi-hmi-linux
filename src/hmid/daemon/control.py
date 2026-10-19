"""Control socket: one text command per connection, one line back ("ok", "error ...",
or JSON). Used by `hmictl`, the systemd sleep hook and (later) a GUI."""
from __future__ import annotations

import os
import shlex
import socket
import socketserver

SOCKET = "/run/hmid/control.sock"       # /run/hmid is made by systemd for the hmid user
OLD_SOCKET = "/run/hmid.sock"           # before hmid had its own user


def serve(handler, path: str = SOCKET):
    class H(socketserver.StreamRequestHandler):
        def handle(self):
            line = self.rfile.readline().decode(errors="replace").strip()
            try:
                out = handler(line)
            except Exception as e:          # never kill the server thread
                out = f"error {e}"
            self.wfile.write((out + "\n").encode())

    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    srv = socketserver.ThreadingUnixStreamServer(path, H)
    os.chmod(path, 0o660)                  # root and the hmid group only
    srv.daemon_threads = True
    srv.serve_forever()


def request(args, path: str | None = None, timeout: float = 120) -> str:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    if path:
        s.connect(path)
    else:
        try:
            s.connect(SOCKET)
        except FileNotFoundError:
            s.connect(OLD_SOCKET)                            # an older hmid still running
    with s:
        s.sendall((shlex.join(args) + "\n").encode())     # quoted: file names with spaces stay whole
        return s.makefile().read().strip()                  # the whole answer, however many lines
