"""Drawing primitives. Everything is drawn at S x size and scaled down for smooth edges."""
from __future__ import annotations

import io
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

from ..panel.protocol import HEIGHT as H
from ..panel.protocol import WIDTH as W
from . import theme as T

S = 2

_FONT_PATHS = {
    True: ["/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", "/usr/share/fonts/noto/NotoSans-Bold.ttf",
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    False: ["/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}
_fonts: dict = {}


def font(size: int, bold: bool = True):
    """Font at 1x size (scaled by S internally)."""
    key = (int(size * S), bold)
    if key not in _fonts:
        path = next((p for p in _FONT_PATHS[bold] if os.path.exists(p)), None)
        if not path:
            try:
                path = subprocess.run(["fc-match", "-f", "%{file}", "sans:bold" if bold else "sans"],
                                      capture_output=True, text=True, timeout=2).stdout.strip() or None
            except (OSError, subprocess.SubprocessError):
                path = None
        _fonts[key] = ImageFont.truetype(path, key[0]) if path else ImageFont.load_default()
    return _fonts[key]


def text_width(txt: str, size: int, bold: bool = True) -> float:
    return font(size, bold).getlength(txt) / S


def text(d, xy, txt, size, fill, anchor="la", bold=True, spacing=0):
    """Text at 1x coordinates with optional letter spacing (px)."""
    x, y = xy[0] * S, xy[1] * S
    f = font(size, bold)
    if not spacing:
        d.text((x, y), txt, font=f, fill=fill, anchor=anchor)
        return
    widths = [f.getlength(c) for c in txt]
    total = sum(widths) + spacing * S * (len(txt) - 1)
    if anchor[0] == "m":
        x -= total / 2
    elif anchor[0] == "r":
        x -= total
    for c, w in zip(txt, widths):
        d.text((x, y), c, font=f, fill=fill, anchor="l" + anchor[1])
        x += w + spacing * S


def text_unit(d, x, y, value, size, fill, unit, unit_size, unit_fill, gap=4, bold=True):
    """A number with its unit after it, both on the same baseline (y = top of the number)."""
    f = font(size, bold)
    base = y * S + f.getmetrics()[0]                 # ascent: top -> baseline
    d.text((x * S, base), value, font=f, fill=fill, anchor="ls")
    if unit:
        ux = x * S + f.getlength(value) + gap * S
        d.text((ux, base), unit, font=font(unit_size, False), fill=unit_fill, anchor="ls")


def bar(im, x, y, w, pct, state, th: T.Theme, color=None):
    """8 px pill bar. color: solid fill instead of the theme gradient (warn/crit still win)."""
    d = ImageDraw.Draw(im)
    h, r = 8 * S, 4 * S
    X, Y, Wd = int(x * S), int(y * S), int(w * S)
    d.rounded_rectangle((X, Y, X + Wd, Y + h), r, fill=th.track)
    if not pct or pct <= 0:
        return
    fw = max(h, int(Wd * min(pct, 100) / 100))
    if state in ("warn", "crit") or color:
        d.rounded_rectangle((X, Y, X + fw, Y + h), r, fill=th.state_color(state) if state in ("warn", "crit") else color)
        return
    c0, c1 = th.bar
    grad = Image.new("RGBA", (fw, h))
    gd = ImageDraw.Draw(grad)
    for i in range(fw):
        t = i / max(1, fw - 1)
        gd.line((i, 0, i, h), fill=tuple(int(c0[k] + (c1[k] - c0[k]) * t) for k in range(3)) + (255,))
    mask = Image.new("L", (fw, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, fw - 1, h - 1), r, fill=255)
    im.paste(grad, (X, Y), mask)


def ring(im, cx, cy, size, width, pct, state, th: T.Theme, color=None):
    """Circular progress: a track circle and a clockwise arc from the top with round ends.
    Colours as bar(): theme gradient along the arc, or `color`, or warn/crit."""
    import math
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    r, w = (size / 2 - width / 2) * S, width * S
    X, Y = cx * S, cy * S
    box = (X - r - w / 2, Y - r - w / 2, X + r + w / 2, Y + r + w / 2)
    d.ellipse(box, outline=th.track, width=int(w))
    if pct and pct > 0:
        pct = min(pct, 100.0)
        solid = th.state_color(state) if state in ("warn", "crit") else color
        c0, c1 = th.bar
        steps = max(2, int(pct * 1.8))             # short segments, so a gradient follows the arc
        for i in range(steps):
            t0, t1 = pct * i / steps, pct * (i + 1) / steps
            mix = (i + 0.5) / steps
            fill = solid or tuple(int(c0[k] + (c1[k] - c0[k]) * mix) for k in range(3)) + (255,)
            d.arc(box, -90 + 3.6 * t0, -90 + 3.6 * t1 + 0.6, fill=fill, width=int(w))
        for t, fill in ((0, solid or c0), (pct, solid or c1)):        # round ends
            a = math.radians(-90 + 3.6 * t)
            ex, ey = X + r * math.cos(a), Y + r * math.sin(a)
            d.ellipse((ex - w / 2, ey - w / 2, ex + w / 2, ey + w / 2), fill=fill[:3] + (255,))
    im.alpha_composite(ov)


DEFAULT = T.get("tiffany")
RADIUS = 14


def card(im, x, y, w, h, th: T.Theme = DEFAULT, fill=True, border=True):
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).rounded_rectangle((int(x * S), int(y * S), int((x + w) * S), int((y + h) * S)),
                                         RADIUS * S, fill=th.card_bg if fill else None,
                                         outline=th.card_border if border else None, width=S)
    im.alpha_composite(ov)


def rounded_mask(size, box, radius):
    """L mask (full canvas size) of a rounded box, coordinates at 1x."""
    m = Image.new("L", size, 0)
    x, y, w, h = box
    ImageDraw.Draw(m).rounded_rectangle((int(x * S), int(y * S), int((x + w) * S), int((y + h) * S)),
                                        radius * S, fill=255)
    return m


def background(th: T.Theme = DEFAULT):
    im = Image.new("RGBA", (W * S, H * S), th.canvas)
    if th.glow is None:
        return im
    glow = Image.new("L", im.size, 0)
    gd = ImageDraw.Draw(glow)
    cx, cy, rmax = W * S // 2, int(H * S * 0.08), int(W * S * 0.80)
    for r in range(rmax, 0, -4 * S):          # radial glow near the top
        a = int(255 * 0.55 * (1 - r / rmax) ** 1.4)
        gd.ellipse((cx - r, cy - int(r * 0.8), cx + r, cy + int(r * 0.8)), fill=a)
    im.paste(Image.new("RGBA", im.size, th.glow[:3] + (255,)), (0, 0), glow)
    return im


def divider(im, y, th: T.Theme = DEFAULT):
    x0, x1 = 16 * S, (W - 16) * S
    line = Image.new("RGBA", (x1 - x0, 2 * S))
    ld = ImageDraw.Draw(line)
    for i in range(x1 - x0):                    # transparent -> tiffany -> transparent
        t = 1 - abs(i / (x1 - x0 - 1) * 2 - 1)
        ld.line((i, 0, i, 2 * S), fill=th.accent[:3] + (int(255 * t),))
    im.alpha_composite(line, (x0, y * S))


def to_png(im) -> bytes:
    out = im.resize((W, H), Image.LANCZOS).convert("RGB").convert("RGBA")
    b = io.BytesIO()
    out.save(b, "PNG", compress_level=6)
    return b.getvalue()
