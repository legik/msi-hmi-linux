"""Drawing a layout's widgets onto the 480x800 overlay."""
from __future__ import annotations

import io
import os
import threading
import time

from PIL import Image, ImageDraw

from .. import hwmon
from ..hwmon import load_state, temp_state
from ..panel.protocol import HEIGHT as H
from ..panel.protocol import WIDTH as W
from ..render import draw as D
from ..render import theme as T
from ..render.pages import tile
from . import Layout
from .values import MISSING, number, render_text, series, truthy, values

STATE_RULES = {"load": load_state, "temp": temp_state}


def color(spec, th: T.Theme, default=None):
    """'#RRGGBB', '#RRGGBBAA' or a theme name (text, secondary, header, value, accent, ...)."""
    if spec is None:
        return default or th.primary
    names = {"text": th.primary, "white": T.TEXT_PRIMARY, "secondary": th.secondary,
             "header": th.header, "value": th.normal_text, "accent": th.accent, "accent_dark": th.accent_dark,
             "tiffany": T.TIFFANY, "tiffany_dark": T.TIFFANY_DARK,
             "warn": th.warn, "crit": th.crit, "track": th.track, "card": th.card_bg}
    if spec in names:
        return names[spec]
    return T.parse(spec) or default or th.primary


def limit(spec, vals, default):
    """A number, or the name of a value (e.g. "gpu_power_limit")."""
    if isinstance(spec, (int, float)):
        return float(spec)
    if isinstance(spec, str):
        v = number(vals, spec)
        if v:
            return v
    return default


TRANSFORMS = {"upper": str.upper, "lower": str.lower, "title": str.title}


def threshold_state(w, vals, v):
    """Explicit "warn"/"crit" thresholds on a widget (numbers or value names), or None."""
    if v is None or ("warn" not in w and "crit" not in w):
        return None
    crit, warn = limit(w.get("crit"), vals, None), limit(w.get("warn"), vals, None)
    if crit is not None and v >= crit:
        return "crit"
    if warn is not None and v >= warn:
        return "warn"
    return "normal"


def describe(layout: Layout, renderer: "LayoutRenderer", sample) -> dict:
    """What a layout gets right now: its file, each source's value or error, and what each
    picture widget points to and whether it loaded (hmictl sources)."""
    import os as _os

    from . import BUILTIN
    vals = values(sample, layout.source_values())
    out = {"layout": layout.name, "file": layout.path,
           "origin": "built-in" if _os.path.dirname(layout.path) == BUILTIN else "yours (/etc/hmid/layouts)",
           "errors": layout.errors, "sources": {}, "pictures": []}
    now = time.time()
    for n, s in layout.sources.items():
        v = s.value
        out["sources"][n] = {"value": v if not isinstance(v, (dict, list)) else f"<JSON {type(v).__name__}>",
                             "error": s.error,
                             "updated_s_ago": round(now - s._t, 1) if s._t else None,
                             "as": s.spec.get("as", "root") if s.kind == "command" else None}
    for i, w in enumerate(layout.data.get("widgets", [])):
        if w.get("type") != "image":
            continue
        shown = "when" not in w or truthy(vals, w["when"])
        path = render_text(w["path"], vals).strip() if "{" in w["path"] else w["path"]
        state = "hidden (when: {})".format(w["when"]) if not shown else \
            "empty path" if not path or path == MISSING else \
            f"unknown value {path[1:]!r}" if path.startswith("?") else renderer.pictures.state(path)
        out["pictures"].append({"widget": i + 1, "path_template": w["path"], "path": path, "state": state})
    return out


class LayoutRenderer:
    def __init__(self, theme_id=2):
        self.theme = T.get(theme_id)
        self._canvas: dict = {}
        self._images: dict = {}
        self.pictures = Pictures()

    def theme_for(self, data) -> T.Theme:
        base = T.get(data["theme"]) if "theme" in data else self.theme      # a layout may pin a theme by name
        return T.with_colors(base, data.get("colors")) if data.get("colors") else base

    # ---- page -----------------------------------------------------------------------
    def render(self, layout: Layout, sample) -> bytes:
        self._sample = sample
        layout.reload()
        if layout.errors:
            return self.error_page(layout)
        data = layout.data
        th = self.theme_for(data)
        vals = values(sample, layout.source_values())
        im = self._background(data.get("background"), th)
        for w in data["widgets"]:
            if "when" in w and not truthy(vals, w["when"]):
                continue
            try:
                getattr(self, "w_" + w["type"])(im, w, vals, th, layout)
            except Exception as e:           # one bad widget must not blank the page
                layout.log(f"layout {layout.name}: {w['type']} widget failed: {e}")
        return D.to_png(im)

    def error_page(self, layout: Layout) -> bytes:
        im = Image.new("RGBA", (W * D.S, H * D.S), T.BG_CANVAS)
        d = ImageDraw.Draw(im)
        D.text(d, (24, 24), f"LAYOUT {layout.name.upper()}", 20, T.CRIT)
        y = 64
        for e in layout.errors[:12]:
            for line in _wrap(e, 15, W - 48):
                D.text(d, (24, y), line, 15, T.TEXT_PRIMARY, bold=False)
                y += 22
            y += 8
        D.text(d, (24, H - 40), "fix the file - it is re-read automatically", 14, T.TEXT_SECONDARY, bold=False)
        return D.to_png(im)

    def _background(self, spec, th):
        if isinstance(spec, dict) and spec.get("image"):
            img = self._image(spec["image"], W, H)
            if img is not None:
                im = Image.new("RGBA", (W * D.S, H * D.S), th.canvas)
                im.alpha_composite(img)
                return im
        if isinstance(spec, dict) and spec.get("color"):
            return Image.new("RGBA", (W * D.S, H * D.S), color(spec["color"], th))
        if th not in self._canvas:
            self._canvas[th] = D.background(th)
        return self._canvas[th].copy()

    def _image(self, path, w=None, h=None):
        try:
            mt = os.path.getmtime(path)
        except OSError:
            return None
        key = (path, w, h)
        if key not in self._images or self._images[key][0] != mt:
            img = Image.open(path).convert("RGBA")
            if w and h:
                img = img.resize((int(w * D.S), int(h * D.S)), Image.LANCZOS)
            else:
                img = img.resize((img.width * D.S, img.height * D.S), Image.LANCZOS)
            self._images[key] = (mt, img)
        return self._images[key][1]

    # ---- widgets -------------------------------------------------------------------------
    def w_text(self, im, w, vals, th, layout):
        txt = render_text(w["text"], vals)
        if w.get("transform") in TRANSFORMS:
            txt = TRANSFORMS[w["transform"]](txt)
        size, bold, spacing = w.get("size", 20), w.get("bold", True), w.get("spacing", 0)
        fill = color(w.get("color"), th)
        if "value" in w and ("rule" in w or "warn" in w or "crit" in w):
            v = number(vals, w["value"])
            state = threshold_state(w, vals, v) or STATE_RULES.get(w.get("rule"), lambda v: None)(v)
            if state in ("warn", "crit"):
                fill = th.state_color(state)
        if "max_width" in w:
            while txt and D.text_width(txt, size, bold) + spacing * len(txt) > w["max_width"]:
                txt = txt[:-2] + "…" if len(txt) > 1 else ""
        d = ImageDraw.Draw(im)
        align = w.get("align", "left")
        if "suffix" in w:                    # number + unit on one baseline
            suffix = render_text(w["suffix"], vals)
            ss, gap = w.get("suffix_size", 22), w.get("suffix_gap", 4)
            total = D.text_width(txt, size, bold) + gap + D.text_width(suffix, ss, False)
            x = w["x"] - (total / 2 if align == "center" else total if align == "right" else 0)
            D.text_unit(d, x, w["y"], txt, size, fill, suffix, ss, color(w.get("suffix_color", "secondary"), th), gap, bold)
            return
        anchor = {"left": "la", "center": "ma", "right": "ra"}.get(align, "la")
        D.text(d, (w["x"], w["y"]), txt, size, fill, anchor, bold, spacing)

    def w_card(self, im, w, vals, th, layout):
        D.card(im, w["x"], w["y"], w["w"], w["h"], th, w.get("fill", True), w.get("border", True))

    def w_divider(self, im, w, vals, th, layout):
        D.divider(im, w["y"], th)

    def w_bar(self, im, w, vals, th, layout):
        v = number(vals, w["value"])
        lo, hi = limit(w.get("min", 0), vals, 0.0), limit(w.get("max"), vals, 100.0)
        pct = None if v is None else max(0.0, min(100.0, 100 * (v - lo) / max(hi - lo, 1e-9)))
        state = threshold_state(w, vals, v) or STATE_RULES.get(w.get("rule", "load"), lambda v: None)(pct)
        D.bar(im, w["x"], w["y"], w["w"], pct, state, th)

    def w_ring(self, im, w, vals, th, layout):
        """Circular progress centred on x, y; `size` is the outer diameter."""
        v = number(vals, w["value"])
        lo, hi = limit(w.get("min", 0), vals, 0.0), limit(w.get("max"), vals, 100.0)
        pct = None if v is None else max(0.0, min(100.0, 100 * (v - lo) / max(hi - lo, 1e-9)))
        state = threshold_state(w, vals, v) or STATE_RULES.get(w.get("rule", "load"), lambda v: None)(pct)
        D.ring(im, w["x"], w["y"], w["size"], w.get("width", 14), pct, state, th,
               color(w["color"], th) if "color" in w else None)

    def w_icon(self, im, w, vals, th, layout):
        from ..render.icons import NAMES, draw_icon
        name = render_text(w["icon"], vals)
        if name in NAMES:
            draw_icon(im, name, w["x"], w["y"], w["size"], th)

    def w_sensor(self, im, w, vals, th, layout):
        name = w["sensor"]
        r = hwmon.readings(self._sample)[name]
        label = w.get("label", hwmon.SENSORS[name].label)
        big = w.get("size", 34 if w["w"] < 300 else 48)
        bar = None
        if w.get("bar") is False:
            bar = False
        elif "bar_min" in w or "bar_max" in w or "bar_rule" in w or "bar_color" in w:
            v = number(vals, name)
            lo = limit(w.get("bar_min", 0), vals, 0.0)
            hi = limit(w.get("bar_max", 100), vals, 100.0)
            pct = None if v is None else max(0.0, min(100.0, 100 * (v - lo) / max(hi - lo, 1e-9)))
            rule = w.get("bar_rule", "load")
            state = temp_state(v) if rule == "temp" else load_state(pct) if rule == "load" else None
            bar = (pct if pct is not None else 0, state, color(w["bar_color"], th) if "bar_color" in w else None)
        tile(im, w["x"], w["y"], w["w"], w["h"], label, r, big, w.get("unit_size", 22), th,
             unit_gap=w.get("unit_gap", 4), baseline=True, bar=bar)

    def w_graph(self, im, w, vals, th, layout):
        """"value": history of a value over `seconds`; "series": a list value (e.g. 24 hourly
        temperatures) spread across the width. min/max default to the data (series) or 0/peak."""
        x, y, gw, gh = w["x"], w["y"], w["w"], w["h"]
        if "series" in w:
            data = series(vals, w["series"])
            if len(data) < 2:
                return
            xs = [gw * i / (len(data) - 1) for i in range(len(data))]
            pad = (max(data) - min(data)) * 0.15 or 1
            lo = limit(w.get("min"), vals, min(data) - pad)
            hi = limit(w.get("max"), vals, max(data) + pad)
        else:
            seconds = w.get("seconds", 120)
            hist = layout.history.setdefault((w["value"], seconds), [])
            now = time.time()
            v = number(vals, w["value"])
            if v is not None:
                hist.append((now, v))
            cutoff = now - seconds
            while hist and hist[0][0] < cutoff:
                hist.pop(0)
            if len(hist) < 2:
                return
            data = [val for _, val in hist]
            xs = [gw * (t - cutoff) / seconds for t, _ in hist]
            lo = limit(w.get("min", 0), vals, 0.0)
            hi = limit(w.get("max"), vals, max(data) or 1)
        span = max(hi - lo, 1e-9)
        pts = [((x + px) * D.S, (y + gh - gh * min(max((val - lo) / span, 0), 1)) * D.S) for px, val in zip(xs, data)]
        c = color(w.get("color"), th, th.accent)
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        if w.get("fill", True):
            d.polygon(pts + [(pts[-1][0], (y + gh) * D.S), (pts[0][0], (y + gh) * D.S)], fill=c[:3] + (50,))
        d.line(pts, fill=c, width=2 * D.S, joint="curve")
        if "marker" in w and "series" in w:                  # dot on one point, e.g. the current hour
            i = w["marker"] if isinstance(w["marker"], (int, float)) else number(vals, w["marker"])
            if i is not None and 0 <= int(i) < len(pts):
                px, py = pts[int(i)]
                r = 5 * D.S
                d.ellipse((px - r, py - r, px + r, py + r), fill=th.card_bg[:3] + (255,), outline=c, width=2 * D.S)
        if w.get("clip"):
            # clip to the box, with the card's rounded bottom corners (graph flush with a card's bottom)
            mask = D.rounded_mask(im.size, (x, y - D.RADIUS, gw, gh + D.RADIUS), D.RADIUS)
            box = Image.new("L", im.size, 0)
            ImageDraw.Draw(box).rectangle((int(x * D.S), int(y * D.S), int((x + gw) * D.S), int((y + gh) * D.S)), fill=255)
            from PIL import ImageChops
            ov.putalpha(ImageChops.multiply(ov.getchannel("A"), ImageChops.multiply(mask, box)))
        im.alpha_composite(ov)

    def w_image(self, im, w, vals, th, layout):
        """A picture file, or with a template a changing one: a path or http(s)/file:// link,
        e.g. a player's album cover {player|line(9)}. Links load in the background."""
        path = render_text(w["path"], vals).strip() if "{" in w["path"] else w["path"]
        if not path or path == MISSING or path.startswith("?"):
            return
        fit, radius = w.get("fit", "stretch"), w.get("radius", 0)
        if path.startswith(("http://", "https://", "file://")) or fit != "stretch" or radius:
            self.pictures.log = layout.log
            img = self.pictures.get(path, w.get("w"), w.get("h"), fit, radius)
        else:
            img = self._image(path, w.get("w"), w.get("h"))
        if img is not None:
            ox = (w.get("w", img.width / D.S) * D.S - img.width) / 2 if fit == "contain" else 0
            oy = (w.get("h", img.height / D.S) * D.S - img.height) / 2 if fit == "contain" else 0
            im.alpha_composite(img, (int(w["x"] * D.S + ox), int(w["y"] * D.S + oy)))


class Pictures:
    """Pictures named by a value that changes (album covers): files or web links, loaded in a
    background thread, kept for the last few names, scaled to each widget's box."""
    KEEP, MAX_BYTES, TIMEOUT, RETRY = 8, 8 * 1024 * 1024, 10, 30

    def __init__(self):
        self._orig: dict = {}           # name -> PIL image, or None while loading / after a failure
        self._failed: dict = {}         # name -> time of the failure, retried after RETRY seconds
        self._scaled: dict = {}
        self._errors: dict = {}         # name -> last error logged, so a retry that fails the same way stays quiet
        self._lock = threading.Lock()
        self.log = print

    def get(self, name, w=None, h=None, fit="stretch", radius=0):
        with self._lock:
            if name in self._failed and time.time() - self._failed[name] >= self.RETRY:
                del self._failed[name]
                self._orig.pop(name, None)
            if name not in self._orig:
                self._orig[name] = None
                threading.Thread(target=self._load, args=(name,), daemon=True, name="picture").start()
                while len(self._orig) > self.KEEP:
                    old = next(iter(self._orig))
                    self._orig.pop(old)
                    self._scaled = {k: v for k, v in self._scaled.items() if k[0] != old}
            src = self._orig[name]
        if src is None:
            return None
        key = (name, w, h, fit, radius)
        if key not in self._scaled:
            self._scaled[key] = _fit(src, w, h, fit, radius)
        return self._scaled[key]

    def state(self, name) -> str:
        """For hmictl sources: loaded / loading / failed: <reason> / not requested."""
        with self._lock:
            if name in self._failed:
                wait = max(0, round(self.RETRY - (time.time() - self._failed[name])))
                return f"failed: {self._errors.get(name, '?')} (retry in {wait} s)"
            if name not in self._orig:
                return "not requested yet"
            return "loading" if self._orig[name] is None else "loaded {}x{}".format(*self._orig[name].size)

    def _load(self, name):
        try:
            if name.startswith(("http://", "https://")):
                from .. import net
                data = net.get(_cover_url(name), timeout=self.TIMEOUT, limit=self.MAX_BYTES + 1)
            else:
                from urllib.parse import unquote
                path = unquote(name[7:]) if name.startswith("file://") else name
                st = os.stat(path)
                # the name can come from a player (any program in the session), and hmid runs as
                # root: only open files that a normal user could read anyway
                if st.st_uid == 0 and not st.st_mode & 0o004:
                    raise PermissionError("only files owned by a user or readable by everyone are shown")
                if os.path.getsize(path) > self.MAX_BYTES:
                    raise ValueError(f"larger than {self.MAX_BYTES // 2**20} MB")
                with open(path, "rb") as f:
                    data = f.read()
            if len(data) > self.MAX_BYTES:
                raise ValueError(f"larger than {self.MAX_BYTES // 2**20} MB")
            try:
                img = Image.open(io.BytesIO(data))
            except Exception:
                raise ValueError(f"not a picture ({len(data)} bytes, starts with {data[:24]!r})") from None
            img.draft("RGB", (1024, 1024))              # JPEG: decode at reduced size
            img = img.convert("RGBA")
            img.thumbnail((1024, 1024))
            with self._lock:
                if name in self._orig:
                    self._orig[name] = img
            if self._errors.pop(name, None):
                self.log(f"picture {_short(name)} loaded")
        except Exception as e:                           # no picture for now: the widget stays empty
            msg = str(e) or type(e).__name__
            with self._lock:
                self._failed[name] = time.time()
                new = self._errors.get(name) != msg
                self._errors[name] = msg
                while len(self._errors) > 4 * self.KEEP:
                    self._errors.pop(next(iter(self._errors)))
            if new:
                self.log(f"picture {_short(name)} failed: {msg} (retrying every {self.RETRY} s)")


def _cover_url(url):
    """Older Spotify clients report covers at open.spotify.com/image/<id>, which no longer
    serves them; the same picture is at i.scdn.co/image/<id>."""
    for old in ("https://open.spotify.com/image/", "http://open.spotify.com/image/"):
        if url.startswith(old):
            return "https://i.scdn.co/image/" + url[len(old):]
    return url


def _short(name):
    return name if len(name) <= 90 else name[:60] + "…" + name[-25:]


def _fit(src, w, h, fit, radius):
    """Scale to w x h panel pixels: stretch, cover (fill and crop) or contain (fit inside);
    radius rounds the corners."""
    if not (w and h):
        w, h = src.width, src.height
    W2, H2 = int(w * D.S), int(h * D.S)
    if fit == "cover":
        sc = max(W2 / src.width, H2 / src.height)
        img = src.resize((max(W2, round(src.width * sc)), max(H2, round(src.height * sc))), Image.LANCZOS)
        left, top = (img.width - W2) // 2, (img.height - H2) // 2
        img = img.crop((left, top, left + W2, top + H2))
    elif fit == "contain":
        sc = min(W2 / src.width, H2 / src.height)
        img = src.resize((max(1, round(src.width * sc)), max(1, round(src.height * sc))), Image.LANCZOS)
    else:
        img = src.resize((W2, H2), Image.LANCZOS)
    if radius:
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius * D.S, fill=255)
        from PIL import ImageChops
        img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    return img


def _wrap(text, size, width):
    words, line, out = text.split(), "", []
    for word in words:
        cand = f"{line} {word}".strip()
        if D.text_width(cand, size, False) > width and line:
            out.append(line)
            line = word
        else:
            line = cand
    return out + ([line] if line else [])
