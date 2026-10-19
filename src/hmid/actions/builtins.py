"""Built-in actions: Free Up Memory, countdown alarm, Mystic Light."""
from __future__ import annotations

import os
import threading
import time

from ..panel.protocol import Msg
from ..sensors import memory
from . import items

ALARM_SOUNDS = ["/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga",
                "/usr/share/sounds/freedesktop/stereo/complete.oga",
                "/usr/share/sounds/freedesktop/stereo/bell.oga"]


class FreeMemory:
    """Drops the kernel's clean caches (`drop_caches` 3: page cache, dentries, inodes)
    and reports the increase in MemFree to the panel's result page within ~1.4 s,
    like MSI Center. Programs' memory and swap are not touched; no sync is done.
    Runs at most once per 10 s (the panel may report the tap again)."""

    REPLY_AT = 1.4
    MIN_INTERVAL = 10

    def __init__(self, send_msg, log=print, drop_path="/proc/sys/vm/drop_caches", level=3, drop=None):
        self.send_msg, self.log = send_msg, log
        self.drop_path, self.level = drop_path, level
        self.drop = drop                        # done by hmid-helper when hmid has its own user
        self.busy = False
        self.last_run = 0.0

    def __call__(self):
        t0 = time.time()
        if self.busy or t0 - self.last_run < self.MIN_INTERVAL:
            return
        self.last_run, self.busy = t0, True
        try:
            before = memory.free_mb()

            def drop():
                try:
                    if self.drop:
                        self.drop()
                    else:
                        with open(self.drop_path, "w") as f:
                            f.write(f"{self.level}\n")
                except OSError as e:
                    self.log("  drop_caches failed:", e)

            th = threading.Thread(target=drop, daemon=True)
            th.start()
            th.join(timeout=max(0.0, self.REPLY_AT - 0.1 - (time.time() - t0)))
            mb = max(1, int(memory.free_mb() - before))
            time.sleep(max(0.0, self.REPLY_AT - (time.time() - t0)))
            msg = Msg.memory(mb)
            self.send_msg(msg)
            self.log(f"  freed {mb} MB, replied {msg} after {time.time() - t0:.1f}s"
                     + (" (cache drop still running)" if th.is_alive() else ""))
        finally:
            self.busy = False


class Alarm:
    """Countdown finished on the panel (item 70): desktop notification and a repeating
    sound until Stop (item 71) or any touch, at most 60 s."""

    MAX_SECONDS = 60

    def __init__(self, session, log=print):
        self.session, self.log = session, log
        self._stop: threading.Event | None = None
        self._proc = None

    @property
    def active(self) -> bool:
        return self._stop is not None and not self._stop.is_set()

    def start(self):
        if self.active:
            return
        self._stop = stop = threading.Event()
        t0 = time.time()
        n = self.session.run("notify-send -a 'HMI panel' -i alarm-clock 'Countdown timer' 'Time is up!'", wait=False)
        snd = next((s for s in ALARM_SOUNDS if os.path.exists(s)), None)
        self.log(f"  alarm: notification {'sent' if n else 'FAILED (no desktop session?)'}, "
                 f"sound: {snd or 'none found (install sound-theme-freedesktop)'}")
        end = t0 + self.MAX_SECONDS
        try:
            while snd and not stop.is_set() and time.time() < end:
                proc = self.session.run(f"exec paplay {snd} 2>/dev/null || exec pw-play {snd}", wait=False)
                if proc is None:
                    break
                self._proc = proc
                started = time.time()
                while proc.poll() is None and not stop.is_set():
                    time.sleep(0.05)
                if proc.returncode not in (None, 0, -15):
                    err = proc.stderr.read().decode(errors="ignore").strip() if proc.stderr else ""
                    self.log(f"  alarm: sound player failed ({proc.returncode}) {err[:150]}")
                    break
                if time.time() - started < 0.3 and not stop.is_set():
                    self.log("  alarm: sound ended instantly - player problem?")
                    break
                self._kill()
                stop.wait(0.3)
        finally:
            stop.set()
            self.log(f"  alarm stopped after {time.time() - t0:.0f}s")

    def stop(self):
        if self._stop:
            self._stop.set()
        self._kill()

    def _kill(self):
        p = self._proc
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, 15)
            except OSError:
                pass


class Lights:
    """Mystic Light items 80-100. Item 89 (CPU temperature) keeps updating the colour."""

    def __init__(self, colors=None, log=print, temp_source=None, factory=None):
        self.colors = {int(k): v for k, v in (colors or {}).items()}
        self.log = log
        self.temp_source = temp_source          # callable -> CPU degC or None
        self.factory = factory
        self.current = None

    def _ml(self):
        if self.factory:
            return self.factory()
        from ..lighting import MysticLight
        return MysticLight()

    def __call__(self, item: int, color: str | None = None):
        color = color or self.colors.get(item)
        self._ml().apply(item, color)
        self.current = item
        self.log(f"  lights: {items.name(item)}" + (f" #{color}" if color else ""))
        if item == items.MYSTIC_CPU_TEMP and self.temp_source:
            threading.Thread(target=self._follow_cpu_temp, daemon=True).start()

    def _follow_cpu_temp(self):
        from ..lighting.mystic import temp_color
        ml, last = self._ml(), None
        while self.current == items.MYSTIC_CPU_TEMP:
            t = self.temp_source()
            if t is not None and temp_color(t) != last:
                try:
                    ml.cpu_temp_color(t)
                    last = temp_color(t)
                except OSError as e:
                    self.log("  lights: cpu temp colour failed:", e)
                    return
            time.sleep(3)
