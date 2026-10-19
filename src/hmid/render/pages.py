"""Pages drawn for the dynamic screen (480x800 PNG overlays)."""
from __future__ import annotations

import time

from PIL import ImageDraw

from .. import hwmon
from ..hwmon import fmt_rate, load_state, temp_state
from ..panel.protocol import HEIGHT as H
from ..panel.protocol import WIDTH as W
from ..sensors import Sample
from . import draw as D
from . import theme as T


class Renderer:
    def __init__(self, theme_id=2):
        self.theme = T.get(theme_id)
        self._bg = None

    def _canvas(self):
        if self._bg is None:
            self._bg = D.background(self.theme)
        return self._bg.copy()

    # ---- stats page: clock, CPU, GPU, memory, network / game ------------------------
    def stats(self, s: Sample) -> bytes:
        th = self.theme
        im = self._canvas()
        d = ImageDraw.Draw(im)
        D.text(d, (W / 2, 14), time.strftime("%H:%M", s.time), 86, th.primary, "ma", spacing=-1)
        D.text(d, (W / 2, 116), time.strftime("%a %d %b", s.time), 22, th.secondary, "ma", bold=False)
        D.divider(im, 158, th)

        card_h, net_h, gap, y = 148, 128, 12, 174
        px, right = 34, W - 34

        def metric(y, title, meta, big, big_state, side, side_color, pct):
            D.card(im, 16, y, W - 32, card_h, th)
            d = ImageDraw.Draw(im)
            D.text(d, (px, y + 16), title, 20, th.header)
            if meta:
                D.text(d, (right, y + 19), meta, 17, th.secondary, "ra", bold=False)
            D.text(d, (px, y + 44), big, 50, th.state_color(big_state))
            if side:
                D.text(d, (right, y + 52), side, 40, side_color, "ra")
            D.bar(im, px, y + card_h - 28, W - 2 * px, pct, load_state(pct), th)

        cl, ct = s.cpu_load, s.cpu_temp
        meta = " · ".join(x for x in (f"{s.cpu_mhz / 1000:.1f} GHz" if s.cpu_mhz else "",
                                      f"{s.cpu_power:.0f} W" if s.cpu_power is not None else "") if x)
        metric(y, "CPU", meta, f"{cl:.0f}%" if cl is not None else "–", load_state(cl),
               f"{ct:.0f}°C" if ct is not None else "", th.state_color(temp_state(ct), th.temp_normal), cl)
        y += card_h + gap

        g = s.gpu
        meta = []
        if g and g.mem_total:
            meta.append(f"{g.mem_used:.1f}/{g.mem_total:.0f} GB")
        if g and g.power is not None:
            meta.append(f"{g.power:.0f} W")
        gl, gt = (g.load, g.temp) if g else (None, None)
        metric(y, "GPU", " · ".join(meta), f"{gl:.0f}%" if gl is not None else "n/a", load_state(gl),
               f"{gt:.0f}°C" if gt is not None else "", th.state_color(temp_state(gt), th.temp_normal), gl)
        y += card_h + gap

        mp = 100 * s.mem_used / s.mem_total if s.mem_total else None
        metric(y, "MEMORY", f"of {s.mem_total:.0f} GB", f"{s.mem_used:.1f} GB", load_state(mp),
               f"{mp:.0f}%" if mp is not None else "", th.secondary, mp)
        y += card_h + gap

        D.card(im, 16, y, W - 32, net_h, th)
        d = ImageDraw.Draw(im)
        if s.game:                              # a game runs with MangoHud: FPS instead of network
            gm = s.game
            D.text(d, (px, y + 16), "GAME", 20, th.header)
            app = gm.app if len(gm.app) <= 22 else gm.app[:21] + "…"
            D.text(d, (right, y + 19), app, 17, th.secondary, "ra", bold=False)
            fps = f"{gm.fps:.0f}"
            D.text(d, (px, y + 50), fps, 50, th.warn if gm.fps < 30 else th.normal_text)
            D.text(d, (px + D.text_width(fps, 50) + 8, y + 74), "FPS", 20, th.secondary, bold=False)
            if gm.frametime is not None:
                D.text(d, (right, y + 64), f"{gm.frametime:.1f} ms", 30, th.primary, "ra")
        else:
            D.text(d, (px, y + 16), "NETWORK", 20, th.header)
            col2 = W / 2 + 6
            D.text(d, (px, y + 54), "DOWN", 16, th.secondary, bold=False)
            D.text(d, (col2, y + 54), "UP", 16, th.secondary, bold=False)
            D.text(d, (px, y + 78), fmt_rate(s.net_down), 30, th.primary)
            D.text(d, (col2, y + 78), fmt_rate(s.net_up), 30, th.primary)
        return D.to_png(im)

    # ---- multi-sensor hardware monitor (MSI "Multi" mode) ------------------------------
    def multi(self, s: Sample, names, page=0, pages=1) -> bytes:
        th = self.theme
        im = self._canvas()
        d = ImageDraw.Draw(im)
        D.text(d, (24, 22), "HARDWARE MONITOR", 20, th.header, spacing=1)
        D.text(d, (W - 24, 18), time.strftime("%H:%M", s.time), 26, th.primary, "ra")
        if pages > 1:
            D.text(d, (W / 2, H - 22), f"{page + 1} / {pages}", 14, th.secondary, "mm", bold=False)
        D.divider(im, 62, th)

        rd = hwmon.readings(s)
        n = len(names)
        cols = 1 if n <= 5 else 2
        rows = max(1, -(-n // cols))
        top, bottom, gap = 76, H - (40 if pages > 1 else 16), 10
        tile_h = (bottom - top - gap * (rows - 1)) / rows
        tile_w = (W - 32 - gap * (cols - 1)) / cols
        big = 34 if cols == 2 else 48
        if tile_h < 100:
            big = min(big, 30)
        for i, name in enumerate(names):
            x = 16 + (i % cols) * (tile_w + gap)
            y = top + (i // cols) * (tile_h + gap)
            tile(im, x, y, tile_w, tile_h, hwmon.SENSORS[name].label, rd[name], big, 16 if cols == 2 else 20, th)
        return D.to_png(im)


def tile(im, x, y, w, h, label, r, big, unit_size, th, unit_gap=6, baseline=False, bar=None):
    """A sensor tile: label, value (+unit), optional bar. Used by multi mode and layouts.
    bar: None = the reading's own bar; (pct, state, color) = a custom bar; False = none.
    baseline=True puts the unit on the number's baseline, unit_gap px after it."""
    D.card(im, x, y, w, h, th)
    d = ImageDraw.Draw(im)
    tx = x + 16
    D.text(d, (tx, y + 12), label, 15, th.header)
    pct, state, color = (r.pct, r.state, None) if bar is None else (bar or (None, None, None))
    vy = y + 34 + (h - 34 - (22 if pct is not None else 10) - big) / 2
    fill = th.state_color(r.state)
    if baseline:
        D.text_unit(d, tx, vy, r.text, big, fill, r.unit, unit_size, th.secondary, unit_gap)
    else:
        D.text(d, (tx, vy), r.text, big, fill)
        if r.unit:
            D.text(d, (tx + D.text_width(r.text, big) + unit_gap, vy + big * 0.42), r.unit, unit_size,
                   th.secondary, bold=False)
    if pct is not None:
        D.bar(im, tx, y + h - 20, w - 32, pct, state, th, color)
