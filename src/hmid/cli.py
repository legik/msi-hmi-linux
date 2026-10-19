"""Command-line entry points.

    hmid                      run the service (systemd starts this)
    hmictl <command>          control the running service, or use a local tool
"""
from __future__ import annotations

import signal
import sys
import threading
import time

from . import __version__

CTL_HELP = f"""hmictl {__version__} - control the MSI HMI panel service

Service commands (need the service running; use sudo). Add --json for the raw answer:
  status                        connection state and settings
  stats | clock | menu          switch the default screen (saved)
  layout <name>                 show a layout (saved); layouts = list built-in and yours
  hwmon [list|multi]            hardware monitor; list = panel-drawn, multi = tiles (saved)
  brightness <0-100>            backlight (saved)
  theme <name> | next | prev    colour scheme for every screen (saved); themes = list them
  sensors                       hardware-monitor sensor names and current readings
  get [setting]                 settings, and which are defaults
  set <setting> <value>         change one setting (checked, saved, applied), e.g. set debug_events true,
                                set proxy socks5h://127.0.0.1:1080, set touch_actions.250 builtin:theme_next
  unset <setting>               back to the default (also unset touch_actions.250)
  sources                       the shown layout: its file, each source's value or error, and
                                what each picture points to and whether it loaded
  light <80-100> [RRGGBB]       Mystic Light effect (panel item numbers, see docs)
  sleep | hibernate | wake | shutdown | restart     power screens (used by the sleep hook)
  where                         which screens the panel reports as active (debug)
  picture [fill|fit|stretch] [rotate] <file>
                                show a picture, animated GIF or video clip. fill (default) covers
                                the screen and crops edges, fit adds black borders, stretch
                                distorts; rotate turns it 90 degrees first (wide pictures)
  picture builtin <0-5>         show one of the panel's built-in pictures (testing)
  display <mode> [hexdata]      raw SetDisplay (debug)
  msg <55AA...5AA5>             raw text command (debug)

Local tools (no service needed):
  preview <out.png> [stats|multi|<layout name or file>]   draw a page with live readings
  check <layout.json>               validate a layout file
  preview-themes <out.png> [stats|<layout>]   one picture with every colour theme side by side
  customize <name>                  copy a built-in layout to /etc/hmid/layouts to edit it (sudo)
  lights-state                      show the Mystic Light controller's current effects
  probe                             query the panel directly (stop the service first)
  watch                             print touch events (stop the service first)
"""


# for shell completion (packaging/completions): name and a short description
COMMANDS = (
    ("status", "connection state and settings"), ("stats", "show the stats screen"),
    ("clock", "show the panel clock"), ("menu", "show the panel menu"), ("layout", "show a layout"),
    ("layouts", "list layouts"), ("hwmon", "hardware monitor (list|multi)"), ("brightness", "backlight 0-100"),
    ("theme", "colour theme"), ("themes", "list colour themes"), ("sensors", "sensor readings"),
    ("sources", "what the shown layout gets (debug)"), ("light", "Mystic Light effect"),
    ("get", "show settings"), ("set", "change a setting"), ("unset", "reset a setting to its default"),
    ("picture", "show a picture, GIF or video"), ("sleep", "sleep screen"), ("hibernate", "hibernate screen"),
    ("wake", "after waking up"), ("shutdown", "shutdown screen"), ("restart", "restart screen"),
    ("where", "active screens (debug)"), ("display", "raw SetDisplay (debug)"), ("msg", "raw text command (debug)"),
    ("preview", "draw a page to a PNG"), ("check", "validate a layout file"),
    ("preview-themes", "every theme side by side"), ("customize", "copy a built-in layout to edit it"),
    ("lights-state", "Mystic Light controller state"), ("probe", "query the panel (service stopped)"),
    ("watch", "print touch events (service stopped)"),
)


# local tools: usage when the arguments are missing (they never go to the service)
LOCAL_USAGE = {
    "preview": "preview <out.png> [stats|multi|<layout name or file>]",
    "preview-themes": "preview-themes <out.png> [stats|<layout>]",
    "check": "check <layout.json>",
    "customize": "customize <layout name>",
}


def _complete(what: str) -> list[str]:
    """Words for shell completion. Reads only files any user can read: no service, no sudo."""
    if what == "commands":
        return [f"{n}:{d}" for n, d in COMMANDS]
    if what == "layouts":
        from .layouts import available
        return list(available())
    if what == "themes":
        from .render.theme import NAMES
        return list(NAMES)
    if what == "settings":
        from .config import DEFAULTS
        return list(DEFAULTS)
    if what.startswith("values:"):
        from .config import _CHOICES, _TYPES, DEFAULTS
        key = what[7:]
        if key == "theme":
            from .render.theme import NAMES
            return list(NAMES)
        if key in ("screen", "game_screen"):
            from .layouts import available
            return list(_CHOICES[key]) + [f"layout:{n}" for n in available()] + (["null"] if key == "game_screen" else [])
        if key in _CHOICES:
            return list(_CHOICES[key])
        if _TYPES.get(key) is bool:
            return ["true", "false"]
        if key in DEFAULTS and DEFAULTS[key] is None:
            return ["null"]
        return []
    if what == "lights":
        from .actions import items
        return [f"{i}:{items.name(i).removeprefix('MysticLight_')}" for i in items.MYSTIC_RANGE]
    return []


def main_daemon():
    if len(sys.argv) > 1 and sys.argv[1] in ("-V", "--version"):
        print(__version__)
        return
    from .daemon import Service
    svc = Service()

    def on_term(*_):
        svc.log("stopping")
        svc.stop.set()

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    svc.log(f"hmid {__version__} starting")
    t = threading.Thread(target=svc.run, daemon=True, name="main")
    t.start()
    while t.is_alive():
        t.join(0.5)
        if svc.stop.is_set():
            t.join(4)
            break


def _preview(args):
    from . import hwmon
    from .config import load
    from .render import Renderer
    from .sensors import Sensors
    conf = load()
    from . import net
    net.set_default(conf["proxy"])
    net.set_logger(print)
    sn = Sensors(conf["fan_map"], conf["vrm_temp_label"], conf["mangohud_folder"])
    sn.sample()
    time.sleep(1)
    s = sn.sample()
    r = Renderer(conf["theme"])
    what = args[1] if len(args) > 1 else "stats"
    if what not in ("stats", "multi"):
        import os

        from .layouts import Layout
        from .layouts.draw import LayoutRenderer
        layout = Layout(os.path.abspath(what) if os.path.exists(what) else what)
        if layout.sources:                  # give sources a moment for their first result
            layout.source_values()
            time.sleep(3)
        png = LayoutRenderer(conf["theme"]).render(layout, s)
        if layout.errors:
            print("layout errors:\n  " + "\n  ".join(layout.errors))
    elif what == "multi":
        names = hwmon.select(conf["hwmon_sensors"], "multi", sn.missing(s))[:hwmon.MULTI_PER_PAGE]
        png = r.multi(s, names)
    else:
        png = r.stats(s)
    with open(args[0], "wb") as f:
        f.write(png)
    print(f"wrote {args[0]} ({len(png)} bytes)")


def _preview_themes(out, what="stats"):
    """Contact sheet: the chosen screen in every theme, with this PC's live readings."""
    import io
    import os

    from PIL import Image, ImageDraw

    from .config import load
    from .layouts import Layout
    from .layouts.draw import LayoutRenderer
    from .render import Renderer
    from .render import draw as D
    from .render import theme as T
    from .sensors import Sensors
    conf = load()
    from . import net
    net.set_default(conf["proxy"])
    net.set_logger(print)
    sn = Sensors(conf["fan_map"], conf["vrm_temp_label"], conf["mangohud_folder"])
    sn.sample()
    time.sleep(1)
    s = sn.sample()
    layout = None if what == "stats" else Layout(os.path.abspath(what) if os.path.exists(what) else what,
                                                 log=lambda *a: None)
    cols, w, h, gap, head = 5, 240, 400, 12, 28
    rows = -(-len(T.NAMES) // cols)
    sheet = Image.new("RGB", (cols * (w + gap) + gap, rows * (h + head + gap) + gap), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    for i, name in enumerate(T.NAMES):
        png = LayoutRenderer(name).render(layout, s) if layout else Renderer(name).stats(s)
        im = Image.open(io.BytesIO(png)).convert("RGB").resize((w, h), Image.LANCZOS)
        x, y = gap + (i % cols) * (w + gap), gap + (i // cols) * (h + head + gap)
        d.text((x + w / 2, y + 4), name, font=D.font(8), fill=(230, 230, 230), anchor="ma")
        sheet.paste(im, (x, y + head))
    sheet.save(out)
    print(f"wrote {out}: {len(T.NAMES)} themes")


def _probe():
    from .panel import Panel
    p = Panel.open()
    try:
        for label, fn in (("LCID", p.lcid), ("version", p.version), ("device info", p.device_info),
                          ("display 25", p.get_display)):
            r = fn()
            print(f"{label:12s}", r.hex(" ") if r else "no reply")
    finally:
        p.close()


def _watch():
    from .actions import items
    from .panel import Panel
    p = Panel.open()
    t0, last = time.time(), None
    try:
        while True:
            ev = p.read_event(0.2)
            if ev and (ev.item, ev.flag, ev.x, ev.y) != last:
                last = (ev.item, ev.flag, ev.x, ev.y)
                print(f"{time.time() - t0:7.1f}s item={ev.item:3d} ({items.name(ev.item)}) "
                      f"flag={ev.flag} x={ev.x:3d} y={ev.y:3d}")
    except KeyboardInterrupt:
        pass
    finally:
        p.close()


def _hand_over_picture(args, run_dir="/run/hmid"):
    """picture <file>: the service runs as the hmid user and may not read your files (a
    private home folder). hmictl runs as root: copy the file into the service's runtime
    folder, readable by it, and send that path instead."""
    import os
    import pwd
    import shutil
    path = os.path.expanduser(args[-1])
    if len(args) < 2 or args[1] == "builtin" or not os.path.isfile(path) or os.geteuid() != 0 \
            or not os.path.isdir(run_dir):
        return args
    if os.path.getsize(path) > 200 * 2**20:
        return args                                # far too big anyway: the service says so
    try:
        legik = pwd.getpwnam("hmid")
    except KeyError:
        return args                                # no hmid user: the service runs as root
    dest = os.path.join(run_dir, "picture" + os.path.splitext(path)[1].lower())
    shutil.copyfile(path, dest)
    os.chown(dest, legik.pw_uid, legik.pw_gid)
    os.chmod(dest, 0o640)
    return args[:-1] + [dest]


def _edit_setting(args) -> int | None:
    """set / unset of a setting in /etc/hmid.json: hmictl edits the file itself (hmid may not
    write it) and tells the service to reload. Choices made while running (screen, theme, ...)
    return None and go to the service, which keeps them in its state file."""
    import os

    from . import config
    from .daemon import control
    key = args[1]
    name = key.partition(".")[0]
    if name in config.PERSISTED and "." not in key:
        if args[0] == "unset" and os.geteuid() == 0:
            config.edit(key, remove=True, path=config.PATH)   # also out of /etc/hmid.json: the default returns
        return None
    if args[0] == "set" and len(args) < 3:
        return None                                # the service prints the usage
    if os.geteuid() != 0:
        print(f"changing {name} edits {config.PATH}: use sudo hmictl {' '.join(args)}", file=sys.stderr)
        return 1
    if args[0] == "set":
        conf, err = config.edit(key, config.parse_value(" ".join(args[2:])), path=config.PATH)
    else:
        conf, err = config.edit(key, remove=True, path=config.PATH)
    if err:
        print(f"error {err}")
        return 1
    try:
        out = control.request(["reload"])
    except OSError:
        out = "ok - saved; hmid is not running, it is used at the next start"
    print(out)
    return 1 if out.startswith("error") else 0


def main_ctl(argv=None):
    args = sys.argv[1:] if argv is None else argv
    raw = "--json" in args                         # the service's JSON as it is, for scripts
    args = [a for a in args if a != "--json"]
    if not args or args[0] in ("-h", "--help", "help"):
        print(CTL_HELP)
        return 0
    if args[0] in ("-V", "--version"):
        print(__version__)
        return 0
    if args[0] == "_complete":                     # used by the shell completion scripts
        try:
            print("\n".join(_complete(args[1] if len(args) > 1 else "")))
        except Exception:                          # never print a traceback into the shell
            pass
        return 0
    from .panel import PanelError
    try:
        if args[0] == "preview" and len(args) >= 2:
            _preview(args[1:])
            return 0
        if args[0] == "preview-themes" and len(args) >= 2:
            _preview_themes(args[1], args[2] if len(args) > 2 else "stats")
            return 0
        if args[0] == "check" and len(args) == 2:
            import json as _json

            from .layouts import validate
            with open(args[1]) as f:
                errs = validate(_json.load(f))
            print("\n".join(errs) if errs else "ok")
            return 1 if errs else 0
        if args[0] == "customize" and len(args) == 2:
            from .layouts import customize
            path = customize(args[1])
            print(f"copied to {path} - edit it there; the panel picks up changes within a minute.\n"
                  f"Delete the file to go back to the built-in version (which updates with hmid).")
            return 0
        if args[0] == "lights-state":
            from .lighting import MysticLight
            print(MysticLight().describe())
            return 0
        if args[0] == "probe":
            _probe()
            return 0
        if args[0] == "watch":
            _watch()
            return 0
        if args[0] in ("set", "unset") and len(args) >= 2 and not raw:
            done = _edit_setting(args)
            if done is not None:
                return done
        if args[0] in LOCAL_USAGE:                 # a local tool with missing / extra arguments
            print(f"use: hmictl {LOCAL_USAGE[args[0]]}", file=sys.stderr)
            return 2
    except (OSError, PanelError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    from .daemon import control
    if args[0] == "picture":
        args = _hand_over_picture(args)
    try:
        out = control.request(args)
    except PermissionError:
        print("permission denied - use sudo", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"hmid is not running ({e})", file=sys.stderr)
        return 1
    if not raw:
        from .pretty import format_answer, format_get
        out = format_get(args, out) if args[0] == "get" else format_answer(args[0], out)
    print(out)
    return 1 if out.startswith("error") else 0


if __name__ == "__main__":
    sys.exit(main_ctl())
