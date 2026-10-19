"""Web requests through a proxy: a small SOCKS5 server and an HTTP server in the test."""
import http.server
import socket
import socketserver
import struct
import threading

import pytest

from hmid import net
from hmid.config import load
from hmid.layouts import validate


class _Web(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def do_GET(self):
        _Web.seen.append(self.path)
        body = b"hello " + self.path.encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _serve(handler):
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Socks5(socketserver.BaseRequestHandler):
    """Minimal SOCKS5 (RFC 1928/1929): records what the client asked for, then relays."""
    login = None            # (user, password) to require a login
    refuse = False          # answer "connection refused"
    log: list = []

    def handle(self):
        c = self.request
        n = c.recv(2)[1]
        methods = c.recv(n)
        if self.login:
            if 2 not in methods:
                c.sendall(b"\x05\xff")
                return
            c.sendall(b"\x05\x02")
            c.recv(1)
            user = c.recv(c.recv(1)[0]).decode()
            pw = c.recv(c.recv(1)[0]).decode()
            ok = (user, pw) == self.login
            c.sendall(b"\x01" + (b"\x00" if ok else b"\x01"))
            if not ok:
                return
        else:
            c.sendall(b"\x05\x00")
        _, cmd, _, atyp = c.recv(4)
        if atyp == 3:
            host = c.recv(c.recv(1)[0]).decode()
            Socks5.log.append(("name", host))
        else:
            raw = c.recv(4 if atyp == 1 else 16)
            host = socket.inet_ntop(socket.AF_INET if atyp == 1 else socket.AF_INET6, raw)
            Socks5.log.append(("ip", host))
        port = struct.unpack(">H", c.recv(2))[0]
        if self.refuse:
            c.sendall(b"\x05\x05\x00\x01" + bytes(6))
            return
        target = socket.create_connection(("127.0.0.1" if host == "web.test" else host, port))
        c.sendall(b"\x05\x00\x00\x01" + bytes(6))
        _relay(c, target)


def _relay(a, b):
    def pump(src, dst):
        try:
            while data := src.recv(65536):
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
    t = threading.Thread(target=pump, args=(b, a), daemon=True)
    t.start()
    pump(a, b)
    t.join(5)


@pytest.fixture
def web():
    srv = _serve(_Web)
    _Web.seen = []
    yield srv.server_address[1]
    srv.shutdown()


@pytest.fixture
def socks():
    Socks5.login, Socks5.refuse, Socks5.log = None, False, []
    srv = _serve(Socks5)
    yield srv.server_address[1]
    srv.shutdown()
    net.set_default(None)


def test_parse_and_describe():
    p = net.parse("socks5h://me:p%40ss@10.0.0.1:9050")
    assert (p["scheme"], p["host"], p["port"], p["user"], p["password"]) == ("socks5h", "10.0.0.1", 9050, "me", "p@ss")
    assert net.parse("socks5://host")["port"] == 1080
    assert net.describe("socks5h://me:secret@h:1") == "socks5h://me@h:1"          # no password in the log
    assert net.describe(None) == "direct"
    for bad in ("socks4://h:1", "h:1080", "socks5://:1080", "socks5://h:port"):
        with pytest.raises(ValueError):
            net.parse(bad)


def test_socks5h_sends_the_name_to_the_proxy(web, socks):
    out = net.get(f"http://web.test:{web}/a", proxy=f"socks5h://127.0.0.1:{socks}")
    assert out == b"hello /a" and Socks5.log == [("name", "web.test")]   # web.test only exists for the proxy


def test_socks5_resolves_here(web, socks):
    assert net.get(f"http://localhost:{web}/b", proxy=f"socks5://127.0.0.1:{socks}") == b"hello /b"
    assert Socks5.log[0][0] == "ip"


def test_socks_login(web, socks):
    Socks5.login = ("me", "pw")
    assert net.get(f"http://web.test:{web}/c", proxy=f"socks5h://me:pw@127.0.0.1:{socks}") == b"hello /c"
    with pytest.raises(OSError, match="rejected the user name"):
        net.get(f"http://web.test:{web}/c", proxy=f"socks5h://me:nope@127.0.0.1:{socks}")
    with pytest.raises(OSError, match="wants a login"):
        net.get(f"http://web.test:{web}/c", proxy=f"socks5h://127.0.0.1:{socks}")


def test_socks_refusal_is_explained(web, socks):
    Socks5.refuse = True
    with pytest.raises(OSError, match="could not reach web.test.*connection refused"):
        net.get(f"http://web.test:{web}/d", proxy=f"socks5h://127.0.0.1:{socks}")


def test_default_proxy_and_per_source_override(web, socks):
    net.set_default(f"socks5h://127.0.0.1:{socks}")
    assert net.get(f"http://web.test:{web}/e") == b"hello /e" and len(Socks5.log) == 1
    assert net.get(f"http://127.0.0.1:{web}/f", proxy=False) == b"hello /f" and len(Socks5.log) == 1  # direct
    with pytest.raises(ValueError):
        net.set_default("ftp://x")


def test_requests_are_logged(web, socks):
    logs = []
    net.set_logger(logs.append)
    try:
        net.get(f"http://web.test:{web}/ok", proxy=f"socks5h://u:secret@127.0.0.1:{socks}")
        assert f"web GET http://web.test:{web}/ok via socks5h://u@127.0.0.1:{socks} -> 200" in logs[0]
        assert "secret" not in logs[0] and " B in " in logs[0]
        Socks5.refuse = True
        with pytest.raises(OSError):
            net.get(f"http://web.test:{web}/no", proxy=f"socks5h://127.0.0.1:{socks}")
        assert "-> failed after" in logs[1] and "connection refused" in logs[1]
        net.set_default(None)
        net.get(f"http://127.0.0.1:{web}/direct")
        assert " direct -> 200 " in logs[2]
    finally:
        net.set_logger(None)


def test_http_proxy(web):
    # a plain HTTP proxy receives the full URL in the request line
    assert net.get("http://anything.test/g", proxy=f"http://127.0.0.1:{web}") == b"hello http://anything.test/g"


def test_layout_source_through_proxy(web, socks):
    from hmid.layouts.sources import Source
    s = Source("x", {"type": "http", "url": f"http://web.test:{web}/h", "proxy": f"socks5h://127.0.0.1:{socks}"},
               allow_commands=False, log=lambda *a: None)
    s.get()
    import time
    end = time.time() + 5
    while s.value is None and time.time() < end:
        time.sleep(0.02)
    assert s.value == "hello /h"


def test_config_and_layout_validation(tmp_path):
    warnings = []
    p = tmp_path / "hmid.json"
    p.write_text('{"proxy": "socks5h://127.0.0.1:1080"}')
    assert load(str(p), warn=warnings.append)["proxy"] == "socks5h://127.0.0.1:1080" and not warnings
    p.write_text('{"proxy": "socks4://127.0.0.1:1080"}')
    assert load(str(p), warn=warnings.append)["proxy"] is None and "proxy" in warnings[0]
    w = [{"type": "divider", "y": 1}]
    assert validate({"widgets": w, "sources": {"a": {"type": "http", "url": "u", "proxy": False}}}) == []
    assert validate({"widgets": w, "sources": {"a": {"type": "http", "url": "u", "proxy": "socks5://h:1"}}}) == []
    assert "or false" in validate({"widgets": w, "sources": {"a": {"type": "http", "url": "u", "proxy": "x"}}})[0]
