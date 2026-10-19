import json

from hmid import config


def test_defaults_when_missing(tmp_path):
    c = config.load(str(tmp_path / "none.json"))
    assert c == config.DEFAULTS


def test_bad_values_fall_back(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"brightness": "high", "screen": "weather", "hwmon_mode": "multi",
                             "nope": 1, "clock_24h": 1, "stats_interval": 2.5}))
    warnings = []
    c = config.load(str(p), warn=warnings.append)
    assert c["brightness"] == 50 and c["screen"] == "stats" and c["hwmon_mode"] == "multi"
    assert c["clock_24h"] is True and c["stats_interval"] == 2.5
    assert len(warnings) == 4


def test_brightness_clamped():
    assert config.validate({"brightness": 250})["brightness"] == 100


def test_migrates_hwmon_hide():
    c = config.validate({"hwmon_hide": [11], "hwmon_network": False}, warn=lambda m: None)
    assert "vrm_temp" not in c["hwmon_sensors"] and "cpu_load" in c["hwmon_sensors"]
    assert "upload" not in c["hwmon_sensors"]


def test_choices_go_to_the_state_file(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"fan_map": {"cpu_fan": "fan2"}, "brightness": 10}))
    c = config.load(str(p))
    c["brightness"], c["screen"] = 70, "clock"
    st = config.state_path_for(str(p))
    config.save_state(c, st)
    assert json.loads(p.read_text()) == {"fan_map": {"cpu_fan": "fan2"}, "brightness": 10}   # untouched
    assert json.loads(open(st).read()) == {"screen": "clock", "brightness": 70, "hwmon_mode": "list",
                                           "theme": "monokai"}
    again = config.load(str(p))
    assert again["brightness"] == 70 and again["screen"] == "clock"           # state wins
    config.forget_state("brightness", st)
    assert config.load(str(p))["brightness"] == 10                           # the file decides again
    assert config.state_path_for(config.PATH) == config.STATE


def test_theme_setting_and_migration():
    assert config.validate({})["theme"] == "monokai"
    assert config.validate({"stats_theme": 3})["theme"] == "gruvbox"        # old numeric setting
    assert config.validate({"stats_theme": 2, "theme": "nord"})["theme"] == "nord"
    warnings = []
    assert config.validate({"theme": "neon"}, warn=warnings.append)["theme"] == "monokai" and warnings


def test_shell_completion_words(capsys):
    import re

    from hmid.cli import COMMANDS, CTL_HELP, main_ctl
    for n, _ in COMMANDS:                                  # every completed command is in the help
        assert re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", CTL_HELP), n
    main_ctl(["_complete", "layouts"])
    assert "now-playing" in capsys.readouterr().out.split()
    main_ctl(["_complete", "themes"])
    assert "graphite" in capsys.readouterr().out.split()
    main_ctl(["_complete", "lights"])
    assert "92:Rainbow" in capsys.readouterr().out.split()
    assert main_ctl(["_complete", "nonsense"]) == 0 and capsys.readouterr().out.strip() == ""


def test_completion_scripts_are_installed():
    import os
    root = os.path.join(os.path.dirname(__file__), "..")
    for f in ("packaging/completions/_hmictl", "packaging/completions/hmictl.bash"):
        assert os.path.exists(os.path.join(root, f)), f
    with open(os.path.join(root, "install.sh")) as fh:
        inst = fh.read()
    assert "_hmictl" in inst and "bash-completion" in inst


def test_local_tools_without_arguments_show_usage(capsys):
    from hmid.cli import main_ctl
    for cmd in ("preview", "preview-themes", "check", "customize"):
        assert main_ctl([cmd]) == 2
        assert capsys.readouterr().err.startswith(f"use: hmictl {cmd} ")


def test_readable_answers():
    import json

    from hmid.pretty import format_answer
    t = format_answer("themes", json.dumps({"current": "nord", "available": ["monokai", "nord"]}))
    assert t.splitlines() == ["  monokai", "* nord"]
    s = format_answer("status", json.dumps({"connected": True, "game": None,
                                            "config": {"proxy": "socks5h://me:secret@h:1"}}))
    assert "connected" in s and "yes" in s and "secret" not in s and "socks5h://me@h:1" in s
    src = format_answer("sources", json.dumps({"layout": "x", "origin": "built-in", "file": "/f", "errors": [],
                                               "sources": {"p": {"value": "a\nb", "error": None}},
                                               "pictures": []}))
    assert "    0: a" in src and "    1: b" in src
    assert format_answer("themes", "error nope") == "error nope"
    assert format_answer("themes", "not json") == "not json"
    assert format_answer("brightness", "ok") == "ok"


def test_json_flag_passes_the_raw_answer(monkeypatch, capsys):
    import json

    from hmid.cli import main_ctl
    from hmid.daemon import control
    answer = json.dumps({"current": "nord", "available": ["nord"]})
    monkeypatch.setattr(control, "request", lambda args: answer)
    main_ctl(["themes"])
    assert capsys.readouterr().out.strip() == "* nord"
    main_ctl(["themes", "--json"])
    assert capsys.readouterr().out.strip() == answer


def test_edit_one_setting(tmp_path):
    import json

    from hmid import config
    p = tmp_path / "hmid.json"
    p.write_text('{"brightness": 40, "my_note": "kept"}')
    conf, err = config.edit("debug_events", True, path=str(p))
    assert err is None and conf["debug_events"] is True
    data = json.loads(p.read_text())
    assert data == {"brightness": 40, "my_note": "kept", "debug_events": True}   # the rest untouched
    conf, err = config.edit("touch_actions.250", "builtin:theme_next", path=str(p))
    assert err is None and conf["touch_actions"] == {"250": "builtin:theme_next"}
    conf, err = config.edit("touch_actions.250", remove=True, path=str(p))
    assert err is None and "touch_actions" not in json.loads(p.read_text())
    conf, err = config.edit("brightness", remove=True, path=str(p))
    assert conf["brightness"] == config.DEFAULTS["brightness"]

    before = p.read_text()
    for key, value, msg in (("debug_events", "yes", "wrong type"), ("proxy", "socks4://x:1", "proxy"),
                            ("theme", "neon", "unknown theme"), ("nonsense", 1, "unknown setting"),
                            ("debug.x", 1, "unknown setting"), ("brightness.x", 1, "no sub-keys"),
                            ("touch_actions.250", "steam", "user:<command>"),
                            ("touch_actions.abc", "none", "not a panel item")):
        conf, err = config.edit(key, value, path=str(p))
        assert conf is None and msg in err, (key, err)
    assert p.read_text() == before                         # nothing written on a bad value
    assert config.parse_value("true") is True and config.parse_value("50") == 50
    assert config.parse_value("socks5h://h:1") == "socks5h://h:1" and config.parse_value("null") is None


def test_picture_is_handed_over_to_the_service(tmp_path, monkeypatch):
    import os
    import pwd

    from hmid.cli import _hand_over_picture
    pic = tmp_path / "Cat Photo.GIF"
    pic.write_bytes(b"GIF89a")
    run = tmp_path / "run"
    run.mkdir()
    me = pwd.getpwuid(os.getuid())
    monkeypatch.setattr(pwd, "getpwnam", lambda name: me)
    out = _hand_over_picture(["picture", "fit", str(pic)], run_dir=str(run))
    assert out == ["picture", "fit", str(run / "picture.gif")] and (run / "picture.gif").read_bytes() == b"GIF89a"
    assert _hand_over_picture(["picture", "builtin", "2"], run_dir=str(run)) == ["picture", "builtin", "2"]
    assert _hand_over_picture(["picture", "/nope.gif"], run_dir=str(run)) == ["picture", "/nope.gif"]


def test_edit_keeps_file_permissions(tmp_path):
    import os

    from hmid import config
    p = tmp_path / "hmid.json"
    p.write_text("{}")
    os.chmod(p, 0o640)
    conf, err = config.edit("debug_events", True, path=str(p))
    assert err is None and oct(os.stat(p).st_mode & 0o777) == "0o640"
