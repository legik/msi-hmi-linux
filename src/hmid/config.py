"""Settings in /etc/hmid.json. Every key is optional; see docs/CONFIGURATION.md."""
from __future__ import annotations

import json
import os

PATH = "/etc/hmid.json"                     # yours (root); hmid only reads it
STATE = "/var/lib/hmid/state.json"           # hmid's own: choices made while running (PERSISTED)
SCREENS = ("stats", "hwmon", "clock", "menu")

DEFAULTS = {
    # panel
    "screen": "stats",                 # default screen: stats | hwmon | clock | menu | layout:<name>
    "brightness": 50,                  # 0..100
    "sleep_backlight_off": True,       # backlight 0 while the PC sleeps
    "clock_style": 0,                  # panel clock face 0..9
    "clock_24h": True,
    "menu_user_scenario": False,       # show the panel's User Scenario menu
    "menu_mystic_light": True,         # show the panel's Mystic Light menu
    # stats screen / multi monitor (drawn by hmid)
    "stats_interval": 3,               # seconds between redraws
    "theme": "monokai",                # colour scheme for every screen (hmictl themes): monokai, nord, gruvbox, ...
    "background": None,                # MP4 behind the drawn page (480x800 H.264 baseline); null = built-in
    # hardware monitor
    "hwmon_mode": "list",              # list = panel-drawn, one sensor per screen; multi = tiles drawn by hmid
    "hwmon_style": 2,                  # list mode: panel's built-in style 1..3
    "hwmon_sensors": None,             # names in order (hmictl sensors); null = all (list) / default set (multi)
    "hwmon_auto_hide": True,           # leave out sensors this PC has no reading for
    "hwmon_page_seconds": 6,           # multi mode, more than 12 sensors: seconds per page
    # sensors
    "fan_map": None,                   # e.g. {"cpu_fan": "fan1", "pump": "fan2", "sys_fan": "fan4"}
    "vrm_temp_label": None,            # e.g. "Thermistor 15"; null = sensor chip's 3rd temperature
    "mangohud_folder": "/tmp/hmi-fps", # MangoHud output_folder (FPS while a game runs)
    "game_screen": None,               # screen while a game runs, e.g. "layout:gaming"; null = no switching
    # touch actions and lights
    "touch_actions": {},               # {"<item>": "user:cmd" | "root:cmd" | "builtin:name" | "none"}
    "light_colors": {"82": "0ABAB5"},  # Mystic Light colour per effect item (82 = Steady, Tiffany blue)
    "light_on_start": 92,              # effect applied when the service starts (92 = Rainbow); null = keep
    # network
    "proxy": None,                     # web requests of layouts: "socks5h://127.0.0.1:1080", "http://host:3128"; null = direct
    # troubleshooting
    "debug_events": False,             # log every change the panel reports (item / touch flag)
}

# changed while running (panel buttons, hmictl layout/theme/brightness/hwmon) and kept in
# STATE, which hmid may write; everything else lives only in PATH, which hmid may not write
# (it holds root commands: touch_actions)
PERSISTED = ("screen", "brightness", "hwmon_mode", "theme")


def state_path_for(conf_path: str) -> str:
    """The state file that goes with a settings file (tests use their own folder)."""
    return STATE if conf_path == PATH else os.path.join(os.path.dirname(os.path.abspath(conf_path)),
                                                        "hmid-state.json")


def read_state(state_path: str) -> dict:
    try:
        with open(state_path) as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if k in PERSISTED} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

_TYPES = {
    "screen": str, "brightness": int, "sleep_backlight_off": bool, "clock_style": int, "clock_24h": bool,
    "menu_user_scenario": bool, "menu_mystic_light": bool, "stats_interval": (int, float),
    "theme": str, "background": (str, type(None)), "hwmon_mode": str, "hwmon_style": int,
    "hwmon_sensors": (list, type(None)), "hwmon_auto_hide": bool, "hwmon_page_seconds": (int, float),
    "fan_map": (dict, type(None)), "vrm_temp_label": (str, type(None)), "mangohud_folder": str,
    "touch_actions": dict, "light_colors": dict, "game_screen": (str, type(None)),
    "light_on_start": (int, type(None)), "debug_events": bool, "proxy": (str, type(None)),
}
def _theme_names():
    from .render.theme import NAMES
    return NAMES


_CHOICES = {"screen": SCREENS, "game_screen": SCREENS, "hwmon_mode": ("list", "multi")}


def _migrate(user: dict, warn):
    """Keys from earlier versions."""
    if "hwmon_hide" in user and "hwmon_sensors" not in user:
        from .hwmon import SENSORS
        hide = set(user["hwmon_hide"])
        user["hwmon_sensors"] = [n for n, s in SENSORS.items()
                                 if s.slot not in hide and (s.slot is not None or n in ("upload", "download"))]
        if user.get("hwmon_network") is False:
            user["hwmon_sensors"] = [n for n in user["hwmon_sensors"] if n not in ("upload", "download")]
    if "stats_theme" in user:                       # numeric themes before 0.2
        from .render.theme import name_of
        user.setdefault("theme", name_of(user["stats_theme"]))
        user.pop("stats_theme")
    for old in ("hwmon_hide", "hwmon_network", "menu_timeout", "menu_check", "fast_stats_return",
                "memory_back_to_menu", "hw_values"):
        if old in user:
            warn(f"config: '{old}' is no longer used")
            user.pop(old)


def validate(conf: dict, warn=print) -> dict:
    out = dict(DEFAULTS)
    user = dict(conf)
    _migrate(user, warn)
    for k, v in user.items():
        if k not in DEFAULTS:
            warn(f"config: unknown key '{k}' ignored")
            continue
        t = _TYPES.get(k)
        if t and not isinstance(v, t) or (t is int and isinstance(v, bool)):
            warn(f"config: '{k}' has the wrong type ({type(v).__name__}), using default {DEFAULTS[k]!r}")
            continue
        if k in ("screen", "game_screen") and isinstance(v, str) and v.startswith("layout:") and len(v) > 7:
            out[k] = v
            continue
        if k == "theme" and v not in _theme_names():
            warn(f"config: unknown theme '{v}' (hmictl themes lists them), using {DEFAULTS[k]!r}")
            continue
        if k == "proxy" and v:
            from .net import parse
            try:
                parse(v)
            except ValueError as e:
                warn(f"config: proxy: {e}; not using a proxy")
                continue
        if k in _CHOICES and v not in _CHOICES[k]:
            warn(f"config: '{k}' must be one of {', '.join(_CHOICES[k])}, using default {DEFAULTS[k]!r}")
            continue
        out[k] = v
    out["brightness"] = max(0, min(100, out["brightness"]))
    return out


def load(path: str = PATH, warn=print, state: str | None = "auto") -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("top level must be an object")
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as e:
        warn(f"config: {path} unreadable ({e}), using defaults")
        data = {}
    if state:
        data = {**data, **read_state(state_path_for(path) if state == "auto" else state)}
    return validate(data, warn)


def save_state(conf: dict, state_path: str = STATE, warn=print):
    """Keep the choices made while running (PERSISTED keys) in hmid's state file."""
    try:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        tmp = state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({k: conf[k] for k in PERSISTED if k in conf}, f, indent=2)
            f.write("\n")
        os.replace(tmp, state_path)
    except OSError as e:
        warn(f"config: could not save {state_path}: {e}")


def forget_state(key: str, state_path: str = STATE):
    """Drop one choice from the state file (hmictl unset): the settings file decides again."""
    data = read_state(state_path)
    if key in data:
        data.pop(key)
        tmp = state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, state_path)


# ---- changing single settings (hmictl set / unset) ---------------------------------------
NESTED = ("touch_actions", "light_colors", "fan_map")      # objects that take key.sub
_ACTION_KINDS = ("user:", "root:", "builtin:")


def parse_value(text: str):
    """Command-line text -> value: JSON when it is JSON (true, 50, null, [..], {..}), else text."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def _read_file(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be an object")
    return data


def edit(key: str, value=None, remove=False, path: str = PATH):
    """Set (or remove) one setting in the file, checked first. key may be "touch_actions.250".
    Returns (new validated settings, None) or (None, error message); the file is only
    written when the change is valid."""
    name, _, sub = key.partition(".")
    if name not in DEFAULTS:
        close = [k for k in DEFAULTS if name in k or k in name]
        return None, f"unknown setting '{name}'" + (f" (did you mean {', '.join(close)}?)" if close else "")
    if sub and name not in NESTED:
        return None, f"'{name}' has no sub-keys (only {', '.join(NESTED)} do)"
    try:
        data = _read_file(path)
    except (OSError, ValueError) as e:
        return None, f"cannot read {path}: {e}"
    new = json.loads(json.dumps(data))
    if sub:
        obj = dict(new.get(name) or {})
        if remove:
            obj.pop(sub, None)
        else:
            obj[sub] = value
        if obj:
            new[name] = obj
        else:
            new.pop(name, None)
    elif remove:
        new.pop(name, None)
    else:
        new[name] = value
    if name == "touch_actions" and not remove:
        for item, action in (new.get(name) or {}).items():
            if not str(item).isdigit():
                return None, f"touch_actions: '{item}' is not a panel item number"
            if not (action == "none" or (isinstance(action, str) and action.startswith(_ACTION_KINDS))):
                return None, f"touch_actions.{item}: use user:<command>, root:<command>, builtin:<name> or none"
    before, after = [], []
    validate(data, warn=before.append)
    conf = validate(new, warn=after.append)
    fresh = [w for w in after if w not in before]
    if fresh:
        return None, "; ".join(w.removeprefix("config: ") for w in fresh)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(new, f, indent=2)
            f.write("\n")
        if os.path.exists(path):                    # keep legik and mode (root:hmid 640)
            st = os.stat(path)
            os.chmod(tmp, st.st_mode & 0o7777)
            if os.geteuid() == 0:
                os.chown(tmp, st.st_uid, st.st_gid)
        os.replace(tmp, path)
    except OSError as e:
        return None, f"cannot save {path}: {e}"
    return conf, None


def in_file(path: str = PATH, state_path: str | None = None) -> list[str]:
    """Settings set by the file or the state file (the rest are defaults)."""
    try:
        keys = list(_read_file(path))
    except (OSError, ValueError):
        keys = []
    return keys + [k for k in read_state(state_path or state_path_for(path)) if k not in keys]
