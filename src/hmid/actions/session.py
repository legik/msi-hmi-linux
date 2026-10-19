"""Run commands as the logged-in desktop user from the root service.

Uses Popen(user=, group=) with an environment taken from the user's session instead
of runuser/PAM, which took seconds per tap.
"""
from __future__ import annotations

import glob
import os
import pwd
import subprocess
import time

DISPLAY_VARS = ("WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY", "XDG_SESSION_TYPE",
                "XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION", "LANG")


def desktop_user() -> tuple[str, int] | None:
    """(name, uid) of the active graphical session (logind), or None."""
    try:
        lines = subprocess.run(["loginctl", "list-sessions", "--no-legend"], capture_output=True,
                               text=True, timeout=3).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return None
    best = None
    for line in lines:
        if not line.strip():
            continue
        sid = line.split()[0]
        try:
            out = subprocess.run(["loginctl", "show-session", sid, "-p", "Name", "-p", "User", "-p", "Type",
                                  "-p", "Active", "-p", "Class"], capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        info = dict(x.split("=", 1) for x in out.splitlines() if "=" in x)
        if info.get("Class") != "user" or info.get("Type") not in ("wayland", "x11"):
            continue
        cand = (info["Name"], int(info["User"]))
        if info.get("Active") == "yes":
            return cand
        best = best or cand
    return best


class UserSession:
    def __init__(self, log=print, ttl=60):
        self.log = log
        self.ttl = ttl
        self._cache = None
        self._t = 0.0

    def env(self):
        """Cached (pw entry, env) for the active desktop user."""
        now = time.time()
        if self._cache and now - self._t < self.ttl:
            return self._cache
        u = desktop_user()
        if not u:
            self._cache = None
            return None
        name, uid = u
        pw = pwd.getpwnam(name)
        env = {"HOME": pw.pw_dir, "USER": name, "LOGNAME": name,
               "PATH": "/usr/local/sbin:/usr/local/bin:/usr/bin:/bin",
               "XDG_RUNTIME_DIR": f"/run/user/{uid}",
               "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus"}
        for p in glob.glob("/proc/[0-9]*"):          # display variables from a running desktop process
            try:
                if os.stat(p).st_uid != uid:
                    continue
                with open(f"{p}/environ", "rb") as f:
                    raw = f.read().decode(errors="ignore")
            except OSError:
                continue
            e = dict(x.split("=", 1) for x in raw.split("\0") if "=" in x)
            if "WAYLAND_DISPLAY" in e or "DISPLAY" in e:
                env.update({k: e[k] for k in DISPLAY_VARS if k in e})
                break
        self._cache, self._t = (pw, env), now
        return self._cache

    def run(self, cmd: str, wait: bool = True):
        """Run a shell command as the desktop user. wait=False returns the Popen."""
        ue = self.env()
        if not ue:
            self.log("no desktop session found for:", cmd)
            return None
        pw, env = ue
        t = time.time()
        proc = subprocess.Popen(["sh", "-c", cmd], user=pw.pw_uid, group=pw.pw_gid,
                                extra_groups=os.getgrouplist(pw.pw_name, pw.pw_gid),
                                env=env, cwd=pw.pw_dir, start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if not wait:
            return proc
        try:
            _, err = proc.communicate(timeout=5)
            if proc.returncode:
                self.log(f"  '{cmd}' exited {proc.returncode}: {err.decode(errors='ignore').strip()[:200]}")
            else:
                self.log(f"  done in {(time.time() - t) * 1000:.0f} ms")
        except subprocess.TimeoutExpired:
            pass                    # long-running program (an app shortcut): leave it running
        return proc
