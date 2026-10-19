"""Screens described in JSON ("layouts"): widgets on the 480x800 canvas.

    built-in   hmid/data/layouts/<name>.json   shipped and updated with the program
    yours      /etc/hmid/layouts/<name>.json   your own; same name = replaces the built-in one
    selected with  "screen": "layout:<name>"   (hmictl customize <name> makes an editable copy)

See docs/LAYOUTS.md for the format. Files are re-read when they change, so edits show
up on the panel at the next redraw. Errors are drawn on the panel and logged.
"""
from __future__ import annotations

import json
import os
import stat

from .sources import TYPES as SOURCE_TYPES
from .sources import Source

DIR = "/etc/hmid/layouts"
BUILTIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "layouts")
PREFIX = "layout:"

# widget type -> (required keys, optional keys)
WIDGETS = {
    "text":    ({"x", "y", "text"}, {"size", "color", "align", "bold", "spacing", "value", "rule", "max_width",
                                      "transform", "suffix", "suffix_size", "suffix_color", "suffix_gap",
                                      "warn", "crit"}),
    "card":    ({"x", "y", "w", "h"}, {"fill", "border"}),
    "divider": ({"y"}, set()),
    "bar":     ({"x", "y", "w", "value"}, {"min", "max", "rule", "warn", "crit", "height"}),
    "sensor":  ({"x", "y", "w", "h", "sensor"}, {"label", "size", "unit_size", "unit_gap",
                                                 "bar", "bar_min", "bar_max", "bar_rule", "bar_color"}),
    "graph":   ({"x", "y", "w", "h"}, {"value", "series", "marker", "max", "min", "seconds", "color", "fill", "clip"}),
    "ring":    ({"x", "y", "size", "value"}, {"min", "max", "width", "rule", "warn", "crit", "color"}),
    "icon":    ({"x", "y", "size", "icon"}, set()),
    "image":   ({"x", "y", "path"}, {"w", "h", "fit", "radius"}),
}
COMMON = {"type", "when", "comment"}


def _names(directory: str) -> set[str]:
    try:
        return {f[:-5] for f in os.listdir(directory) if f.endswith(".json")}
    except OSError:
        return set()


def path_for(name: str, directory: str = DIR, builtin: str = BUILTIN) -> str:
    """'gaming' -> your /etc/hmid/layouts/gaming.json if it exists, else the built-in one.
    Anything with a '/' is a file path."""
    if name.startswith(PREFIX):
        name = name[len(PREFIX):]
    if os.sep in name:                          # a file path (absolute or relative)
        return os.path.abspath(name)
    file = name if name.endswith(".json") else name + ".json"
    mine, shipped = os.path.join(directory, file), os.path.join(builtin, file)
    if not os.path.exists(mine) and os.path.exists(shipped):
        return shipped
    return mine


def catalog(directory: str = DIR, builtin: str = BUILTIN) -> dict[str, str]:
    """name -> "built-in" | "yours" | "yours (replaces built-in)"."""
    mine, shipped = _names(directory), _names(builtin)
    return {n: ("yours (replaces built-in)" if n in mine and n in shipped else "yours" if n in mine else "built-in")
            for n in sorted(mine | shipped)}


def available(directory: str = DIR, builtin: str = BUILTIN) -> list[str]:
    return list(catalog(directory, builtin))


def customize(name: str, directory: str = DIR, builtin: str = BUILTIN) -> str:
    """Copy a built-in layout to `directory` for editing; returns the new path."""
    import shutil
    file = (name[len(PREFIX):] if name.startswith(PREFIX) else name).removesuffix(".json") + ".json"
    src, dst = os.path.join(builtin, file), os.path.join(directory, file)
    if not os.path.exists(src):
        raise FileNotFoundError(f"no built-in layout '{file[:-5]}' (built-in: {', '.join(sorted(_names(builtin)))})")
    if os.path.exists(dst):
        raise FileExistsError(f"{dst} already exists - edit it, or delete it to go back to the built-in version")
    os.makedirs(directory, exist_ok=True)
    shutil.copyfile(src, dst)
    os.chmod(dst, 0o644)
    return dst


def trusted(path: str) -> bool:
    """Commands run as root, so only from files that only root can change."""
    try:
        st = os.stat(path)
        dst = os.stat(os.path.dirname(os.path.abspath(path)))
    except OSError:
        return False
    no_write = lambda s: not (s.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
    return st.st_uid == 0 and no_write(st) and dst.st_uid == 0 and no_write(dst)


def validate(data) -> list[str]:
    """Problems in a layout, as readable messages (empty = fine)."""
    from .. import hwmon
    if not isinstance(data, dict):
        return ["the file must contain a JSON object"]
    errs = []
    unknown = set(data) - {"widgets", "sources", "background", "refresh", "theme", "colors", "comment"}
    if unknown:
        errs.append(f"unknown top-level keys: {', '.join(sorted(unknown))}")
    from ..render.theme import TOKENS, parse
    colors = data.get("colors", {})
    if not isinstance(colors, dict):
        errs.append("'colors' must be an object")
        colors = {}
    for k, v in colors.items():
        if k not in TOKENS:
            errs.append(f"colors: unknown name '{k}' (use: {', '.join(TOKENS)})")
        elif not (v is None and k == "glow") and parse(v) is None:
            errs.append(f"colors: '{k}' must be #RRGGBB or #RRGGBBAA")
    widgets = data.get("widgets")
    if not isinstance(widgets, list) or not widgets:
        errs.append("'widgets' must be a non-empty list")
        widgets = []
    for i, w in enumerate(widgets):
        where = f"widget {i + 1}"
        if not isinstance(w, dict) or w.get("type") not in WIDGETS:
            errs.append(f"{where}: 'type' must be one of {', '.join(WIDGETS)}")
            continue
        req, opt = WIDGETS[w["type"]]
        where = f"widget {i + 1} ({w['type']})"
        if req - set(w):
            errs.append(f"{where}: missing {', '.join(sorted(req - set(w)))}")
        extra = set(w) - req - opt - COMMON
        if extra:
            errs.append(f"{where}: unknown keys {', '.join(sorted(extra))}")
        for k in ("x", "y", "w", "h", "size", "seconds", "height", "spacing", "max_width", "width",
                  "suffix_size", "suffix_gap", "unit_size", "unit_gap"):
            if k in w and not isinstance(w[k], (int, float)):
                errs.append(f"{where}: '{k}' must be a number")
        if w.get("fit", "stretch") not in ("stretch", "cover", "contain"):
            errs.append(f"{where}: 'fit' must be stretch, cover or contain")
        if w["type"] == "graph" and ("value" in w) == ("series" in w):
            errs.append(f"{where}: needs either 'value' (history) or 'series' (a list value)")
        for k in ("min", "max", "bar_min", "bar_max", "warn", "crit"):   # a number, or a value name
            if k in w and not isinstance(w[k], (int, float, str)):
                errs.append(f"{where}: '{k}' must be a number or a value name")
        if w.get("transform", "upper") not in ("upper", "lower", "title"):
            errs.append(f"{where}: 'transform' must be upper, lower or title")
        if w["type"] == "sensor" and w.get("sensor") not in hwmon.SENSORS:
            errs.append(f"{where}: unknown sensor {w.get('sensor')!r} (see: hmictl sensors)")
    sources = data.get("sources", {})
    if not isinstance(sources, dict):
        errs.append("'sources' must be an object")
        sources = {}
    for name, spec in sources.items():
        if not isinstance(spec, dict) or spec.get("type") not in SOURCE_TYPES:
            errs.append(f"source '{name}': 'type' must be one of {', '.join(SOURCE_TYPES)}")
            continue
        need = {"command": "run", "file": "path", "http": "url"}[spec["type"]]
        if need not in spec:
            errs.append(f"source '{name}': missing '{need}'")
        if "proxy" in spec and spec["proxy"] not in (None, False):
            from ..net import parse
            try:
                parse(spec["proxy"]) if isinstance(spec["proxy"], str) else parse("")
            except ValueError as e:
                errs.append(f"source '{name}': {e} (or false for a direct connection)")
        if spec.get("as", "root") not in ("root", "user"):
            errs.append(f"source '{name}': 'as' must be root or user")
    return errs


class Layout:
    """A layout file, re-read when it changes."""

    def __init__(self, name: str, directory: str = DIR, log=print):
        self.path = path_for(name, directory)
        self.name = os.path.basename(self.path)[:-5] if self.path.endswith(".json") else os.path.basename(self.path)
        self.log = log
        self.data: dict = {}
        self.errors: list[str] = []
        self.sources: dict[str, Source] = {}
        self.history: dict = {}            # graph data, kept across reloads
        self._mtime = None
        self.reload()

    def reload(self):
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            if self._mtime != -1:
                self.errors = [f"layout file not found: {self.path}"]
                self.log(self.errors[0])
            self._mtime = -1
            return
        if mtime == self._mtime:
            return
        self._mtime = mtime
        try:
            with open(self.path) as f:
                data = json.load(f)
            errs = validate(data)
        except (OSError, ValueError) as e:
            data, errs = {}, [f"cannot read {os.path.basename(self.path)}: {e}"]
        self.errors = errs
        for e in errs:
            self.log(f"layout {self.name}: {e}")
        if errs:
            return
        self.data = data
        allow = trusted(self.path)
        self.sources = {n: Source(n, spec, allow, self.log, layout_path=self.path)
                        for n, spec in data.get("sources", {}).items()}
        origin = "built-in" if os.path.dirname(self.path) == BUILTIN else \
            "yours, replaces the built-in one" if os.path.exists(os.path.join(BUILTIN, os.path.basename(self.path))) else "yours"
        self.log(f"layout {self.name} loaded ({len(data['widgets'])} widgets, {len(self.sources)} sources; {origin})")

    def refresh_seconds(self, default):
        return self.data.get("refresh", default)

    def source_values(self) -> dict:
        return {n: s.get() for n, s in self.sources.items()}
