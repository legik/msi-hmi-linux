"""Service behaviour against a fake panel: the exact command order on the real
hardware paths (these sequences were found by comparing with MSI Center)."""
import json
import os
import struct

import pytest
from test_hwmon import sample

from hmid.daemon.service import Service
from hmid.panel import protocol as P
from hmid.panel.device import Panel


@pytest.fixture
def svc(tmp_path, fake, no_sleep, monkeypatch):
    p = tmp_path / "hmid.json"
    p.write_text("{}")
    s = Service(str(p))
    s.panel, s.connected = Panel(fake), True
    s.log = lambda *a: None
    monkeypatch.setattr("hmid.daemon.service.log", lambda *a: None)
    monkeypatch.setattr(s.sensors, "sample", lambda: sample())
    s.background_video = lambda: b"VIDEO" * 100
    return s


def set_conf(svc, **kw):
    svc.conf.update(kw)


def test_stats_screen_sequence(svc, fake):
    fake.display[P.Mode.DYNAMIC] = bytes([1, 0, 0, 1])
    svc.show_screen()
    assert fake.script() == [
        "cmd 24",                                  # brightness
        "msg 55AASETTEMP05AA5", "display 24 sub=0 01",
        "upload M25-S0-V-R0.mp4",
        "msg 55AASETLASTHWM255AA5", "display 25 sub=0 01",
        "cmd 20", "get_display 25",                # MSI's queries before every overlay
        "upload M25-S0-O-R000.png",
    ]
    assert svc.dynamic_active and svc.screen.name == "stats"


def test_overlay_not_uploaded_unless_panel_confirms(svc, fake):
    fake.display[P.Mode.DYNAMIC] = bytes([1, 0, 0, 0])
    svc.show_screen()
    assert "upload M25-S0-O-R000.png" not in fake.script()


def test_list_monitor_sequence(svc, fake):
    set_conf(svc, screen="hwmon", hwmon_mode="list", hwmon_sensors=["cpu_load", "gpu_temp", "download"])
    svc.show_screen()
    script = fake.script()
    assert script[1:] == ["msg 55AASETTEMP05AA5", "display 24 sub=0 01", "msg 55AASETLASTHWM005AA5",
                          "display 7 sub=2 " + (bytes([0, 2]) + bytes(14)).hex(),
                          "display 0 sub=2 " + bytes([0, 2, 0, 0, 0, 0, 0, 2] + [0] * 8).hex(),
                          "cmd 48", "cmd 60"]
    assert svc.list_active and svc.screen.keepalive_mode == P.Mode.HWMON


def test_multi_monitor_uses_dynamic_canvas(svc, fake):
    set_conf(svc, screen="hwmon", hwmon_mode="multi")
    fake.display[P.Mode.DYNAMIC] = bytes([1, 0, 0, 1])
    svc.show_screen()
    assert "upload M25-S0-O-R000.png" in fake.script() and svc.screen.dynamic


def test_missing_video_falls_back_to_clock(svc, fake):
    def boom():
        raise OSError("gone")
    svc.background_video = boom
    svc.show_screen()
    assert svc.screen.name == "clock" and fake.script()[-1].startswith("display 5")


def test_overlay_blocked_while_menu_or_alarm(svc):
    svc.dynamic_active, svc.showing_default = True, True
    assert svc.overlay_wanted()
    svc.menu_open = True
    assert not svc.overlay_wanted()
    svc.menu_open = False
    svc.actions.alarm._stop = __import__("threading").Event()       # alarm ringing
    assert not svc.overlay_wanted()


def test_keepalive_detects_return_and_panel_picked_monitor(svc, fake, monkeypatch):
    fake.display[P.Mode.DYNAMIC] = bytes([1, 0, 0, 1])
    svc.show_screen()
    svc.menu_open, svc.last_real_touch = True, 0
    svc.check_dynamic(bytes([1, 0, 0, 1]))
    assert not svc.menu_open and svc.showing_default

    set_conf(svc, screen="clock")
    svc.show_screen()
    svc.check_dynamic(bytes([1]))                 # user opened the panel's own monitor
    assert svc.picked_dynamic and svc.overlay_wanted()
    svc.check_dynamic(bytes([0]))
    assert not svc.picked_dynamic


def ev(item, flag=0):
    return bytes([1, 0, item, flag]) + struct.pack("<HH", 10, 10) + bytes(56)


def test_reader_dispatches_taps(svc, fake):
    taps = []
    svc.actions.handle = taps.append
    fake.events = [ev(8), ev(0, 1), ev(60), ev(60), ev(24)]
    real = fake.read_event

    def read(timeout):
        if not fake.events:
            svc.connected = False
        return real(timeout)
    fake.read_event = read
    svc.reader()
    assert taps == [60, 24] and svc.menu_open


def test_control_commands(svc, fake, tmp_path):
    assert svc.handle("brightness 70") == "ok"
    assert json.loads((tmp_path / "hmid-state.json").read_text())["brightness"] == 70
    assert "brightness" not in json.loads((tmp_path / "hmid.json").read_text())   # /etc stays as it was
    assert svc.handle("hwmon bogus").startswith("error")
    assert svc.handle("nonsense") == "error unknown command 'nonsense' (hmictl help lists them)"
    assert svc.handle("picture").startswith("error use: picture [fill|fit|stretch]")
    assert svc.handle("brightness") == "error use: brightness <0-100>"
    assert svc.handle("theme").startswith("error use: theme")
    status = json.loads(svc.handle("status"))
    assert status["connected"] is True
    out = json.loads(svc.handle("sensors"))
    assert out["vrm_temp"] == "57 °C"


def test_layout_screen(svc, fake, tmp_path):
    p = tmp_path / "mine.json"
    p.write_text(json.dumps({"refresh": 7, "widgets": [{"type": "text", "x": 0, "y": 0, "text": "{cpu_load}"}]}))
    fake.display[P.Mode.DYNAMIC] = bytes([1, 0, 0, 1])
    set_conf(svc, screen="layout:" + str(p))
    svc.show_screen()
    assert svc.screen.dynamic and svc.screen.interval == 7
    assert fake.script()[-1] == "upload M25-S0-O-R000.png"
    assert svc.handle("layout nope").startswith("error")


def run_reader(svc, fake, events, clock):
    """Feed events through the reader; clock: list of times, one per event."""
    import hmid.daemon.service as S
    taps, logs = [], []
    svc.actions.handle = taps.append
    S.log = logs.append
    fake.events = list(events)
    times = iter(clock)
    real_time = S.time.time
    S.time.time = lambda: next(times, clock[-1])
    real = fake.read_event

    def read(timeout):
        if not fake.events:
            svc.connected = False
        return real(timeout)
    fake.read_event = read
    try:
        svc.reader()
    finally:
        S.time.time = real_time
    return taps, logs


def test_taps_in_menu_and_ignored_on_our_screen(svc, fake):
    # real log: menu open, tap -> item jumps to the button, falls back to 0 ~2 s later;
    # flag stays 0. Then the panel is back on our screen and changes to 90 by itself.
    svc.menu_open = True
    taps, logs = run_reader(svc, fake, [ev(0), ev(40), ev(0), ev(41), ev(0)],
                            [0, 0, 1, 1, 3, 3, 6, 6, 8, 8])
    assert taps == [40, 41]
    svc.connected, svc.menu_open = True, False         # panel went back to our screen
    taps, logs = run_reader(svc, fake, [ev(0), ev(90)], [0, 0, 6, 6])
    assert taps == [] and svc.menu_open                # treated as the menu opening
    assert any("no action" in str(m) for m in logs)


def test_menu_screen_taps_count_at_once(svc, fake):
    set_conf(svc, screen="menu")
    svc.show_screen()
    taps, _ = run_reader(svc, fake, [ev(0), ev(24)], [0, 0, 1, 1])
    assert taps == [24]


def test_game_screen_switch(svc, fake):
    from hmid.sensors import GameSample
    fake.display[P.Mode.DYNAMIC] = bytes([1, 0, 0, 1])
    set_conf(svc, screen="stats", game_screen="clock")
    svc.show_screen()
    game = [GameSample(120.0, 8.3, "vkcube")]
    svc.sensors.fps.read = lambda: game[0]
    svc.check_game(100.0)
    assert svc.screen.name == "clock" and svc.game_mode
    n = len(fake.sent)
    svc.check_game(102.0)                       # still running: no re-switch
    assert len(fake.sent) == n
    game[0] = None
    svc.check_game(110.0)                       # last seen at 102: 8 s ago, keep the game screen
    assert svc.screen.name == "clock"
    svc.check_game(118.0)                       # 16 s since last seen: back to the default
    assert svc.screen.name == "stats" and not svc.game_mode
    assert json.loads(svc.handle("status"))["game"] is None


def test_game_screen_respects_user_choice_and_menu(svc, fake):
    from hmid.sensors import GameSample
    set_conf(svc, screen="stats", game_screen="clock")
    svc.sensors.fps.read = lambda: GameSample(60.0, 16.6, "game")
    svc.menu_open = True
    svc.check_game(10.0)                        # panel menu open: wait
    assert not svc.game_mode
    svc.menu_open = False
    svc.check_game(12.0)
    assert svc.game_mode and svc.screen.name == "clock"
    assert svc.handle("menu") == "ok"           # user picks a screen during the game
    assert svc.game_override and not svc.game_mode
    svc.check_game(14.0)
    assert svc.screen.name == "menu"
    assert json.loads(svc.handle("status"))["game"]["app"] == "game"


def test_picture_commands(svc, fake, tmp_path):
    from PIL import Image
    img = tmp_path / "p.jpg"
    Image.new("RGB", (1920, 1080), (200, 30, 30)).save(img)
    assert svc.handle(f"picture {img}") == "ok"
    assert fake.script()[-3:] == ["display 24 sub=0 01", "upload M1-S7-O-R0.png", "display 1 sub=0 " + bytes([0] * 7 + [1]).hex()]
    assert svc.handle("picture builtin 2") == "ok"
    assert fake.script()[-2:] == ["display 24 sub=0 01", "display 1 sub=0 " + bytes([0, 0, 1, 0, 0, 0, 0, 0]).hex()]
    assert svc.handle("picture builtin 7").startswith("error")


def test_picture_animated_gif(svc, fake, tmp_path, monkeypatch):
    from test_media import animated_gif

    from hmid import media
    animated_gif(tmp_path / "a.gif")
    seen = []
    monkeypatch.setattr(media, "animation_avi", lambda path, mode, rotate: seen.append((mode, rotate)) or b"AVI" * 100)
    assert svc.handle(f"picture {tmp_path / 'a.gif'}") == "ok"
    assert "upload M1-S7-V-R0.avi" in fake.script() and seen == [("fill", False)]
    assert svc.handle(f"picture fit rotate {tmp_path / 'a.gif'}") == "ok" and seen[-1] == ("fit", True)
    assert svc.handle("picture /nope.gif").startswith("error no such file")


def test_theme_commands(svc, fake, tmp_path):
    fake.display[P.Mode.DYNAMIC] = bytes([1, 0, 0, 1])
    svc.show_screen()
    assert svc.handle("theme nord") == "ok nord"
    assert json.loads((tmp_path / "hmid-state.json").read_text())["theme"] == "nord"
    assert svc.redraw                                                # session loop redraws at once
    assert svc.handle("theme next").startswith("ok ")
    assert svc.handle("theme neon").startswith("error unknown theme")
    assert json.loads(svc.handle("themes"))["current"] != "nord"


def test_theme_button_actions(svc):
    first = svc.conf["theme"]
    svc.actions.run("builtin:theme_next", 40)
    assert svc.conf["theme"] != first
    svc.actions.run("builtin:theme_prev", 41)
    assert svc.conf["theme"] == first


def test_sources_command_explains_pictures(svc, fake, tmp_path):
    from PIL import Image
    Image.new("RGB", (10, 10), (1, 2, 3)).save(tmp_path / "c.png")
    (tmp_path / "cover.txt").write_text((tmp_path / "c.png").as_uri())
    p = tmp_path / "pic.json"
    p.write_text(json.dumps({"sources": {"cover": {"type": "file", "path": str(tmp_path / "cover.txt")}},
                             "widgets": [{"type": "image", "x": 0, "y": 0, "w": 50, "h": 50, "fit": "cover",
                                          "path": "{cover}", "when": "cover"},
                                         {"type": "image", "x": 0, "y": 0, "path": "{nothing}"}]}))
    assert svc.handle("sources").startswith("error the panel shows")
    fake.display[P.Mode.DYNAMIC] = bytes([1, 0, 0, 1])
    set_conf(svc, screen="layout:" + str(p))
    svc.show_screen()
    import time as _t
    end = _t.time() + 3
    while _t.time() < end:
        out = json.loads(svc.handle("sources"))
        if out["sources"]["cover"]["value"] and out["pictures"][0]["state"].startswith("loaded"):
            break
        svc.screen.render(sample())
        _t.sleep(0.05)
    assert out["file"] == str(p) and out["origin"].startswith("yours")
    assert out["sources"]["cover"]["value"].startswith("file://") and out["sources"]["cover"]["error"] is None
    assert out["pictures"][0]["state"] == "loaded 10x10"
    assert out["pictures"][1]["path_template"] == "{nothing}" and out["pictures"][1]["state"] == "unknown value 'nothing'"


def test_theme_change_keeps_loaded_pictures(svc):
    pics = svc.layout_renderer.pictures
    svc.set_theme("nord")
    assert svc.layout_renderer.pictures is pics


def test_web_request_lines_only_with_debug_events(tmp_path, monkeypatch):
    from hmid import net
    monkeypatch.setattr("hmid.daemon.service.log", lambda *a: None)
    p = tmp_path / "hmid.json"
    p.write_text("{}")
    Service(str(p))
    assert net._log is None
    p.write_text('{"debug_events": true}')
    Service(str(p))
    assert net._log is not None
    net.set_logger(None)


def test_control_socket_round_trip(tmp_path):
    """Through a real socket, as hmictl uses it: quoted arguments, multi-line answers."""
    import threading

    from hmid.daemon import control
    path = str(tmp_path / "c.sock")
    got = []

    def handler(line):
        got.append(line)
        return "line one\nline two"
    threading.Thread(target=control.serve, args=(handler, path), daemon=True).start()
    import time as _t
    for _ in range(100):
        if os.path.exists(path):
            break
        _t.sleep(0.01)
    assert control.request(["sources"], path) == "line one\nline two"
    control.request(["picture", "fit", "/home/me/My Pictures/cat.gif"], path)
    import shlex
    assert shlex.split(got[-1]) == ["picture", "fit", "/home/me/My Pictures/cat.gif"]


def test_handle_keeps_quoted_paths(svc, tmp_path):
    from PIL import Image
    d = tmp_path / "My Pictures"
    d.mkdir()
    Image.new("RGB", (10, 10)).save(d / "c a t.png")
    assert svc.handle(f"picture '{d / 'c a t.png'}'") == "ok"


def test_set_get_unset_commands(svc, fake, tmp_path):
    from hmid import net
    assert svc.handle("set debug_events true") == "ok" and net._log is not None
    assert json.loads(svc.handle("get debug_events")) is True
    assert svc.handle("set proxy socks5h://127.0.0.1:1080") == "ok" and net._default == "socks5h://127.0.0.1:1080"
    assert svc.handle("unset proxy") == "ok" and net._default is None
    assert svc.handle("set touch_actions.250 builtin:theme_next") == "ok"
    assert svc.actions.map[250] == "builtin:theme_next"
    assert svc.handle("set light_colors.82 FF0000") == "ok" and svc.actions.lights.colors[82] == "FF0000"
    assert svc.handle("set brightness 70") == "ok" and fake.script()[-1] == "cmd 24"
    assert svc.handle("set menu_user_scenario true").startswith("ok - menu_user_scenario takes effect after")
    assert svc.handle("set screen layout:nope").startswith("error no layout 'nope'")
    assert svc.handle("set debug_events maybe").startswith("error")
    assert svc.handle("set").startswith("error use: set")
    d = json.loads(svc.handle("get"))
    assert d["settings"]["brightness"] == 70 and "brightness" in d["in_file"]
    assert json.loads((tmp_path / "hmid.json").read_text())["touch_actions"] == {"250": "builtin:theme_next"}
    net.set_logger(None)
    net.set_default(None)


def test_readable_get():
    from hmid.pretty import format_get
    out = format_get(["get"], json.dumps({"settings": {"brightness": 70, "theme": "monokai",
                                                       "proxy": "socks5h://u:pw@h:1"},
                                          "in_file": ["brightness", "proxy"], "file": "/etc/hmid.json"}))
    assert "brightness  70" in out and "monokai   (default)" in out and "pw@" not in out
    assert format_get(["get", "theme"], '"monokai"') == "monokai"
    assert format_get(["get", "x"], "error unknown setting 'x'") == "error unknown setting 'x'"


def test_reload_and_choices_while_running(svc, fake, tmp_path, monkeypatch):
    from hmid import privileged
    conf = tmp_path / "hmid.json"
    conf.write_text('{"debug_events": true, "touch_actions": {"251": "none"}}')
    assert svc.handle("reload") == "ok" and svc.conf["debug_events"] and svc.actions.map[251] == "none"
    assert svc.handle("set brightness 30") == "ok"                       # a choice: state file
    assert json.loads((tmp_path / "hmid-state.json").read_text())["brightness"] == 30
    assert "brightness" not in json.loads(conf.read_text())
    assert svc.handle("unset brightness") == "ok" and svc.conf["brightness"] == 50
    assert svc.handle("set brightness lots").startswith("error")
    monkeypatch.setattr(privileged, "direct", lambda: False)             # hmid as its own user
    assert "sudo hmictl set" in svc.handle("set debug_events false")     # may not write /etc
    assert json.loads(conf.read_text())["debug_events"] is True


def test_hmictl_edits_the_file_and_reloads(tmp_path, monkeypatch, capsys):
    from hmid import config
    from hmid.cli import main_ctl
    from hmid.daemon import control
    conf = tmp_path / "hmid.json"
    conf.write_text("{}")
    monkeypatch.setattr(config, "PATH", str(conf))
    sent = []
    monkeypatch.setattr(control, "request", lambda args: sent.append(args) or "ok")
    assert main_ctl(["set", "debug_events", "true"]) == 0
    assert json.loads(conf.read_text()) == {"debug_events": True} and sent[-1] == ["reload"]
    assert main_ctl(["set", "debug_events", "maybe"]) == 1 and "wrong type" in capsys.readouterr().out
    assert main_ctl(["set", "theme", "nord"]) == 0 and sent[-1] == ["set", "theme", "nord"]   # a choice
    monkeypatch.setattr("os.geteuid", lambda: 1000)
    assert main_ctl(["set", "proxy", "socks5h://h:1"]) == 1
    assert "sudo" in capsys.readouterr().err
