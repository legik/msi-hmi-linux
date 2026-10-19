#!/usr/bin/env python3
"""Render layouts with made-up readings, for the pictures in the docs.

    python3 tools/layout_gallery.py docs/images/examples examples/layouts/*.json
    python3 tools/layout_gallery.py /tmp/out --theme nord --sheet /tmp/sheet.png examples/layouts/*.json

Writes <out>/<name>.png (240 x 400, half size) for every layout, and with --sheet one
picture with all of them side by side. Nothing is read from this PC: the readings and
the values of the layouts' own sources are the demo values below, and graphs get a
made-up history, so the pictures are the same on every machine.
"""
from __future__ import annotations

import argparse
import io
import math
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PIL import Image  # noqa: E402

from hmid.layouts import Layout  # noqa: E402
from hmid.layouts.draw import LayoutRenderer  # noqa: E402
from hmid.layouts.values import number, values  # noqa: E402
from hmid.sensors import GameSample, Sample  # noqa: E402
from hmid.sensors.gpu import GpuSample  # noqa: E402

NOW = time.struct_time((2026, 10, 18, 17, 52, 0, 6, 291, 0))      # Sunday 18 October, 17:52


def demo_sample(game=True):
    return Sample(
        time=NOW, cpu_load=37.0, cpu_temp=71.0, cpu_mhz=4250, cpu_power=55, mem_used=13.4, mem_total=32,
        mem_mhz=4400, gpu=GpuSample(load=96, temp=67, mem_used=10.5, mem_total=16, power=281, clock=2610,
                                    fan_pct=55, power_limit=320),
        net_down=2.4e6, net_up=120e3,
        fans={"cpu_fan": (653, 41), "pump": (2977, 100), "sys_fan": (1016, 31)},
        vrm_temp=57.0, game=GameSample(143.7, 6.96, "eldenring") if game else None)


def _iso(seconds_from_now):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + seconds_from_now))


def _weather_demo():
    """MET Norway answers saved in tests/data, moved by whole days to today (so today's high/low
    and sunset work whenever the pictures are made)."""
    import json
    import re
    from datetime import datetime, timedelta, timezone
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "data")
    try:
        with open(os.path.join(here, "met_norway.json")) as f:
            met = f.read()
        with open(os.path.join(here, "met_sun.json")) as f:
            sun = f.read()
    except OSError:
        return {}
    first = datetime.fromisoformat(json.loads(met)["properties"]["timeseries"][0]["time"].replace("Z", "+00:00"))
    shift = timedelta(days=(datetime.now(timezone.utc).date() - first.date()).days)     # whole days

    def move(text):
        def one(m):
            d = datetime.fromisoformat(m.group(0).replace("Z", "+00:00")) + shift
            return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return re.sub(r"\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?(?:Z|[+-]\d\d:\d\d)", one, text)
    return {"met": json.loads(move(met)), "sun": json.loads(move(sun))}


# what each example's sources would return (by source name)
DEMO_SOURCES = {
    "yt": {"items": [{"snippet": {"title": "Pixel & Solder"},
                      "statistics": {"subscriberCount": "128456", "viewCount": "9384120", "videoCount": "214"}}]},
    "upload": {"items": [{"snippet": {"title": "I rebuilt a 2003 PC with modern parts",
                                      "publishedAt": _iso(-26 * 3600)}}]},
    "tw": {"total": 23817, "data": []},
    "live": {"data": [{"viewer_count": 1342, "game_name": "Elden Ring",
                       "title": "Blind run, day 4 - no summons", "started_at": _iso(-7400)}]},
    "sched": {"data": {"segments": [{"title": "Elden Ring, day 5", "start_time": _iso(2 * 86400 + 3600)}]}},
    "bsky": {"followersCount": 8412, "postsCount": 1290},
    "post": {"feed": [{"post": {"record": {"text": "New video is up! Full teardown of the Trident X2 front panel."},
                                "likeCount": 342, "repostCount": 57, "replyCount": 31,
                                "indexedAt": _iso(-3 * 3600)}}]},
    "masto": {"followers_count": 2150},
    "gh": {"followers": 960},
    **_weather_demo(),
    "ping": "14.2", "ip": "192.168.1.20", "public_ip": "203.0.113.42",
    "host": "trident", "kernel": "6.18.4-1-MANJARO", "uptime": "3 days, 4 hours", "updates": "12",
    "root_pct": "41", "root_free": "547G", "home_pct": "68", "home_free": "602G", "load": {"m1": 1.24, "m5": 0.98, "m15": 0.87},
    "pkgs": "1432",
    "player": "Playing\n312000000\n481000000\n5:12\n8:01\nWeightless\nMarconi Union\n"
              "Weightless (Ambient Transmissions Vol. 2)\nspotify\nfile://" + os.path.join(
                  tempfile.gettempdir(), "hmid-demo-cover.png"),
    "zones": "10:52\nSun, UTC-04:00\n15:52\nSun, UTC+01:00\n23:52\nSun, UTC+09:00\n01:52\nMon, UTC+11:00",
    "fx": {"rates": {"EUR": 0.912, "GBP": 0.771, "RUB": 81.35}},
    "coins": {"bitcoin": {"usd": 106840.0, "usd_24h_change": 2.31},
              "ethereum": {"usd": 3912.5, "usd_24h_change": -1.42},
              "solana": {"usd": 187.3, "usd_24h_change": 4.87}},
    "repo": {"full_name": "legik/msi-hmi-linux", "stargazers_count": 1284, "forks_count": 87,
             "open_issues_count": 23, "subscribers_count": 41, "pushed_at": _iso(-5 * 3600),
             "description": "Linux service for the MSI MEG Trident X2 front touch panel"},
    "release": {"tag_name": "v0.2.0", "published_at": _iso(-6 * 86400)},
    "ci": {"workflow_runs": [{"name": "CI", "status": "completed", "conclusion": "success", "run_number": 318,
                              "head_branch": "main", "actor": {"login": "contributor"},
                              "head_commit": {"message": "layouts: line(), compact and ago filters\n\nmore text"},
                              "updated_at": _iso(-40 * 60)}]},
}


def fake_history(layout: Layout, vals: dict):
    """Fill every value graph with a plausible history ending at the current reading."""
    for w in layout.data.get("widgets", []):
        if w.get("type") != "graph" or "value" not in w:
            continue
        v = number(vals, w["value"])
        if v is None:
            continue
        seconds = w.get("seconds", 120)
        now, n = time.time(), 90
        seed = sum(map(ord, w["value"]))
        pts = []
        growing = isinstance(w.get("min"), str)  # min relative to the value: counters and prices
        for i in range(n):
            t = now - seconds + seconds * i / (n - 1)
            if growing:
                pts.append((t, v * (0.985 + 0.015 * i / n + 0.004 * math.sin(i / 5 + seed)
                                    + 0.002 * math.sin(i * 1.3 + seed))))
                continue
            wobble = (0.18 * math.sin(i / 6 + seed) + 0.10 * math.sin(i / 2.3 + seed * 3)
                      + 0.06 * math.sin(i * 1.7 + seed))
            pts.append((t, max(0.0, v * (1 + wobble * (1 - i / n * 0.6)))))
        pts[-1] = (now, v)
        layout.history[(w["value"], seconds)] = pts[:-1]


def demo_cover(path):
    """An abstract made-up album cover (no real artwork in the docs)."""
    if os.path.exists(path):
        return
    from PIL import ImageDraw, ImageFilter
    n = 600
    im = Image.new("RGB", (n, n))
    px = im.load()
    for y in range(n):
        for x in range(n):
            t, u = x / n, y / n
            px[x, y] = (int(40 + 150 * t * (1 - u)), int(30 + 60 * u), int(90 + 140 * u * (1 - t * 0.5)))
    d = ImageDraw.Draw(im)
    for r, c in ((230, (255, 170, 90)), (170, (250, 110, 120)), (110, (255, 220, 150))):
        d.ellipse((n * 0.62 - r, n * 0.38 - r, n * 0.62 + r, n * 0.38 + r), outline=c, width=10)
    im = im.filter(ImageFilter.GaussianBlur(2))
    im.save(path)


def render(path: str, theme: str) -> Image.Image:
    layout = Layout(os.path.abspath(path), log=lambda *a: None)
    if layout.errors:
        raise SystemExit(f"{path}: " + "; ".join(layout.errors))
    layout.source_values = lambda: {n: DEMO_SOURCES.get(n) for n in layout.data.get("sources", {})}
    sample = demo_sample(game="fps" in json_text(path))
    fake_history(layout, values(sample, layout.source_values()))
    renderer = LayoutRenderer(theme)
    if any(w.get("type") == "image" and "{" in w.get("path", "") for w in layout.data["widgets"]):
        demo_cover(os.path.join(tempfile.gettempdir(), "hmid-demo-cover.png"))
        renderer.render(layout, sample)            # starts loading the picture
        time.sleep(0.5)
    png = renderer.render(layout, sample)
    return Image.open(io.BytesIO(png)).convert("RGB")


def json_text(path):
    with open(path) as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", help="folder for the pictures")
    ap.add_argument("layouts", nargs="+")
    ap.add_argument("--theme", default="monokai")
    ap.add_argument("--sheet", help="also write all of them side by side into this file")
    ap.add_argument("--scale", type=float, default=0.5)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    shots = []
    for p in a.layouts:
        im = render(p, a.theme)
        im = im.resize((int(480 * a.scale), int(800 * a.scale)), Image.LANCZOS)
        name = os.path.basename(p)[:-5]
        im.save(os.path.join(a.out, name + ".png"), optimize=True)
        shots.append(im)
        print("wrote", os.path.join(a.out, name + ".png"))
    if a.sheet:
        gap = 10
        w, h = shots[0].size
        sheet = Image.new("RGB", (len(shots) * (w + gap) - gap, h), (255, 255, 255))
        for i, im in enumerate(shots):
            sheet.paste(im, (i * (w + gap), 0))
        sheet.save(a.sheet, optimize=True)
        print("wrote", a.sheet)


if __name__ == "__main__":
    main()
