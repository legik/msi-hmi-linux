"""Web requests for layouts (http sources, pictures), optionally through a proxy.

    "proxy": "socks5h://127.0.0.1:1080"     in /etc/hmid.json, for every request
    "proxy": false / "socks5://…"            on a single layout source, to skip or override it

socks5h:// resolves host names through the proxy (use this when DNS is filtered too),
socks5:// resolves them here. user:password@ in the address is sent as SOCKS5 login.
http:// and https:// are ordinary HTTP proxies. No extra package is needed: SOCKS5 is
spoken directly (RFC 1928, login RFC 1929).
"""
from __future__ import annotations

import functools
import http.client
import ipaddress
import socket
import ssl
import struct
import time
import urllib.error
import urllib.request
from urllib.parse import unquote, urlsplit

from . import __version__

SCHEMES = ("socks5", "socks5h", "http", "https")
_default = None                 # proxy for every request (from the config), None = direct
_log = None                     # set_logger(): one line per request (where it went, how it ended)


def set_logger(fn):
    global _log
    _log = fn


def _short(url):
    return url if len(url) <= 80 else url[:55] + "…" + url[-20:]


def _size(n):
    return f"{n} B" if n < 1024 else f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 2**20:.1f} MB"


def parse(proxy: str) -> dict:
    """'socks5h://user:pw@host:1080' -> parts; ValueError for anything unusable."""
    u = urlsplit(proxy)
    if u.scheme not in SCHEMES:
        raise ValueError(f"proxy must start with {', '.join(s + '://' for s in SCHEMES)}")
    if not u.hostname:
        raise ValueError("proxy has no host")
    try:
        port = u.port
    except ValueError:
        raise ValueError("proxy port must be a number") from None
    port = port or {"socks5": 1080, "socks5h": 1080, "http": 8080, "https": 443}[u.scheme]
    return {"scheme": u.scheme, "host": u.hostname, "port": port,
            "user": unquote(u.username) if u.username else None,
            "password": unquote(u.password) if u.password else ""}


def describe(proxy) -> str:
    """For the log: the address without the password."""
    if not proxy:
        return "direct"
    p = parse(proxy)
    who = f"{p['user']}@" if p["user"] else ""
    return f"{p['scheme']}://{who}{p['host']}:{p['port']}"


def set_default(proxy: str | None):
    global _default
    if proxy:
        parse(proxy)
    _default = proxy or None


def get(url: str, headers: dict | None = None, timeout: float = 10, limit: int = 1024 * 1024,
        proxy="default") -> bytes:
    """GET url and return at most `limit` bytes. proxy: "default" (the configured one),
    None/False (direct) or a proxy address."""
    if proxy == "default":
        proxy = _default
    req = urllib.request.Request(url, headers={"User-Agent": f"hmid/{__version__}", **(headers or {})})
    via = f"via {describe(proxy)}" if proxy else "direct"
    t = time.monotonic()
    try:
        with opener(proxy or None).open(req, timeout=timeout) as r:
            data = r.read(limit)
            if _log:
                kind = (r.headers.get_content_type() or "") if r.headers else ""
                _log(f"web GET {_short(url)} {via} -> {r.status} {kind} {_size(len(data))} "
                     f"in {time.monotonic() - t:.2f} s")
            return data
    except Exception as e:
        if _log:
            reason = f"HTTP {e.code} {e.reason}" if isinstance(e, urllib.error.HTTPError) else \
                str(getattr(e, "reason", None) or e) or type(e).__name__
            _log(f"web GET {_short(url)} {via} -> failed after {time.monotonic() - t:.2f} s: {reason}")
        raise


@functools.lru_cache(maxsize=8)
def opener(proxy: str | None) -> urllib.request.OpenerDirector:
    if not proxy:
        # ignore http_proxy & co. from the environment: the config decides
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    p = parse(proxy)
    if p["scheme"] in ("http", "https"):
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _SocksHTTP(p), _SocksHTTPS(p))


# ---- SOCKS5 ---------------------------------------------------------------------------
_REPLIES = {1: "general failure", 2: "not allowed by the proxy's rules", 3: "network unreachable",
            4: "host unreachable", 5: "connection refused", 6: "TTL expired",
            7: "command not supported", 8: "address type not supported"}


class ProxyError(OSError):
    pass


def _recv(s: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise ProxyError("SOCKS proxy closed the connection")
        buf += chunk
    return buf


def socks_connect(p: dict, host: str, port: int, timeout=None) -> socket.socket:
    """A TCP connection to host:port through the SOCKS5 proxy p (from parse())."""
    s = socket.create_connection((p["host"], p["port"]), timeout=timeout)
    try:
        methods = b"\x00\x02" if p["user"] else b"\x00"
        s.sendall(b"\x05" + bytes([len(methods)]) + methods)
        ver, method = _recv(s, 2)
        if ver != 5:
            raise ProxyError("not a SOCKS5 proxy")
        if method == 2:
            user, pw = p["user"].encode(), p["password"].encode()
            s.sendall(b"\x01" + bytes([len(user)]) + user + bytes([len(pw)]) + pw)
            if _recv(s, 2)[1] != 0:
                raise ProxyError("SOCKS proxy rejected the user name or password")
        elif method != 0:
            raise ProxyError("SOCKS proxy wants a login" if method == 0xFF and not p["user"]
                             else "SOCKS proxy accepts none of our login methods")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
            if p["scheme"] == "socks5":                 # resolve here
                ip = ipaddress.ip_address(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][4][0])
        if ip is None:                                  # socks5h: the proxy resolves the name
            name = host.encode("idna")
            addr = b"\x03" + bytes([len(name)]) + name
        else:
            addr = (b"\x01" if ip.version == 4 else b"\x04") + ip.packed
        s.sendall(b"\x05\x01\x00" + addr + struct.pack(">H", port))
        _, rep, _, atyp = _recv(s, 4)
        if rep != 0:
            raise ProxyError(f"SOCKS proxy could not reach {host}:{port}: {_REPLIES.get(rep, f'error {rep}')}")
        _recv(s, {1: 4, 4: 16}.get(atyp) or _recv(s, 1)[0])   # bound address
        _recv(s, 2)                                            # bound port
        return s
    except BaseException:
        s.close()
        raise


class _SocksConnection(http.client.HTTPConnection):
    def __init__(self, *a, socks, **kw):
        super().__init__(*a, **kw)
        self._socks = socks

    def connect(self):
        self.sock = socks_connect(self._socks, self.host, self.port, self.timeout)


class _SocksTLSConnection(http.client.HTTPSConnection):
    def __init__(self, *a, socks, **kw):
        super().__init__(*a, **kw)
        self._socks = socks

    def connect(self):
        sock = socks_connect(self._socks, self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _SocksHTTP(urllib.request.HTTPHandler):
    def __init__(self, p):
        super().__init__()
        self._p = p

    def http_open(self, req):
        return self.do_open(functools.partial(_SocksConnection, socks=self._p), req)


class _SocksHTTPS(urllib.request.HTTPSHandler):
    def __init__(self, p):
        super().__init__(context=ssl.create_default_context())
        self._p = p

    def https_open(self, req):
        return self.do_open(functools.partial(_SocksTLSConnection, socks=self._p), req, context=self._context)
