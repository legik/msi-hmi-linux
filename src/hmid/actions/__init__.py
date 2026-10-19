"""Touch actions: what happens when a panel menu item is tapped.

Each item maps to an action string:
    "user:<shell command>"   run as the logged-in desktop user (audio, media, apps)
    "root:<shell command>"   run as root (power menu)
    "builtin:<name>"         free_memory, timer_alarm, timer_stop, mystic, theme_next, theme_prev
    "none"                   ignore
Defaults below; override per item in /etc/hmid.json "touch_actions".
"""
from __future__ import annotations

import shutil
import subprocess
import threading

from . import items
from .builtins import Alarm, FreeMemory, Lights
from .session import UserSession

SINK, SOURCE = "@DEFAULT_AUDIO_SINK@", "@DEFAULT_AUDIO_SOURCE@"


def _vol(target, arg):
    """PipeWire (wpctl) with PulseAudio (pactl) fallback."""
    pa = "@DEFAULT_SINK@" if target == SINK else "@DEFAULT_SOURCE@"
    kind = "sink" if target == SINK else "source"
    if arg == "toggle":
        return f"user:wpctl set-mute {target} toggle 2>/dev/null || pactl set-{kind}-mute {pa} toggle"
    if arg.endswith(("+", "-")):
        n = arg[:-1]
        return (f"user:wpctl set-volume -l 1.0 {target} {n}%{arg[-1]} 2>/dev/null || "
                f"pactl set-{kind}-volume {pa} {arg[-1]}{n}%")
    return f"user:wpctl set-volume {target} {int(arg) / 100:.2f} 2>/dev/null || pactl set-{kind}-volume {pa} {arg}%"


DEFAULT_ACTIONS = {
    20: _vol(SINK, "5+"), 21: _vol(SINK, "5-"), 22: _vol(SINK, "toggle"),
    23: _vol(SINK, "25"), 24: _vol(SINK, "50"), 25: _vol(SINK, "75"), 26: _vol(SINK, "100"),
    27: _vol(SOURCE, "5+"), 28: _vol(SOURCE, "5-"), 29: _vol(SOURCE, "toggle"),
    30: _vol(SOURCE, "25"), 31: _vol(SOURCE, "50"), 32: _vol(SOURCE, "75"), 33: _vol(SOURCE, "100"),
    50: _vol(SINK, "5+"), 51: _vol(SINK, "5-"), 52: _vol(SINK, "toggle"),
    53: "user:playerctl next", 54: "user:playerctl previous", 55: "user:playerctl play-pause",
    40: "root:powerprofilesctl set performance", 41: "root:powerprofilesctl set balanced",
    42: "root:powerprofilesctl set power-saver", 43: "root:powerprofilesctl set balanced",
    44: "root:powerprofilesctl set performance",
    60: "builtin:free_memory",
    70: "builtin:timer_alarm", 71: "builtin:timer_stop",
    **{i: "builtin:mystic" for i in items.MYSTIC_RANGE},
    240: "root:systemctl suspend", 241: "root:systemctl reboot", 242: "root:systemctl poweroff",
}

OPTIONAL_TOOLS = {"wpctl": "pipewire (wpctl)", "playerctl": "playerctl", "notify-send": "libnotify"}


def missing_tools():
    return [pkg for tool, pkg in OPTIONAL_TOOLS.items() if not shutil.which(tool)]


class AlarmState:
    """When hmid-helper plays the alarm: what hmid needs to know (is it ringing?) and how to
    stop it. The alarm ends by itself after Alarm.MAX_SECONDS."""

    def __init__(self, log=print):
        self.log = log
        self._until = 0.0

    @property
    def active(self) -> bool:
        import time
        return time.time() < self._until

    def started(self):
        import time
        self._until = time.time() + Alarm.MAX_SECONDS

    def stop(self):
        self._until = 0.0
        from .. import privileged
        try:
            privileged.call("alarm-stop", timeout=5)
        except OSError as e:
            self.log("alarm stop failed:", e)


# actions that need root or the desktop session: hmid-helper runs them when hmid has its own user
HELPER_KINDS = ("user:", "root:", "builtin:timer_alarm", "builtin:timer_stop")


class Actions:
    def __init__(self, overrides=None, log=print, send_msg=None, light_colors=None, cpu_temp=None, on_theme=None):
        from .. import privileged
        self.map = dict(DEFAULT_ACTIONS)
        for k, v in (overrides or {}).items():
            self.map[int(k)] = v
        self.log = log
        self.delegate = not privileged.direct()      # hmid as its own user
        self.session = UserSession(log)
        self.free_memory = FreeMemory(send_msg or (lambda m: None), log,
                                      drop=(lambda: privileged.call("drop-caches", timeout=60)) if self.delegate else None)
        self.alarm = AlarmState(log) if self.delegate else Alarm(self.session, log)
        self.lights = Lights(light_colors, log, temp_source=cpu_temp)
        self.builtins = {
            "free_memory": lambda item: self.free_memory(),
            "timer_alarm": lambda item: self.alarm.start(),
            "timer_stop": lambda item: self.alarm.stop(),
            "mystic": self.lights,
            "theme_next": lambda item: on_theme and on_theme(+1),
            "theme_prev": lambda item: on_theme and on_theme(-1),
        }

    @property
    def busy(self):
        return self.free_memory.busy

    def handle(self, item: int):
        action = self.map.get(item, "none")
        self.log(f"tap: {items.name(item)} ({item}) -> {action}")
        if action != "none":
            threading.Thread(target=self.run, args=(action, item), daemon=True).start()

    def run(self, action: str, item: int | None = None):
        if self.delegate and item is not None and action.startswith(HELPER_KINDS):
            from .. import privileged
            try:
                privileged.call("action", item)     # the helper looks the action up itself
                if action == "builtin:timer_alarm":
                    self.alarm.started()
                elif action == "builtin:timer_stop":
                    self.alarm._until = 0.0
            except OSError as e:
                self.log("action failed:", action, e)
            return
        try:
            kind, _, cmd = action.partition(":")
            if kind == "builtin":
                fn = self.builtins.get(cmd)
                if not fn:
                    self.log("unknown builtin:", cmd)
                    return
                fn(item)
            elif kind == "root":
                r = subprocess.run(["sh", "-c", cmd], timeout=30, capture_output=True, text=True)
                if r.returncode:
                    self.log(f"  '{cmd}' exited {r.returncode}: {r.stderr.strip()[:200]}")
            elif kind == "user":
                self.session.run(cmd)
            else:
                self.log("unknown action:", action)
        except Exception as e:          # an action must never take the service down
            self.log("action failed:", action, e)
