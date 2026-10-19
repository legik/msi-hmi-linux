"""The hmid service: keeps the panel alive and showing the configured screen.

Threads
  session loop   connect, MSI handshake, keepalive (GetDisplay every 2 s), time sync,
                 overlay uploads / hardware-monitor values, freeze recovery
  reader         drains the event pipe (EP 0x81) like Windows does; detects taps
  control        unix socket for hmictl and the sleep hook
  actions        one short-lived thread per tap

All panel I/O goes through `self.lock`.

Panel-side state the service tracks (the panel runs its own menu):
  dynamic_active   our dynamic canvas (stats / multi monitor) is up
  list_active      the panel-drawn monitor is up
  menu_open        someone is using the panel's own menu or a function page
  showing_default  False while a screen picked on the panel itself is showing
  picked_dynamic   the user opened the panel's own Hardware Monitor (screen 25)
The panel returns from its menu by itself; the keepalive notices and resumes updates.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
from importlib import resources

from .. import config, hwmon
from ..actions import Actions, items, missing_tools
from ..layouts import available as available_layouts
from ..layouts import catalog as layout_catalog
from ..layouts.draw import LayoutRenderer
from ..panel import Mode, Panel, PanelError, recovery, transport
from ..panel import protocol as P
from ..render import Renderer
from ..render import theme as T
from ..sensors import Sensors
from . import control
from .screens import make_screen

KEEPALIVE = 2.0
TIME_SYNC = 60.0
HW_VALUES = 1.0
GAME_CHECK = 2.0          # how often to look for a running game (MangoHud log)
GAME_END = 15.0           # game gone this long -> back to the default screen
MAX_MISSES = 5            # keepalive replies missed in a row -> treat the panel as frozen
WATCHDOG_WAIT = 40.0      # the panel's watchdog normally restarts it within this time


def log(*a):
    print(*a, flush=True)       # journald adds timestamps


# settings that need the service restarted (read once at start)
RESTART_KEYS = ("menu_user_scenario", "menu_mystic_light", "light_on_start")
# settings the current screen is drawn from: show it again
SCREEN_KEYS = ("screen", "clock_style", "clock_24h", "stats_interval", "background", "hwmon_mode",
               "hwmon_style", "hwmon_sensors", "hwmon_auto_hide", "hwmon_page_seconds")

# shown when a command is given without (or with wrong) arguments
USAGE = {
    "set": "set <setting> <value>   e.g. set debug_events true, set touch_actions.250 builtin:theme_next",
    "unset": "unset <setting>   (back to the default)",
    "get": "get [setting]",
    "picture": "picture [fill|fit|stretch] [rotate] <file>   or   picture builtin <0-5>",
    "brightness": "brightness <0-100>",
    "light": "light <80-100> [RRGGBB]",
    "theme": "theme <name> | next | prev   (themes lists them)",
    "display": "display <mode> [hexdata]",
    "msg": "msg <55AA...5AA5>",
}


class Service:
    def __init__(self, conf_path=config.PATH, state_path=None):
        self.conf_path = conf_path
        self.state_path = state_path or config.state_path_for(conf_path)
        self.conf = config.load(conf_path, warn=log, state=self.state_path)
        from .. import net
        net.set_default(self.conf["proxy"])
        net.set_logger(log if self.conf["debug_events"] else None)      # one line per request
        log(f"web requests: {'through ' + net.describe(self.conf['proxy']) if self.conf['proxy'] else 'direct (no proxy set)'}")
        self.panel: Panel | None = None
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.connected = False
        self.sleeping = False
        self.frozen = False
        self.screen = None
        self.dynamic_active = False
        self.list_active = False
        self.menu_open = False
        self.showing_default = True
        self.picked_dynamic = False
        self.last_real_touch = 0.0
        self.last_in = 0.0
        self.reply_misses = 0
        self._sample = None              # (time, Sample) cache shared by overlay and values
        self.game = None                 # running game (MangoHud), checked every GAME_CHECK s
        self.game_seen = 0.0
        self.game_mode = False           # showing game_screen because a game runs
        self.game_override = False       # user picked a screen during this game: don't switch
        self.redraw = False              # draw the overlay as soon as possible (e.g. new theme)
        self.log = log

        c = self.conf
        self.sensors = Sensors(c["fan_map"], c["vrm_temp_label"], c["mangohud_folder"], log=log)
        self.sensors.fps.setup()
        self.renderer = Renderer(c["theme"])
        self.layout_renderer = LayoutRenderer(c["theme"])
        self.actions = Actions(c["touch_actions"], log=log, send_msg=self._send_msg,
                               light_colors=c["light_colors"], cpu_temp=self.sensors.cpu.temp,
                               on_theme=lambda d: self.set_theme(T.step(self.conf["theme"], d)))
        miss = missing_tools()
        if miss:
            log("touch actions: optional tools not installed:", ", ".join(miss))

    # ---- helpers ---------------------------------------------------------------------
    def background_video(self) -> bytes:
        path = self.conf["background"]
        if path:
            with open(path, "rb") as f:
                return f.read()
        return resources.files("hmid").joinpath("data/bg_default.mp4").read_bytes()

    def sample(self, max_age=0.0):
        if self._sample and time.time() - self._sample[0] <= max_age:
            return self._sample[1]
        s = self.sensors.sample()
        self._sample = (time.time(), s)
        return s

    def hwmon_names(self, mode, sample=None):
        missing = set()
        if self.conf["hwmon_auto_hide"]:
            missing = self.sensors.missing(sample or self.sample(max_age=5))
        return hwmon.select(self.conf["hwmon_sensors"], mode, missing, log)

    def change_setting(self, key: str, value=None, remove=False) -> str:
        """hmictl set / unset. Choices made while running (config.PERSISTED) go to hmid's state
        file. Everything else lives in /etc/hmid.json, which hmictl (as root) edits itself and
        then sends "reload"; only a service running as root edits it here."""
        name = key.partition(".")[0]
        if name in ("screen", "game_screen") and isinstance(value, str) and value.startswith("layout:") \
                and value[7:] not in available_layouts():
            return f"error no layout '{value[7:]}' (available: {', '.join(available_layouts())})"
        if name in config.PERSISTED and "." not in key:
            if remove:
                try:
                    config.forget_state(name, self.state_path)
                except OSError as e:
                    return f"error {e}"
                return self.reload()
            warnings = []
            checked = config.validate({name: value}, warn=warnings.append)
            if warnings:
                return "error " + "; ".join(w.removeprefix("config: ") for w in warnings)
            old = dict(self.conf)
            self.conf = {**self.conf, name: checked[name]}
            config.save_state(self.conf, self.state_path, warn=log)
            log(f"setting {key} changed (hmictl)")
            return self.apply_changes(old, self.conf)
        from .. import privileged
        if not privileged.direct():
            return f"error {name} is in {self.conf_path}: change it with sudo hmictl set (hmictl edits the file)"
        conf, err = config.edit(key, value, remove, self.conf_path)
        if err:
            return f"error {err}"
        log(f"setting {key} {'reset to default' if remove else 'changed'} (hmictl)")
        return self.reload()

    def reload(self) -> str:
        """Read the settings again (after hmictl or you changed /etc/hmid.json) and apply
        what changed."""
        new = config.load(self.conf_path, warn=log, state=self.state_path)
        old, self.conf = self.conf, new
        return self.apply_changes(old, new)

    def apply_changes(self, old: dict, new: dict) -> str:
        changed = [k for k in new if old.get(k) != new[k]]
        if changed:
            log("settings changed: " + ", ".join(changed))
        redraw = False
        for name in changed:
            if name == "theme":
                self.set_theme(new["theme"])
            elif name == "brightness" and self.connected:
                with self.lock:
                    self.panel.brightness(new["brightness"])
            elif name == "proxy":
                from .. import net
                net.set_default(new["proxy"])
                log(f"web requests: {'through ' + net.describe(new['proxy']) if new['proxy'] else 'direct (no proxy set)'}")
            elif name == "debug_events":
                from .. import net
                net.set_logger(log if new["debug_events"] else None)
            elif name in ("fan_map", "vrm_temp_label", "mangohud_folder"):
                self.sensors = Sensors(new["fan_map"], new["vrm_temp_label"], new["mangohud_folder"], log=log)
                self.sensors.fps.setup()
                self.actions.lights.temp_source = self.sensors.cpu.temp
                self._sample = None
            elif name == "touch_actions":
                from ..actions import DEFAULT_ACTIONS
                self.actions.map = {**DEFAULT_ACTIONS, **{int(k): v for k, v in new["touch_actions"].items()}}
            elif name == "light_colors":
                self.actions.lights.colors = {int(k): v for k, v in new["light_colors"].items()}
            elif name in SCREEN_KEYS:
                redraw = True
        if redraw and self.connected and not self.sleeping:
            with self.lock:
                self.show_screen()
        later = [k for k in changed if k in RESTART_KEYS]
        if later:
            return f"ok - {', '.join(later)} takes effect after: sudo systemctl restart hmid"
        return "ok"

    def set_theme(self, name: str) -> str:
        """Switch the colour theme for every screen and save it. While the panel's own menu
        is open the new colours appear when it returns to the screen (drawing is paused)."""
        self.conf["theme"] = name
        config.save_state(self.conf, self.state_path, warn=log)
        pictures = self.layout_renderer.pictures            # keep loaded covers: no new downloads
        self.renderer, self.layout_renderer = Renderer(name), LayoutRenderer(name)
        self.layout_renderer.pictures = pictures
        log(f"theme: {name}" + ("  (shown when the panel leaves its menu)" if self.menu_open else ""))
        self.redraw = True                         # drawn by the session loop as soon as allowed
        return name

    def _send_msg(self, text):
        with self.lock:
            if self.connected:
                self.panel.msg(text)

    # ---- screens -------------------------------------------------------------------------
    def show_screen(self, name=None):
        """Open a screen from scratch (boot, wake, hmictl, game start/end).
        name=None: the configured default screen."""
        if name is None:
            self.game_mode = False
        self.dynamic_active = self.list_active = False
        self.showing_default, self.picked_dynamic = True, False
        self.panel.brightness(self.conf["brightness"])
        self.screen = make_screen(self, name or self.conf["screen"])
        self.menu_open = self.screen.name == "menu"      # the panel's own menu is the screen
        if not self.screen.open():
            self.screen = make_screen(self, "clock")
            self.screen.open()

    def overlay_wanted(self):
        """Upload overlays? Our dynamic screen is up, or the user opened the panel's own
        Hardware Monitor (screen 25). Never while the countdown alarm is up: an upload
        onto another page freezes the panel."""
        if self.menu_open or self.actions.alarm.active:
            return False
        return (self.dynamic_active and self.showing_default) or self.picked_dynamic

    def values_wanted(self):
        return self.list_active and self.showing_default and not self.menu_open \
            and not self.actions.alarm.active

    def push_overlay(self):
        s = self.sample()
        scr = self.screen if self.screen and self.screen.dynamic else make_screen(self, "stats")
        png = scr.render(s)
        with self.lock:
            p = self.panel
            p.device_info()                      # MSI queries these before every overlay -
            r = p.get_display(Mode.DYNAMIC)      # without them the panel ignores the upload
            if not P.dynamic_ready(r):
                return False
            p.upload(png, P.DYNAMIC_OVERLAY)
            return True

    def push_hw_values(self):
        vals = hwmon.encode(self.sample(max_age=2))
        with self.lock:
            self.panel.hw_values(vals)

    def check_game(self, now):
        """Switch to "game_screen" while a game runs (MangoHud log), back when it ends.
        Waits while the panel's own menu or the countdown alarm is up."""
        g = self.sensors.fps.read()
        if g and not self.game:
            log(f"game detected: {g.app}")
        self.game = g
        if g:
            self.game_seen = now
        target = self.conf["game_screen"]
        if not target or self.sleeping or not self.connected:
            return
        if g:
            if not self.game_mode and not self.game_override and target != self.conf["screen"] \
                    and not self.menu_open and not self.actions.alarm.active:
                log(f"game started ({g.app}) - showing {target}")
                with self.lock:
                    self.show_screen(target)
                self.game_mode = True
        elif now - self.game_seen >= GAME_END:
            if self.game_mode and not self.menu_open and not self.actions.alarm.active:
                log(f"game closed - back to {self.conf['screen']}")
                with self.lock:
                    self.show_screen()
            if not self.game_mode:
                self.game_override = False

    # ---- keepalive replies -----------------------------------------------------------------
    def _returned(self):
        return self.menu_open and not self.actions.alarm.active and time.time() - self.last_real_touch > 1.5

    def check_dynamic(self, reply):
        on = P.display_active(reply)
        if on and self.dynamic_active and self.screen.dynamic and self._returned():
            self.menu_open, self.showing_default = False, True
            log(f"panel is back on {self.screen.name} - resuming updates")
            return
        ours = self.dynamic_active and self.showing_default
        if on and not ours and not self.picked_dynamic:
            self.picked_dynamic, self.menu_open, self.showing_default = True, False, False
            log("panel opened its Hardware Monitor (screen 25) - sending stats")
        elif not on and self.picked_dynamic:
            self.picked_dynamic = False
            log("panel left its Hardware Monitor")

    def check_list(self, reply):
        if P.display_active(reply) and self.list_active and self._returned():
            self.menu_open, self.showing_default = False, True
            log("panel is back on its hardware monitor - resuming values")

    # ---- startup / power -----------------------------------------------------------------
    def startup(self):
        """MSI's connect sequence. True if the panel answered."""
        with self.lock:
            p = self.panel
            if not p.device_info():
                log("panel did not answer device-info query")
                return False
            p.lcid()
            p.version()
            p.set_display(Mode.LOADING)
        time.sleep(0.5)
        with self.lock:
            p.handshake(self.conf["menu_user_scenario"], self.conf["menu_mystic_light"])
            self.show_screen()
        log("panel ready:", self.conf["screen"])
        return True

    def power_screen(self, mode, backlight_off=False):
        with self.lock:
            if self.connected:
                self.panel.power_screen(mode, backlight_off)

    def final_screen(self):
        """Service stopping: tell the panel whether the PC reboots or powers off."""
        try:
            jobs = subprocess.run(["systemctl", "list-jobs", "--no-legend"],
                                  capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            jobs = ""
        mode = Mode.RESTART if ("reboot.target" in jobs or "kexec.target" in jobs) else Mode.SHUTDOWN
        try:
            with self.lock:
                self.panel.set_display(mode)
            log("final screen:", "restart" if mode == Mode.RESTART else "shutdown")
        except PanelError as e:
            log("final screen failed:", e)

    def start_lights(self):
        item = self.conf["light_on_start"]
        if item is None:
            return
        from ..lighting import find_node
        for _ in range(30):                      # the controller may appear later at boot
            if find_node():
                try:
                    self.actions.lights(int(item))
                    log(f"lights at start: {items.name(int(item))}")
                except (OSError, ValueError) as e:
                    log("lights at start failed:", e)
                return
            if self.stop.wait(1):
                return
        log("lights at start: Mystic Light controller not found")

    # ---- reader thread ---------------------------------------------------------------------
    def reader(self):
        """Taps: the panel reports its current menu function ("item") in every packet. A tap
        on a menu button shows as the item jumping to that button's number; about 2 s later
        it falls back to 0. (This panel never sets the touch flag.)

        Menu buttons can only be tapped while the panel's menu is open. While our own screen
        is up, an item change is the tap that opens the menu - or the panel changing the item
        by itself (seen when it leaves a page after its idle timeout) - so no action runs."""
        last_item = last_raw = None
        debug = self.conf["debug_events"]
        while self.connected and not self.stop.is_set():
            try:
                raw = self.panel.read_raw_event(0.2)
            except PanelError as e:
                if self.connected and not self.stop.is_set():
                    log("panel disconnected:", e)
                self.connected = False
                return
            if raw:
                self.last_in = time.time()
            ev = P.parse_event(raw)
            if not ev:
                continue
            now = time.time()
            alarm = self.actions.alarm
            if (alarm.active or debug) and (ev.item, ev.flag) != last_raw:
                log(f"  ({'alarm' if alarm.active else 'event'}) panel reports item={ev.item} flag={ev.flag}")
                last_raw = (ev.item, ev.flag)
            if alarm.active and ev.flag == 1:
                alarm.stop()                          # any touch stops the alarm
            changed = last_item is not None and ev.item != last_item
            if changed or ev.flag == 1:
                self.last_real_touch = now
            if not self.sleeping and changed and ev.item != 0:
                if self.menu_open:
                    self.actions.handle(ev.item)
                else:
                    log(f"panel menu opened (item {items.name(ev.item)} ({ev.item}) - no action)")
            if changed or ev.flag == 1:
                self.menu_open = True
            last_item = ev.item

    # ---- session loop ----------------------------------------------------------------------
    def session(self):
        while not transport.present():
            if self.stop.wait(0.2):
                return
        try:
            self.panel = Panel.open()
        except PanelError as e:
            log("open failed:", e)
            time.sleep(1)
            return
        self.connected = True
        log("panel connected")
        threading.Thread(target=self.reader, daemon=True, name="reader").start()
        time.sleep(1.0)
        ready = False
        if not self.sleeping:
            try:
                ready = self.startup()
            except PanelError as e:
                log("startup failed:", e)
        t_poll = t_sync = t_draw = t_vals = t_game = time.time()
        while self.connected and not self.stop.is_set():
            self.stop.wait(0.2)
            now = time.time()
            try:
                if not self.sleeping and self.values_wanted() and now - t_vals >= HW_VALUES:
                    t_vals = now
                    self.push_hw_values()
                if ready and now - t_game >= GAME_CHECK:
                    t_game = now
                    self.check_game(now)
                interval = self.screen.interval if self.screen and self.screen.dynamic else self.conf["stats_interval"]
                if not self.sleeping and self.overlay_wanted() and (self.redraw or now - t_draw >= interval):
                    self.redraw = False
                    t_draw = now
                    try:
                        self.push_overlay()
                    except PanelError:
                        raise
                    except Exception as e:            # a drawing bug must not stop the service
                        log("render error:", e)
                with self.lock:
                    if now - t_poll >= KEEPALIVE:
                        t_poll = now
                        mode = self.screen.keepalive_mode if self.screen else Mode.DYNAMIC
                        r = self.panel.get_display(mode)
                        self.reply_misses = 0 if r else self.reply_misses + 1
                        if self.reply_misses >= MAX_MISSES:
                            log(f"panel stopped answering for {MAX_MISSES * KEEPALIVE:.0f} s - treating it as frozen")
                            self.reply_misses, self.frozen = 0, True
                            break
                        if mode == Mode.HWMON:
                            self.check_list(r)
                        else:
                            self.check_dynamic(r)
                        if not ready and not self.sleeping:
                            ready = self.startup()
                    if not self.sleeping and now - t_sync >= TIME_SYNC:
                        self.panel.sync_time(self.conf["clock_24h"])
                        t_sync = now
            except PanelError as e:
                if not self.stop.is_set():
                    log("command error:", e, "| last command:", self.panel.describe_last())
                    if e.errno == 110:
                        self.frozen = True
                break
        self.connected = False
        if self.stop.is_set():
            self.final_screen()
        time.sleep(0.3)
        try:
            self.panel.close()
        except Exception:
            pass
        if self.frozen and not self.stop.is_set():
            self.recover()

    def recover(self):
        """The firmware hung: send nothing until its watchdog restarts it."""
        self.frozen = False
        log(f"panel froze - waiting for it to restart itself (up to {WATCHDOG_WAIT:.0f} s)")
        t0 = time.time()
        while transport.present() and time.time() - t0 < WATCHDOG_WAIT:
            if self.stop.wait(0.5):
                return
        if time.time() - t0 < WATCHDOG_WAIT:
            log(f"panel restarted after {time.time() - t0:.0f}s")
        else:
            log("panel did not restart by itself - cycling its USB port")
            try:
                from .. import privileged
                if privileged.direct():
                    recovery.cycle_port(log)
                else:
                    privileged.call("usb-cycle", timeout=40)   # writing the port switch needs root
            except OSError as e:
                log("port cycle failed:", e)
        self.menu_open = False

    def run(self):
        threading.Thread(target=self.serve_control, daemon=True, name="control").start()
        threading.Thread(target=self.start_lights, daemon=True, name="lights").start()
        while not self.stop.is_set():
            try:
                self.session()
            except Exception as e:
                log("error:", e)
            self.stop.wait(1)

    # ---- control socket ----------------------------------------------------------------------
    def serve_control(self):
        control.serve(self.handle)

    def _wake(self):
        time.sleep(1.5)                  # give USB a moment after resume
        try:
            if self.connected and not self.sleeping:
                self.startup()
        except PanelError as e:
            log("wake startup failed (will reconnect):", e)

    def handle(self, line: str) -> str:
        try:
            args = shlex.split(line)                       # hmictl quotes its arguments
        except ValueError:
            args = line.split()
        if not args:
            return "error empty command"
        c, rest = args[0], args[1:]
        try:
            if c == "status":
                return json.dumps({"connected": self.connected, "sleeping": self.sleeping,
                                   "screen": self.screen.name if self.screen else None,
                                   "seconds_since_panel_packet": round(time.time() - self.last_in, 1) if self.last_in else None,
                                   "missed_replies": self.reply_misses,
                                   "game": {"app": self.game.app, "fps": round(self.game.fps)} if self.game else None,
                                   "game_mode": self.game_mode, "config": self.conf})
            if c in ("sleep", "hibernate"):
                self.sleeping, self.dynamic_active = True, False
                self.power_screen(Mode.SLEEP if c == "sleep" else Mode.HIBERNATE, self.conf["sleep_backlight_off"])
                log("system going to", c)
                return "ok"
            if c == "wake":
                self.sleeping = False
                log("system woke up")
                if self.connected:
                    threading.Thread(target=self._wake, daemon=True).start()
                return "ok"
            if c in ("shutdown", "restart"):
                self.power_screen(Mode.SHUTDOWN if c == "shutdown" else Mode.RESTART)
                return "ok"
            if c == "themes":
                return json.dumps({"current": self.conf["theme"], "available": list(T.NAMES)})
            if c == "theme" and len(rest) == 1:            # theme <name> | next | prev
                name = T.step(self.conf["theme"], 1 if rest[0] == "next" else -1) if rest[0] in ("next", "prev") \
                    else rest[0]
                if name not in T.NAMES:
                    return f"error unknown theme '{name}' (available: {', '.join(T.NAMES)})"
                return f"ok {self.set_theme(name)}"
            if c == "layouts":
                return json.dumps(layout_catalog())
            if c == "get" and len(rest) <= 1:              # get [key]
                if rest:
                    name = rest[0].partition(".")[0]
                    if name not in config.DEFAULTS:
                        return f"error unknown setting '{name}'"
                    v = self.conf[name]
                    if "." in rest[0]:
                        v = (v or {}).get(rest[0].partition(".")[2])
                    return json.dumps(v, ensure_ascii=False)
                return json.dumps({"settings": self.conf, "in_file": config.in_file(self.conf_path, self.state_path),
                                   "file": self.conf_path}, ensure_ascii=False)
            if c == "reload":                              # after /etc/hmid.json changed
                return self.reload()
            if c == "set" and len(rest) >= 2:              # set key value  (value may contain spaces)
                return self.change_setting(rest[0], config.parse_value(" ".join(rest[1:])))
            if c == "unset" and len(rest) == 1:
                return self.change_setting(rest[0], remove=True)
            if c == "sources":                             # what the shown layout gets (debug)
                lay = getattr(self.screen, "layout", None)
                if lay is None:
                    return f"error the panel shows '{self.screen.name if self.screen else None}', not a layout"
                from ..layouts.draw import describe
                return json.dumps(describe(lay, self.layout_renderer, self.sensors.sample()), ensure_ascii=False)
            if c == "layout":                              # layout <name>
                if len(rest) != 1:
                    return "error use: layout <name>  (available: " + ", ".join(available_layouts()) + ")"
                if rest[0] not in available_layouts():
                    return f"error no layout '{rest[0]}' (available: {', '.join(available_layouts())})"
                c, rest = "layout:" + rest[0], []
            if c in config.SCREENS or c.startswith("layout:"):
                if c == "hwmon" and rest:
                    if rest[0] not in ("list", "multi"):
                        return "error use: hwmon [list|multi]"
                    self.conf["hwmon_mode"] = rest[0]
                self.conf["screen"] = c
                config.save_state(self.conf, self.state_path, warn=log)
                if self.game:                              # chosen during a game: keep it
                    self.game_override = True
                if self.connected and not self.sleeping:
                    with self.lock:
                        self.show_screen()
                return "ok"
            if c == "brightness" and len(rest) == 1:
                self.conf["brightness"] = max(0, min(100, int(rest[0])))
                config.save_state(self.conf, self.state_path, warn=log)
                if self.connected:
                    with self.lock:
                        self.panel.brightness(self.conf["brightness"])
                return "ok"
            if c == "sensors":
                self.sensors.sample()
                time.sleep(0.5)
                s = self.sample()
                rd, gone = hwmon.readings(s), self.sensors.missing(s)
                return json.dumps({n: f"{rd[n].text} {rd[n].unit}".strip() + (" (no reading)" if n in gone else "")
                                   for n in hwmon.SENSORS}, ensure_ascii=False)
            if c == "light" and rest:                      # light <item 80-100> [RRGGBB]
                self.actions.lights(int(rest[0]), rest[1] if len(rest) > 1 else None)
                return "ok"
            if c == "where":
                with self.lock:
                    act = [m for m in P.MODE_NAMES if self.panel.active(m)]
                return json.dumps({"active": {int(m): P.MODE_NAMES[m] for m in act},
                                   "showing_default": self.showing_default, "menu_open": self.menu_open,
                                   "panel_hw_monitor": self.picked_dynamic, "sending_overlay": self.overlay_wanted()})
            if c == "picture" and rest:      # picture [fill|fit|stretch] [rotate] <file> | picture builtin <0-5>
                from .. import media
                animated = False
                if rest[0] == "builtin" and len(rest) == 2:
                    slot, data = int(rest[1]), None
                    if not 0 <= slot <= 5:
                        return "error built-in pictures are slots 0-5"
                else:
                    mode, rotate = "fill", False
                    while rest and rest[0] in media.MODES + ("rotate",):
                        if rest[0] == "rotate":
                            rotate = True
                        else:
                            mode = rest[0]
                        rest = rest[1:]
                    path = " ".join(rest)
                    if not os.path.isfile(path):
                        return f"error no such file: {path}"
                    slot, animated = P.PICTURE_SLOT, media.is_animated(path)
                    try:
                        data = media.animation_avi(path, mode, rotate) if animated else media.still_png(path, mode, rotate)
                    except RuntimeError as e:
                        return f"error {e}"
                self.dynamic_active = self.list_active = False      # stop overlays / values
                with self.lock:
                    if animated:
                        self.panel.show_video(data, slot)
                    else:
                        self.panel.show_picture(data, ".png", slot)
                kind = "animation" if animated else "picture"
                log(f"{kind}: slot {slot}" + (f", uploaded {len(data) // 1024} KB" if data else " (built-in)"))
                return "ok"
            if c == "display" and rest:                    # debug: display <mode> [hexdata]
                data = bytes.fromhex(rest[1]) if len(rest) > 1 else b"\x01"
                self.dynamic_active = self.list_active = False
                with self.lock:
                    self.panel.set_display(int(rest[0]), data)
                return "ok"
            if c == "msg" and len(rest) == 1:              # debug: msg 55AA....5AA5
                with self.lock:
                    self.panel.msg(rest[0])
                return "ok"
            if c in USAGE:                                 # right command, wrong or missing arguments
                return f"error use: {USAGE[c]}"
            return f"error unknown command '{c}' (hmictl help lists them)"
        except PanelError as e:
            return f"error usb: {e}"
        except (ValueError, OSError) as e:
            return f"error {e}"
