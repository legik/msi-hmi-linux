import io
import json
import os
import time

import pytest
from PIL import Image
from test_hwmon import sample

from hmid.layouts import Layout, available, path_for, trusted, validate
from hmid.layouts.draw import LayoutRenderer, color
from hmid.layouts.sources import Source, json_path
from hmid.layouts.values import render_text, truthy, values
from hmid.render import Renderer
from hmid.render import theme as T

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "src", "hmid", "data", "layouts")
GALLERY = os.path.join(os.path.dirname(__file__), "..", "examples", "layouts")


def write(tmp_path, data, name="t"):
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(data))
    return p


def wait_for(fn, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.02)
    return False


# ---- values and templates -------------------------------------------------------------
def test_templates():
    v = values(sample(), {"subs": "128456", "note": "hi"})
    assert render_text("{cpu_load:.0f}% {cpu_temp:.0f}°C", v) == "37% 71°C"
    assert render_text("{time:%Y}", v) == time.strftime("%Y", v["time"])
    assert render_text("{subs:,.0f} / {note}", v) == "128,456 / hi"
    assert render_text("{download}", v) == "2.4 MB/s"
    assert render_text("{nope} {fps:.0f}", values(sample(game=None))) == "?nope –"
    assert render_text("{{literal}}", v) == "{literal}"
    assert render_text("{note:.1f}", v) == "hi"                # text with a number format: shown as is


def test_when_conditions():
    v = values(sample(game=None))
    assert not truthy(v, "fps") and truthy(v, "!fps") and truthy(v, "cpu_load")


def test_when_comparisons():
    v = values(sample(), {"ci": {"status": "completed", "conclusion": "Success"}, "chg": "-1.4", "empty": None})
    assert truthy(v, "ci.conclusion=success") and not truthy(v, "ci.conclusion=failure")
    assert truthy(v, "!ci.status=in_progress")
    assert truthy(v, "chg<0") and not truthy(v, "chg>=0") and truthy(v, "cpu_temp>=71")
    assert not truthy(v, "empty=x") and not truthy(v, "empty<1") and truthy(v, "!empty>1")
    assert not truthy(v, "ci.status>3")                        # text compared as a number: false


def test_text_and_time_filters(monkeypatch):
    v = values(sample(), {"out": "Playing\n312\n\nWeightless", "n": "128456", "big": 2.34e6, "small": 950,
                          "t": "2026-10-18T12:00:00Z"})
    assert render_text("{out|line(0)} {out|line(3)}", v) == "Playing Weightless"
    assert render_text("{out|line(2)}|{out|line(9)}", v) == "–|–"
    assert render_text("{n|compact} {big|compact} {small|compact}", v) == "128K 2.3M 950"
    import hmid.layouts.values as V
    noon = V._iso("2026-10-18T12:00:00Z").timestamp()
    monkeypatch.setattr(V.time, "time", lambda: noon + 3 * 3600 + 120)
    assert render_text("{t|ago}", v) == "3 h ago"
    monkeypatch.setattr(V.time, "time", lambda: noon - 2 * 86400 - 5)
    assert render_text("{t|ago}", v) == "in 2 d"
    assert render_text("{t|date}", v).endswith("Oct")


def test_ring_widget(tmp_path):
    def draw(value, **kw):
        p = write(tmp_path, {"widgets": [{"type": "ring", "x": 240, "y": 400, "size": 200, "width": 20,
                                          "value": value, "rule": "none", **kw}]}, name=f"r{len(kw)}{value}")
        return Image.open(io.BytesIO(LayoutRenderer().render(Layout(str(p)), sample()))).convert("RGB")
    empty, half = draw("missing_value"), draw("cpu_load", max=74)            # 37 of 74: half way
    right, left = (330, 400), (150, 400)                                      # on the ring, 3 and 9 o'clock
    assert empty.getpixel(right) == empty.getpixel(left)                      # only the track
    assert half.getpixel(right) != empty.getpixel(right)                      # filled at 3 o'clock...
    assert half.getpixel((150, 430)) == empty.getpixel((150, 430))            # ...not past 6 o'clock
    red = draw("cpu_load", color="#ff0000")
    assert red.getpixel(right)[0] > 200 and red.getpixel(right)[1] < 60
    assert validate({"widgets": [{"type": "ring", "x": 1, "y": 1, "size": 9}]}) == ["widget 1 (ring): missing value"]


def test_image_from_value_file_and_web(tmp_path):
    import http.server
    import threading

    from hmid.layouts.draw import Pictures
    Image.new("RGB", (300, 100), (250, 20, 20)).save(tmp_path / "wide.png")
    pics = Pictures()
    name = (tmp_path / "wide.png").as_uri()                      # file:///.../wide.png
    assert pics.get(name, 100, 100, "cover", 10) is None         # loads in the background
    assert wait_for(lambda: pics.get(name, 100, 100, "cover", 10) is not None)
    img = pics.get(name, 100, 100, "cover", 10)
    assert img.size == (200, 200) and img.getpixel((0, 0))[3] == 0 and img.getpixel((100, 100))[:3] == (250, 20, 20)
    assert pics.get(name, 100, 100, "contain").size == (200, 67)

    handler = type("H", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), lambda *a: handler(*a, directory=str(tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/wide.png"
        pics.get(url, 50, 50, "cover")
        assert wait_for(lambda: pics.get(url, 50, 50, "cover") is not None)
        bad = f"http://127.0.0.1:{srv.server_port}/missing.png"
        logs = []
        pics.log = logs.append
        pics.get(bad)
        assert wait_for(lambda: bad in pics._failed) and pics.get(bad) is None
        assert len(logs) == 1 and "missing.png failed: HTTP Error 404" in logs[0]
        (tmp_path / "junk.png").write_text("<html>blocked</html>")
        junk = (tmp_path / "junk.png").as_uri()
        pics.get(junk)
        assert wait_for(lambda: len(logs) == 2) and "not a picture" in logs[1] and "<html>" in logs[1]
        pics._failed[bad] -= Pictures.RETRY                        # retried after a while
        pics.get(bad)
        assert bad not in pics._failed or pics._failed[bad] > 0
    finally:
        srv.shutdown()

    p = write(tmp_path, {"sources": {"cover": {"type": "file", "path": str(tmp_path / "name.txt")}},
                         "widgets": [{"type": "image", "x": 0, "y": 0, "w": 100, "h": 100, "path": "{cover}",
                                      "fit": "cover"}]}, name="cov")
    (tmp_path / "name.txt").write_text(name)
    r, lay = LayoutRenderer(), Layout(str(p))
    assert wait_for(lambda: lay.source_values().get("cover") == name)
    r.render(lay, sample())
    assert wait_for(lambda: Image.open(io.BytesIO(r.render(lay, sample()))).getpixel((50, 50))[0] > 200)
    assert validate({"widgets": [{"type": "image", "x": 0, "y": 0, "path": "a", "fit": "zoom"}]}) == \
        ["widget 1 (image): 'fit' must be stretch, cover or contain"]


def test_spotify_cover_link():
    from hmid.layouts.draw import _cover_url
    assert _cover_url("https://open.spotify.com/image/ab67616d0000b273") == "https://i.scdn.co/image/ab67616d0000b273"
    assert _cover_url("https://i.scdn.co/image/x") == "https://i.scdn.co/image/x"


def test_colors():
    th = T.get(2)
    assert color("#0ABAB5", th) == (10, 186, 181, 255)
    assert color("#0ABAB580", th)[3] == 128
    assert color("header", th) == th.header
    assert color("bogus", th) == T.TEXT_PRIMARY


# ---- validation --------------------------------------------------------------------------
def test_examples_are_valid():
    for folder in (EXAMPLES, GALLERY):
        for f in [f for f in os.listdir(folder) if f.endswith(".json")]:
            with open(os.path.join(folder, f)) as fh:
                assert validate(json.load(fh)) == [], f


def test_gallery_tool_draws_layouts_without_pictures():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gallery2", os.path.join(os.path.dirname(__file__), "..", "tools", "layout_gallery.py"))
    gallery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gallery)
    assert gallery.render(os.path.join(EXAMPLES, "classic.json"), "monokai").size == (480, 800)
    assert "met" in gallery.DEMO_SOURCES and "sun" in gallery.DEMO_SOURCES


def test_gallery_examples_render_with_demo_data():
    """Every example in examples/layouts draws without a failing widget, using the
    demo values from tools/layout_gallery.py."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gallery", os.path.join(os.path.dirname(__file__), "..", "tools", "layout_gallery.py"))
    gallery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gallery)
    builtin = ["creator.json", "now-playing.json"]
    for f in sorted(f for f in os.listdir(GALLERY) if f.endswith(".json")) + builtin:
        path = os.path.join(EXAMPLES if f in builtin else GALLERY, f)
        logs = []
        layout = Layout(os.path.abspath(path), log=logs.append)
        demo = {n: gallery.DEMO_SOURCES.get(n) for n in layout.data.get("sources", {})}
        layout.source_values = lambda demo=demo: demo
        for n in layout.data.get("sources", {}):
            assert n in gallery.DEMO_SOURCES, f"{f}: no demo value for source {n}"
        im = Image.open(io.BytesIO(LayoutRenderer().render(layout, gallery.demo_sample())))
        assert im.size == (480, 800)
        assert not [m for m in logs if "failed" in m], (f, logs)
        assert "?" not in "".join(render_text(w["text"], values(gallery.demo_sample(), layout.source_values()))
                                  for w in layout.data["widgets"] if w["type"] == "text"), f


def test_validation_messages():
    errs = validate({"widgets": [{"type": "text", "x": 1}, {"type": "blink"}, {"type": "sensor", "x": 0, "y": 0,
                                 "w": 1, "h": 1, "sensor": "x"}, {"type": "card", "x": "1", "y": 0, "w": 1, "h": 1,
                                                                  "colour": 1}],
                     "sources": {"a": {"type": "http"}, "b": {"type": "ftp"}}, "extra": 1})
    text = "\n".join(errs)
    for part in ("missing text, y", "'type' must be one of", "unknown sensor 'x'", "'x' must be a number",
                 "unknown keys colour", "source 'a': missing 'url'", "source 'b'", "extra"):
        assert part in text, part
    assert validate([]) == ["the file must contain a JSON object"]


def test_builtin_and_custom_layouts(tmp_path):
    from hmid.layouts import BUILTIN, catalog, customize
    mine = tmp_path / "layouts"
    # built-in used when there is no file of yours
    assert path_for("layout:gaming", str(mine)) == os.path.join(BUILTIN, "gaming.json")
    assert path_for("layout:nope", str(mine)) == str(mine / "nope.json")       # error names your folder
    assert path_for("/x/y.json") == "/x/y.json"
    # customize copies the built-in; yours then wins
    dst = customize("gaming", str(mine))
    assert path_for("gaming", str(mine)) == dst
    with pytest.raises(FileExistsError):
        customize("gaming", str(mine))
    with pytest.raises(FileNotFoundError):
        customize("nope", str(mine))
    (mine / "own.json").write_text('{"widgets": [{"type": "divider", "y": 1}]}')
    cat = catalog(str(mine))
    assert cat["gaming"] == "yours (replaces built-in)" and cat["own"] == "yours" and cat["weather"] == "built-in"


def test_builtin_layouts_are_packaged():
    tomllib = pytest.importorskip("tomllib")              # Python 3.11+
    with open(os.path.join(os.path.dirname(__file__), "..", "pyproject.toml"), "rb") as f:
        data = tomllib.load(f)["tool"]["setuptools"]["package-data"]["hmid"]
    assert "data/layouts/*.json" in data
    assert {"classic", "gaming", "weather", "weather-openmeteo", "creator", "now-playing"} <= set(available())


# ---- rendering ---------------------------------------------------------------------------------
def test_all_widgets_render(tmp_path):
    img = tmp_path / "logo.png"
    Image.new("RGBA", (40, 40), (255, 0, 0, 255)).save(img)
    p = write(tmp_path, {"background": {"color": "#102030"}, "widgets": [
        {"type": "card", "x": 10, "y": 10, "w": 200, "h": 100},
        {"type": "text", "x": 20, "y": 20, "text": "{cpu_temp:.0f}", "value": "cpu_temp", "rule": "temp", "max_width": 50},
        {"type": "bar", "x": 20, "y": 80, "w": 100, "value": "gpu_load"},
        {"type": "sensor", "x": 10, "y": 120, "w": 220, "h": 120, "sensor": "vrm_temp"},
        {"type": "graph", "x": 10, "y": 260, "w": 200, "h": 60, "value": "cpu_load"},
        {"type": "image", "x": 300, "y": 300, "path": str(img)},
        {"type": "divider", "y": 400},
        {"type": "text", "x": 0, "y": 500, "text": "hidden", "when": "fps"}]})
    lay = Layout(str(p), log=lambda *a: None)
    r = LayoutRenderer(2)
    for _ in range(3):
        im = Image.open(io.BytesIO(r.render(lay, sample(game=None)))).convert("RGB")
    assert im.size == (480, 800)
    assert im.getpixel((5, 790)) == (16, 32, 48)                 # background colour
    assert im.getpixel((320, 320))[0] > 200                     # the image
    assert len(lay.history[("cpu_load", 120)]) == 3


def test_errors_drawn_and_hot_reload(tmp_path):
    p = write(tmp_path, {"widgets": [{"type": "text"}]})
    logs = []
    lay = Layout(str(p), log=logs.append)
    assert lay.errors and any("missing" in m for m in logs)
    bad = LayoutRenderer(2).render(lay, sample())
    p.write_text(json.dumps({"widgets": [{"type": "text", "x": 0, "y": 0, "text": "ok"}]}))
    os.utime(p, (time.time() + 5, time.time() + 5))
    good = LayoutRenderer(2).render(lay, sample())
    assert not lay.errors and good != bad


def test_missing_file(tmp_path):
    lay = Layout(str(tmp_path / "none.json"), log=lambda *a: None)
    assert "not found" in lay.errors[0]
    assert Image.open(io.BytesIO(LayoutRenderer(2).render(lay, sample()))).size == (480, 800)


# ---- sources -------------------------------------------------------------------------------------
def test_json_path():
    data = {"items": [{"statistics": {"subscriberCount": "42"}}]}
    assert json_path(data, "items.0.statistics.subscriberCount") == "42"
    with pytest.raises(KeyError):
        json_path(data, "items.0.nope")


def test_file_source(tmp_path):
    f = tmp_path / "v.json"
    f.write_text('{"a": {"b": 7}}')
    s = Source("v", {"type": "file", "path": str(f), "json": "a.b"}, allow_commands=False, log=lambda *a: None)
    s.get()
    assert wait_for(lambda: s.value == 7)


def test_command_source_needs_trusted_file():
    logs = []
    s = Source("c", {"type": "command", "run": "echo 5"}, allow_commands=False, log=logs.append)
    s.get()
    assert wait_for(lambda: s.error is not None) and s.value is None and "root-owned" in s.error
    ok = Source("c", {"type": "command", "run": "echo 5"}, allow_commands=True, log=lambda *a: None)
    ok.get()
    assert wait_for(lambda: ok.value == "5")


def test_command_as_desktop_user(monkeypatch):
    import pwd

    import hmid.layouts.sources as S
    me = pwd.getpwuid(os.getuid())
    session = type("FakeSession", (), {"env": lambda self: (me, {"PATH": os.environ["PATH"], "HMID_T": "ok"})})()
    monkeypatch.setattr(S, "_user_session", lambda: session)
    s = Source("u", {"type": "command", "as": "user", "run": "echo $HMID_T $(id -u)"}, allow_commands=True,
               log=lambda *a: None)
    s.get()
    assert wait_for(lambda: s.value == f"ok {me.pw_uid}")
    nobody = type("NoSession", (), {"env": lambda self: None})()
    monkeypatch.setattr(S, "_user_session", lambda: nobody)
    s2 = Source("u", {"type": "command", "as": "user", "run": "echo hi"}, allow_commands=True, log=lambda *a: None)
    s2.get()
    assert wait_for(lambda: s2._t and not s2._busy) and s2.value == "" and s2.error is None    # no session: empty
    bad = {"widgets": [{"type": "divider", "y": 1}], "sources": {"x": {"type": "command", "run": "true", "as": "me"}}}
    assert validate(bad) == ["source 'x': 'as' must be root or user"]


def test_trusted(tmp_path):
    p = write(tmp_path, {"widgets": []})
    os.chmod(p, 0o666)
    assert not trusted(str(p))
    if os.geteuid() == 0:
        os.chmod(p, 0o644)
        os.chmod(tmp_path, 0o755)
        assert trusted(str(p))


def test_gaming_example_features():
    from hmid.sensors import GpuSample
    lay = Layout(os.path.join(EXAMPLES, "gaming.json"), log=lambda *a: None)
    gpu = GpuSample(load=96, temp=82, mem_used=10.5, mem_total=16, power=281, clock=2600, fan_pct=55, power_limit=320)
    r = LayoutRenderer(2)
    for _ in range(3):
        png = r.render(lay, sample(gpu=gpu))
    im = Image.open(io.BytesIO(png)).convert("RGB")
    assert im.getpixel((240, 790)) == T.get(2).canvas[:3]              # gruvbox canvas
    assert im.getpixel((20, 395)) != (29, 32, 33)              # card drawn
    assert not lay.errors


def test_gruvbox_colors_validated(tmp_path):
    assert validate({"colors": {"warn": "#fabd2f", "glow": None}, "widgets": [{"type": "divider", "y": 1}]}) == []
    errs = validate({"colors": {"wrn": "#fff", "crit": "red"}, "widgets": [{"type": "divider", "y": 1}]})
    assert any("unknown name 'wrn'" in e for e in errs) and any("'crit' must be" in e for e in errs)


# ---- JSON paths, filters, weather ----------------------------------------------------------
def weather_vals():
    with open(os.path.join(os.path.dirname(__file__), "data", "open_meteo.json")) as f:
        return values(sample(), {"weather": json.load(f), "aqi": 27})


def test_paths_and_filters():
    from hmid.layouts.values import number, resolve, series
    v = weather_vals()
    assert render_text("{weather.current.temperature_2m:.0f}°C", v) == "15°C"
    assert render_text("{weather.daily.temperature_2m_max.0:.0f}", v) == "15"
    assert render_text("{weather.current.weather_code|wmo}", v) == "Partly cloudy"
    assert render_text("{weather.current.wind_direction_10m|compass}", v) == "W"
    assert render_text("{weather.daily.sunset.0|time}", v) == "18:12"
    assert resolve(v, "weather.current|wmo_icon") == "partly"
    assert len(series(v, "weather.hourly.temperature_2m")) == 24
    assert 0 <= number(v, "weather.hourly.time|hour_index") < 24
    assert render_text("{weather.nope.x}", v) == "–" and render_text("{nothing.x}", v) == "?nothing.x"
    assert resolve({"w": None}, "w.a.b") is None


def test_weather_filters_edge_cases():
    from hmid.layouts.values import FILTERS
    assert FILTERS["compass"](359, {}) == "N" and FILTERS["compass"](135, {}) == "SE"
    assert [FILTERS["uv_level"](x, {}) for x in (0, 2.9, 3, 5.9, 6, 11)] == ["LOW", "LOW", "MOD", "MOD", "HIGH", "HIGH"]
    assert FILTERS["wmo_icon"]({"weather_code": 0, "is_day": 0}, {}) == "moon"
    assert FILTERS["wmo_icon"]({"weather_code": 95, "is_day": 1}, {}) == "storm"
    root = {"utc_offset_seconds": 0, "hourly": {"time": [time.strftime("%Y-%m-%dT%H:00", time.gmtime())]}}
    assert FILTERS["now"]([42], root) == 42


def test_whole_json_source(tmp_path):
    f = tmp_path / "w.json"
    f.write_text('{"current": {"t": 3}}')
    s = Source("w", {"type": "file", "path": str(f)}, allow_commands=False, log=lambda *a: None)
    s.get()
    assert wait_for(lambda: s.value == {"current": {"t": 3}})


def test_weather_openmeteo_layout_renders():
    lay = Layout(os.path.join(EXAMPLES, "weather-openmeteo.json"), log=lambda *a: None)
    assert not lay.errors and lay.refresh_seconds(3) == 60
    assert all(s.every == 3600 for s in lay.sources.values())
    with open(os.path.join(os.path.dirname(__file__), "data", "open_meteo.json")) as f:
        data = json.load(f)
    for name, value in (("weather", data), ("aqi", 27)):
        lay.sources[name].value, lay.sources[name]._t = value, time.time()   # no network in tests
    im = Image.open(io.BytesIO(LayoutRenderer(2).render(lay, sample()))).convert("RGB")
    assert im.size == (480, 800) and im.getpixel((240, 795)) == T.get(2).canvas[:3]
    assert im.getpixel((70, 130)) != (40, 40, 40)               # icon drawn over the card


def test_bar_thresholds_and_graph_series(tmp_path):
    p = write(tmp_path, {"sources": {}, "widgets": [
        {"type": "bar", "x": 10, "y": 10, "w": 200, "value": "cpu_load", "min": 20, "max": 40, "warn": 30, "crit": 35},
        {"type": "graph", "x": 0, "y": 100, "w": 480, "h": 100, "series": "cpu_load"}]})
    lay = Layout(str(p), log=lambda *a: None)
    im = Image.open(io.BytesIO(LayoutRenderer(2).render(lay, sample()))).convert("RGB")
    assert im.getpixel((100, 14)) == T.CRIT[:3]                 # 37 >= crit 35
    errs = validate({"widgets": [{"type": "graph", "x": 0, "y": 0, "w": 1, "h": 1}]})
    assert any("either 'value'" in e for e in errs)


def met_vals():
    d = os.path.join(os.path.dirname(__file__), "data")
    with open(os.path.join(d, "met_norway.json")) as f, open(os.path.join(d, "met_sun.json")) as g:
        return values(sample(), {"met": json.load(f), "sun": json.load(g)})


def test_met_norway_filters():
    from hmid.layouts.values import FILTERS, resolve, series
    v = met_vals()
    now = "met.properties.timeseries.0.data"
    assert render_text("{" + now + ".next_1_hours.summary.symbol_code|met_text}", v) == "Partly cloudy"
    assert resolve(v, now + ".next_1_hours.summary.symbol_code|met_icon") == "partly"
    assert render_text("{" + now + ".instant.details.wind_speed|mul(3.6):.0f}", v) == "17"
    assert len(series(v, "met.properties.timeseries|first(24)|pluck(data.instant.details.air_temperature)")) == 24
    hi = resolve(v, "met.properties.timeseries|today|pluck(data.instant.details.air_temperature)|max")
    assert hi is not None and hi >= resolve(v, now + ".instant.details.air_temperature")
    assert FILTERS["met_text"]("lightrainshowersandthunder_day", {}) == "Light rain showers and thunder"
    assert FILTERS["met_icon"]("clearsky_night", {}) == "moon"
    assert round(FILTERS["feels"]({"air_temperature": 10, "relative_humidity": 70, "wind_speed": 5}, {}), 1) == 5.3
    assert FILTERS["time"]("2026-10-18T18:12", {}) == "18:12"          # no zone: shown as is


def test_weather_met_layout_renders():
    lay = Layout(os.path.join(EXAMPLES, "weather.json"), log=lambda *a: None)
    assert not lay.errors and lay.refresh_seconds(3) == 60
    assert all(s.every == 3600 for s in lay.sources.values())
    v = met_vals()
    for name in ("met", "sun"):
        lay.sources[name].value, lay.sources[name]._t = v[name], time.time()
    im = Image.open(io.BytesIO(LayoutRenderer(2).render(lay, sample()))).convert("RGB")
    assert im.size == (480, 800) and im.getpixel((240, 795)) == T.get(2).canvas[:3]


def test_builtin_stats_matches_classic_layout():
    """Built-in stats screen == layout:classic, pixel for pixel, in every theme."""
    lay = Layout(os.path.join(EXAMPLES, "classic.json"), log=lambda *a: None)
    for name in T.NAMES:
        for s in (sample(game=None), sample(cpu_temp=88, gpu=None, game=None), sample(cpu_power=None, game=None)):
            a = Image.open(io.BytesIO(LayoutRenderer(name).render(lay, s))).convert("RGB")
            b = Image.open(io.BytesIO(Renderer(name).stats(s))).convert("RGB")
            assert a.tobytes() == b.tobytes(), name


def test_themes():
    assert T.name_of(3) == "gruvbox" and T.name_of("2") == "tiffany" and T.name_of("nope") == T.DEFAULT
    assert T.step("graphite", 1) == T.NAMES[1] and T.step(T.NAMES[0], -1) == T.NAMES[-1]
    for name in T.NAMES:                                 # every theme renders every page
        r = Renderer(name)
        assert Image.open(io.BytesIO(r.stats(sample()))).size == (480, 800)
    pinned = {"theme": "nord", "widgets": [{"type": "divider", "y": 1}]}
    assert validate(pinned) == []
    assert LayoutRenderer("graphite").theme_for(pinned).canvas == T.get("nord").canvas


@pytest.mark.skipif(os.geteuid() != 0, reason="needs root to create a root-only file")
def test_pictures_refuse_root_only_files(tmp_path):
    from hmid.layouts.draw import Pictures
    Image.new("RGB", (4, 4)).save(tmp_path / "secret.png")
    os.chmod(tmp_path / "secret.png", 0o600)            # root-owned, not world-readable
    Image.new("RGB", (4, 4)).save(tmp_path / "open.png")
    os.chmod(tmp_path / "open.png", 0o644)
    pics, logs = Pictures(), []
    pics.log = logs.append
    for n in ("secret.png", "open.png"):
        pics.get(str(tmp_path / n))
    assert wait_for(lambda: pics.get(str(tmp_path / "open.png")) is not None)
    assert wait_for(lambda: str(tmp_path / "secret.png") in pics._failed)
    assert "readable by everyone" in logs[0]
