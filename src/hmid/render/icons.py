"""Weather icons drawn with shapes (no image files), in theme colours.

Names: clear, moon, partly, partly_night, cloudy, fog, drizzle, rain, snow, storm.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw

from . import draw as D

NAMES = ("clear", "moon", "partly", "partly_night", "cloudy", "fog", "drizzle", "rain", "snow", "storm")


def _sun(d, cx, cy, r, color, rays=True):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    if rays:
        for i in range(8):
            a = i * math.pi / 4
            x0, y0 = cx + math.cos(a) * r * 1.35, cy + math.sin(a) * r * 1.35
            x1, y1 = cx + math.cos(a) * r * 1.8, cy + math.sin(a) * r * 1.8
            d.line((x0, y0, x1, y1), fill=color, width=max(2, int(r * 0.22)))


def _moon(im, cx, cy, r, color, bg):
    d = ImageDraw.Draw(im)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).ellipse((cx - r * 0.45, cy - r * 1.2, cx + r * 1.55, cy + r * 0.8), fill=255)
    im.paste(Image.new("RGBA", im.size, (0, 0, 0, 0)), (0, 0), mask)


def _cloud(d, x, y, w, color):
    """Cloud with its bounding box starting at (x, y), width w."""
    h = w * 0.55
    d.ellipse((x + w * 0.05, y + h * 0.35, x + w * 0.45, y + h), fill=color)
    d.ellipse((x + w * 0.22, y, x + w * 0.72, y + h * 0.85), fill=color)
    d.ellipse((x + w * 0.52, y + h * 0.28, x + w * 0.95, y + h), fill=color)
    d.rounded_rectangle((x + w * 0.25, y + h * 0.55, x + w * 0.75, y + h), radius=h * 0.2, fill=color)


def draw_icon(im, name: str, x: float, y: float, size: float, th):
    """Draw icon `name` in a size x size box at (x, y) (1x coordinates)."""
    S = D.S
    s = int(size * S)
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    sun, cloud, water, dim = th.warn, th.primary, th.accent, th.secondary
    if name == "clear":
        _sun(d, s / 2, s / 2, s * 0.22, sun)
    elif name == "moon":
        _moon(layer, s / 2, s / 2, s * 0.3, sun, None)
    elif name in ("partly", "partly_night"):
        if name == "partly":
            _sun(d, s * 0.36, s * 0.34, s * 0.16, sun)
        else:
            _moon(layer, s * 0.36, s * 0.34, s * 0.2, sun, None)
            d = ImageDraw.Draw(layer)
        _cloud(d, s * 0.18, s * 0.38, s * 0.78, cloud)
    else:
        top = s * 0.12 if name in ("cloudy", "fog") else s * 0.06
        _cloud(d, s * 0.08, top, s * 0.84, dim if name in ("rain", "storm", "drizzle", "snow") else cloud)
        base = top + s * 0.84 * 0.55
        if name == "fog":
            for i in range(3):
                yy = base + s * 0.06 + i * s * 0.09
                d.line((s * 0.14 + (i % 2) * s * 0.08, yy, s * 0.86 - ((i + 1) % 2) * s * 0.08, yy),
                       fill=dim, width=max(2, int(s * 0.04)))
        elif name in ("rain", "drizzle"):
            n = 3 if name == "rain" else 2
            for i in range(n):
                xx = s * (0.3 + i * 0.4 / max(n - 1, 1))
                d.line((xx, base + s * 0.08, xx - s * 0.06, base + s * (0.3 if name == "rain" else 0.18)),
                       fill=water, width=max(2, int(s * 0.05)))
        elif name == "snow":
            for i in range(3):
                xx, yy = s * (0.3 + i * 0.2), base + s * (0.14 if i % 2 else 0.24)
                r = s * 0.035
                d.ellipse((xx - r, yy - r, xx + r, yy + r), fill=cloud)
        elif name == "storm":
            cx, cy = s * 0.5, base + s * 0.04
            d.polygon([(cx + s * 0.04, cy), (cx - s * 0.1, cy + s * 0.2), (cx, cy + s * 0.2),
                       (cx - s * 0.06, cy + s * 0.36), (cx + s * 0.12, cy + s * 0.13), (cx + s * 0.02, cy + s * 0.13)],
                      fill=sun)
    im.alpha_composite(layer, (int(x * S), int(y * S)))
