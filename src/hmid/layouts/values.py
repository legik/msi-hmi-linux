"""Named values a layout can show, and the template formatter.

Templates use Python format syntax with names from values():
    "{cpu_load:.0f}%"   "{time:%H:%M}"   "{download}"   "{subs:,.0f}"
A value that has no reading shows as "–"; an unknown name shows as "?name".
"""
from __future__ import annotations

import math
import re
import string
import time
from datetime import datetime

from ..hwmon import fmt_rate
from ..sensors import Sample

MISSING = "–"


def values(s: Sample, extra: dict | None = None) -> dict:
    g = s.gpu
    gm = s.game
    fan = lambda role, i: s.fans[role][i] if role in s.fans else None
    v = {
        "time": s.time,
        "cpu_load": s.cpu_load, "cpu_temp": s.cpu_temp, "cpu_power": s.cpu_power,
        "cpu_clock": s.cpu_mhz, "cpu_ghz": s.cpu_mhz / 1000 if s.cpu_mhz else None,
        "ram_used": s.mem_used, "ram_total": s.mem_total,
        "ram_pct": 100 * s.mem_used / s.mem_total if s.mem_total else None,
        "ram_clock": s.mem_mhz or None,
        "gpu_load": g.load if g else None, "gpu_temp": g.temp if g else None,
        "gpu_power": g.power if g else None, "gpu_clock": (g.clock or None) if g else None,
        "gpu_fan_pct": g.fan_pct if g else None, "gpu_power_limit": g.power_limit if g else None,
        "vram_used": g.mem_used if g else None, "vram_total": (g.mem_total or None) if g else None,
        "net_down": s.net_down, "net_up": s.net_up,
        "download": fmt_rate(s.net_down), "upload": fmt_rate(s.net_up),
        "cpu_fan": fan("cpu_fan", 0), "cpu_fan_pct": fan("cpu_fan", 1),
        "pump": fan("pump", 0),
        "sys_fan": fan("sys_fan", 0), "sys_fan_pct": fan("sys_fan", 1),
        "vrm_temp": s.vrm_temp,
        "fps": gm.fps if gm else None, "frametime": gm.frametime if gm else None,
        "game": gm.app if gm else None,
    }
    if extra:
        v.update(extra)
    return v


NAMES = sorted(values(Sample()).keys())


# ---- paths and filters --------------------------------------------------------------
# A name can be a path into a JSON source and end in filters:
#     weather.current.temperature_2m          weather.daily.temperature_2m_max.0
#     weather.current|wmo_icon                weather.hourly.uv_index|now|uv_level
WMO = {
    0: ("Clear sky", "clear"), 1: ("Mainly clear", "clear"), 2: ("Partly cloudy", "partly"), 3: ("Overcast", "cloudy"),
    45: ("Fog", "fog"), 48: ("Rime fog", "fog"),
    51: ("Light drizzle", "drizzle"), 53: ("Drizzle", "drizzle"), 55: ("Dense drizzle", "drizzle"),
    56: ("Freezing drizzle", "drizzle"), 57: ("Freezing drizzle", "drizzle"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"), 77: ("Snow grains", "snow"),
    80: ("Rain showers", "rain"), 81: ("Rain showers", "rain"), 82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"), 86: ("Snow showers", "snow"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm, hail", "storm"), 99: ("Thunderstorm, hail", "storm"),
}
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def _code(v):
    if isinstance(v, dict):
        v = v.get("weather_code")
    return int(float(v))


def _now_index(times, root):
    """Index of the current hour in an hourly time list ("2026-10-18T16:00"), in the
    location's time zone when the source gives utc_offset_seconds."""
    off = root.get("utc_offset_seconds") if isinstance(root, dict) else None
    t = time.gmtime(time.time() + off) if off is not None else time.localtime()
    key = time.strftime("%Y-%m-%dT%H:00", t)
    if isinstance(times, list) and key in times:
        return times.index(key)
    return t.tm_hour


def _hourly_times(root):
    return root.get("hourly", {}).get("time") if isinstance(root, dict) else None


def _f_now(v, root):
    if not isinstance(v, list) or not v:
        return None
    i = _now_index(_hourly_times(root), root)
    return v[min(i, len(v) - 1)]


def _f_wmo_icon(v, root):
    icon = WMO.get(_code(v), ("", "cloudy"))[1]
    day = v.get("is_day", 1) if isinstance(v, dict) else 1
    if not day and icon in ("clear", "partly"):
        icon = "moon" if icon == "clear" else "partly_night"
    return icon


# MET Norway symbol codes (e.g. "lightrainshowersandthunder_day") -> text and icon
_MET_WORDS = ("clearsky", "partlycloudy", "cloudy", "fair", "fog", "light", "heavy", "rain", "sleet", "snow",
              "showers", "and", "thunder")
_MET_TEXT = {"clearsky": "Clear sky", "partlycloudy": "Partly cloudy", "fair": "Fair"}


def _met_base(v):
    code = str(v)
    base, _, period = code.partition("_")
    return base, period


def _f_met_text(v, root):
    base, _ = _met_base(v)
    words, rest = [], base
    while rest:
        w = next((w for w in _MET_WORDS if rest.startswith(w)), None)
        if not w:
            words.append(rest)
            break
        words.append(_MET_TEXT.get(w, w))
        rest = rest[len(w):]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def _f_met_icon(v, root):
    base, period = _met_base(v)
    night = period == "night"
    if "thunder" in base:
        return "storm"
    if "snow" in base or "sleet" in base:
        return "snow"
    if "rain" in base:
        return "drizzle" if base.startswith("light") else "rain"
    if base == "fog":
        return "fog"
    if base == "cloudy":
        return "cloudy"
    if base in ("partlycloudy", "fair"):
        return "partly_night" if night else "partly"
    return "moon" if night else "clear"


def _f_feels(v, root):
    """Apparent temperature (Steadman / Australian BoM) from a dict with air_temperature,
    relative_humidity and wind_speed (m/s) - for sources that do not provide feels-like."""
    t, rh, ws = float(v["air_temperature"]), float(v["relative_humidity"]), float(v.get("wind_speed", 0))
    e = rh / 100 * 6.105 * math.exp(17.27 * t / (237.7 + t))
    return t + 0.33 * e - 0.70 * ws - 4.00


def _iso(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def _f_time(v, root):
    """ISO date-time -> HH:MM. With a zone (Z, +02:00) it is shown in this PC's time zone."""
    try:
        d = _iso(v)
    except ValueError:
        return str(v).split("T")[-1][:5]
    if d.tzinfo is not None:
        d = d.astimezone()
    return d.strftime("%H:%M")


def _local(v):
    d = _iso(v)
    return d.astimezone() if d.tzinfo is not None else d


def _f_date(v, root):
    """ISO date-time -> "Mon 20 Oct" (this PC's time zone)."""
    return _local(v).strftime("%a %d %b")


def _f_ago(v, root):
    """ISO date-time -> "5 min ago" / "3 h ago" / "2 d ago", or "in 3 h" for a future time."""
    d = _local(v)
    secs = time.time() - d.timestamp()
    n = abs(secs)
    if n < 60:
        return "now"
    for size, unit in ((86400, "d"), (3600, "h"), (60, "min")):
        if n >= size:
            text = f"{int(n // size)} {unit}"
            break
    return f"{text} ago" if secs > 0 else f"in {text}"


def _f_today(v, root):
    """List of entries with a "time" -> only those on today's date (this PC's time zone)."""
    today = datetime.now().astimezone().date()
    out = []
    for e in v:
        try:
            d = _iso(e["time"])
            if (d.astimezone() if d.tzinfo else d).date() == today:
                out.append(e)
        except (KeyError, TypeError, ValueError):
            pass
    return out


def _get(obj, path):
    for part in str(path).split("."):
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


def _f_pluck(v, root, path):
    """List of entries -> the value at `path` in each (entries without it are skipped)."""
    out = []
    for e in v:
        try:
            out.append(_get(e, path))
        except (KeyError, IndexError, TypeError, ValueError):
            pass
    return out


def _numbers(v):
    return [float(x) for x in v if isinstance(x, (int, float)) or str(x).replace(".", "", 1).lstrip("-").isdigit()]


def _f_uv_level(v, root):
    v = float(v)
    return "LOW" if v < 3 else "MOD" if v < 6 else "HIGH"


FILTERS = {
    "wmo": lambda v, root: WMO.get(_code(v), (f"code {_code(v)}", ""))[0],
    "wmo_icon": _f_wmo_icon,
    "compass": lambda v, root: COMPASS[int((float(v) % 360) / 45 + 0.5) % 8],
    "uv_level": _f_uv_level,
    "time": _f_time,                                                      # ISO date-time -> HH:MM
    "date": _f_date,                                                      # ISO date-time -> Mon 20 Oct
    "ago": _f_ago,                                                        # ISO date-time -> 3 h ago / in 2 d
    "now": _f_now,                                                        # hourly list -> current hour's value
    "hour_index": lambda v, root: _now_index(v if isinstance(v, list) else _hourly_times(root), root),
    "upper": lambda v, root: str(v).upper(),
    "round": lambda v, root: round(float(v)),
    "met_text": _f_met_text,                                              # MET Norway symbol -> text
    "met_icon": _f_met_icon,                                              # MET Norway symbol -> icon name
    "feels": _f_feels,
    "today": _f_today,
    "max": lambda v, root: max(_numbers(v)) if _numbers(v) else None,
    "min": lambda v, root: min(_numbers(v)) if _numbers(v) else None,
    # filters with an argument: name(arg)
    "pluck": _f_pluck,
    "first": lambda v, root, n: list(v)[:int(n)],
    "mul": lambda v, root, x: float(v) * float(x),
    "line": lambda v, root, n: _f_line(v, int(n)),
    "compact": lambda v, root: _f_compact(v),
}


def _f_line(v, n):
    """Line n (from 0) of a command's text output; None past the end or when empty."""
    lines = str(v).splitlines()
    return lines[n].strip() or None if 0 <= n < len(lines) else None


def _f_compact(v):
    """128456 -> 128.5K, 2300000 -> 2.3M, 950 -> 950."""
    x = float(v)
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= div:
            s = f"{x / div:.1f}".rstrip("0").rstrip(".") if abs(x) < 100 * div else f"{x / div:.0f}"
            return s + unit
    return f"{x:.0f}"
_ARG = re.compile(r"^(\w+)\((.*)\)$")


def resolve(vals: dict, expr: str):
    """Value of a name / path / filter chain, or None when it has no reading."""
    path, *filters = str(expr).split("|")
    parts = path.split(".")
    if parts[0] not in vals:
        raise KeyError(parts[0])
    v = root = vals[parts[0]]
    try:
        for part in parts[1:]:
            if v is None:
                return None
            v = v[int(part)] if isinstance(v, list) else v[part]
        for f in filters:
            if v is None:
                return None
            f = f.strip()
            m = _ARG.match(f)
            v = FILTERS[m.group(1)](v, root, m.group(2)) if m else FILTERS[f](v, root)
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    return v


class _Formatter(string.Formatter):
    def get_field(self, field_name, args, kwargs):
        try:
            return resolve(kwargs, field_name), field_name
        except KeyError:
            return f"?{field_name.split('|')[0]}", field_name

    def format_field(self, value, spec):
        if value is None:
            return MISSING
        if isinstance(value, time.struct_time):
            return time.strftime(spec or "%H:%M", value)
        if spec and isinstance(value, str):
            try:
                value = float(value)                 # numeric text from a source
            except ValueError:
                return value
        try:
            return format(value, spec)
        except (ValueError, TypeError):
            return str(value)


_fmt = _Formatter()


def render_text(template: str, vals: dict) -> str:
    try:
        return _fmt.vformat(str(template), (), vals)
    except (ValueError, IndexError, KeyError) as e:
        return f"[{e}]"


def number(vals: dict, name: str):
    """A value (name, path or filter chain) as float, or None."""
    try:
        v = resolve(vals, name)
    except KeyError:
        return None
    if v is None or isinstance(v, time.struct_time):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def series(vals: dict, name: str) -> list[float]:
    """A list value (e.g. hourly temperatures) as floats."""
    try:
        v = resolve(vals, name)
    except KeyError:
        return []
    out = []
    for x in v if isinstance(v, list) else []:
        try:
            out.append(float(x))
        except (TypeError, ValueError):
            pass
    return out


_COND = re.compile(r"^(.*?)(<=|>=|=|<|>)(.*)$")


def truthy(vals: dict, cond: str) -> bool:
    """Widget "when": "fps" (shown while fps has a reading) or "!fps". With a comparison:
    "ci.status=completed" (text, any case), "change<0", "cpu_temp>=80" (numbers)."""
    neg = cond.startswith("!")
    m = _COND.match(cond.lstrip("!"))
    name = m.group(1).strip() if m else cond.lstrip("!")
    try:
        v = resolve(vals, name)
    except KeyError:
        v = None
    if not m:
        ok = v not in (None, "", 0, False)
    elif v is None:
        ok = False
    elif m.group(2) == "=":
        ok = str(v).strip().lower() == m.group(3).strip().lower()
    else:
        try:
            a, b = float(v), float(m.group(3))
        except (TypeError, ValueError):
            return neg
        ok = {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[m.group(2)]
    return ok != neg
