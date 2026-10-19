"""Custom data sources for layouts: a command, a file, or a web address (JSON or text).

    "sources": {
      "subs":    {"type": "http", "url": "https://...", "json": "items.0.statistics.subscriberCount", "every": 300},
      "weather": {"type": "command", "run": "curl -s 'wttr.in/?format=%t'", "every": 600},
      "note":    {"type": "file", "path": "/home/me/note.txt"}
    }

Sources refresh in the background; drawing never waits for them. Until the first
result a source shows as "–". A JSON answer without "json" is kept whole, so a layout
can use many values from it: {weather.current.temperature_2m}.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time

TYPES = ("command", "file", "http")
_session = None


def _user_session():
    """Shared, cached lookup of the logged-in desktop user (same as touch actions)."""
    global _session
    if _session is None:
        from ..actions.session import UserSession
        _session = UserSession(log=lambda *a: None)
    return _session
MAX_TEXT = 2000           # enough for a few lines of command output (see the line() filter)


def json_path(data, path: str):
    """'items.0.statistics.subscriberCount' -> value."""
    for part in str(path).split("."):
        if part == "":
            continue
        if isinstance(data, list):
            data = data[int(part)]
        elif isinstance(data, dict):
            data = data[part]
        else:
            raise KeyError(part)
    return data


class Source:
    def __init__(self, name: str, spec: dict, allow_commands: bool, log=print, layout_path: str | None = None):
        self.name, self.spec, self.log = name, spec, log
        self.layout_path = layout_path          # for hmid-helper, which reads the command itself
        self.kind = spec.get("type")
        self.every = float(spec.get("every", 60 if self.kind != "file" else 5))
        self.allow_commands = allow_commands
        self.value = None
        self.error = None
        self._t = 0.0
        self._busy = False

    def get(self):
        """Latest value; starts a background refresh when it is due."""
        now = time.time()
        due = self.every if self.error is None else min(self.every, 30)
        if not self._busy and now - self._t >= due:
            self._busy, self._t = True, now
            threading.Thread(target=self._refresh, daemon=True, name=f"source-{self.name}").start()
        return self.value

    def _refresh(self):
        try:
            raw = self.fetch()
            if "json" in self.spec:
                raw = json_path(json.loads(raw) if isinstance(raw, (str, bytes)) else raw, self.spec["json"])
            elif isinstance(raw, bytes) and raw.lstrip()[:1] in (b"{", b"["):
                try:
                    raw = json.loads(raw)            # whole JSON answer: use paths like name.a.b.0
                except ValueError:
                    pass
            if isinstance(raw, bytes):
                raw = raw.decode(errors="replace")
            if isinstance(raw, str):
                raw = raw.strip()[:MAX_TEXT]
            if self.error:
                self.log(f"layout source '{self.name}' works again")
            self.value, self.error = raw, None
        except Exception as e:           # a broken source must never break drawing
            if str(e) != self.error:
                self.log(f"layout source '{self.name}' failed: {e}")
            self.error = str(e)
        finally:
            self._busy = False

    def fetch(self):
        timeout = float(self.spec.get("timeout", 10))
        if self.kind == "command":
            if not self.allow_commands:
                raise PermissionError("commands are only allowed in root-owned layout files")
            from .. import privileged
            if not privileged.direct():             # hmid's own user: hmid-helper runs it
                return privileged.call("source", self.layout_path, self.name, timeout=timeout + 5)
            return self.fetch_local()
        if self.kind == "file":
            with open(self.spec["path"], "rb") as f:
                return f.read(64 * 1024)
        if self.kind == "http":
            from .. import net
            return net.get(self.spec["url"], self.spec.get("headers"), timeout,
                           proxy=self.spec.get("proxy", "default"))
        raise ValueError(f"unknown source type {self.kind!r}")

    def fetch_local(self) -> bytes:
        """Run this command source in this process: as root, or as the desktop user. Used
        when hmid runs as root, and by hmid-helper."""
        timeout = min(float(self.spec.get("timeout", 10)), 120)
        if self.spec.get("as") == "user":
            return self._run_as_user(timeout)
        r = subprocess.run(["sh", "-c", self.spec["run"]], capture_output=True, timeout=timeout)
        if r.returncode:
            raise RuntimeError(f"exit {r.returncode}: {r.stderr.decode(errors='replace').strip()[:120]}")
        return r.stdout[:256 * 1024]

    def _run_as_user(self, timeout):
        """"as": "user": run as the logged-in desktop user, in their session (D-Bus, audio,
        display), e.g. playerctl or wpctl. Without a desktop session the value is empty."""
        import os
        ue = _user_session().env()
        if not ue:
            return b""
        pw, env = ue
        r = subprocess.run(["sh", "-c", self.spec["run"]], capture_output=True, timeout=timeout, env=env,
                           user=pw.pw_uid, group=pw.pw_gid, extra_groups=os.getgrouplist(pw.pw_name, pw.pw_gid),
                           cwd=pw.pw_dir, stdin=subprocess.DEVNULL)
        if r.returncode:
            raise RuntimeError(f"exit {r.returncode}: {r.stderr.decode(errors='replace').strip()[:120]}")
        return r.stdout
