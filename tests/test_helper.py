"""hmid-helper (the root part) and how hmid uses it when it runs as its own user."""
import json
import os
import socket
import threading
import time

import pytest

from hmid import config, helper, privileged
from hmid.privileged import HelperError


@pytest.fixture
def helper_sock(tmp_path):
    path = str(tmp_path / "h" / "helper.sock")
    threading.Thread(target=helper.serve, args=(path, {os.getuid()}), daemon=True).start()
    for _ in range(200):
        if os.path.exists(path):
            break
        time.sleep(0.01)
    return path


def _conf(monkeypatch, touch):
    monkeypatch.setattr(config, "load", lambda *a, **kw: config.validate({"touch_actions": touch}))
    helper._actions = None


def test_simple_operations(helper_sock, monkeypatch, tmp_path):
    from hmid.sensors import cpu, memory
    monkeypatch.setattr(memory, "dmidecode_mhz", lambda: 6000)
    (tmp_path / "energy").write_text("123456\n")
    monkeypatch.setattr(cpu, "RAPL", str(tmp_path / "energy"))
    assert privileged.call("ram-clock", path=helper_sock) == 6000
    assert privileged.call("cpu-energy", path=helper_sock) == 123456


def test_actions_are_looked_up_by_the_helper(helper_sock, monkeypatch, tmp_path):
    mark = tmp_path / "ran"
    _conf(monkeypatch, {"250": f"root:echo hello > {mark}", "251": "builtin:mystic"})
    assert privileged.call("action", 250, path=helper_sock) == f"root:echo hello > {mark}"
    for _ in range(200):
        if mark.exists():
            break
        time.sleep(0.01)
    assert mark.read_text() == "hello\n"
    assert privileged.call("action", 251, path=helper_sock).startswith("not a helper action")   # stays in hmid
    assert privileged.call("action", 252, path=helper_sock).startswith("not a helper action")   # nothing set


def test_layout_commands_only_from_root_owned_layout_files(helper_sock, monkeypatch, tmp_path):
    from hmid import layouts
    mine = tmp_path / "layouts"
    mine.mkdir(mode=0o755)
    monkeypatch.setattr(layouts, "DIR", str(mine))
    lay = {"sources": {"hi": {"type": "command", "run": "printf 'a\\nb'"}, "web": {"type": "http", "url": "x"}},
           "widgets": [{"type": "text", "x": 0, "y": 0, "text": "{hi}"}]}
    (mine / "t.json").write_text(json.dumps(lay))
    os.chmod(mine / "t.json", 0o644)
    assert privileged.call("source", str(mine / "t.json"), "hi", path=helper_sock) == b"a\nb"
    with pytest.raises(HelperError, match="no command source 'web'"):
        privileged.call("source", str(mine / "t.json"), "web", path=helper_sock)
    elsewhere = tmp_path / "t.json"
    elsewhere.write_text(json.dumps(lay))
    with pytest.raises(HelperError, match="must be in"):
        privileged.call("source", str(elsewhere), "hi", path=helper_sock)
    os.chmod(mine / "t.json", 0o666)                     # anyone could change it
    with pytest.raises(HelperError, match="only root can change"):
        privileged.call("source", str(mine / "t.json"), "hi", path=helper_sock)


def test_other_users_and_bad_requests_are_refused(tmp_path):
    path = str(tmp_path / "s.sock")
    threading.Thread(target=helper.serve, args=(path, {os.getuid() + 12345}), daemon=True).start()
    for _ in range(200):
        if os.path.exists(path):
            break
        time.sleep(0.01)
    with pytest.raises(HelperError, match="may not use"):
        privileged.call("ram-clock", path=path)
    with pytest.raises(ValueError):
        privileged.call("run", "rm -rf /")                 # not an operation: never sent


def test_bad_request_on_the_wire(helper_sock):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(helper_sock)
    s.sendall(b'{"op": "shell", "args": ["id"]}\n')
    r = json.loads(s.makefile().readline())
    assert r == {"ok": False, "error": "bad request"}


def test_helper_not_running():
    with pytest.raises(HelperError, match="hmid-helper is not running"):
        privileged.call("ram-clock", path="/nonexistent/helper.sock")


def test_hmid_as_its_own_user_delegates(monkeypatch):
    """Commands and the alarm go to the helper; lights and themes stay in hmid."""
    from hmid.actions import Actions
    monkeypatch.setattr(privileged, "direct", lambda: False)
    calls = []
    monkeypatch.setattr(privileged, "call", lambda op, *a, **kw: calls.append((op, *a)) or "ok")
    acts = Actions({"250": "root:reboot"}, log=lambda *a: None, on_theme=lambda d: calls.append(("theme", d)))
    acts.run("root:reboot", 250)
    acts.run("builtin:timer_alarm", 70)
    assert acts.alarm.active
    acts.alarm.stop()
    acts.run("builtin:theme_next", 251)
    assert calls == [("action", 250), ("action", 70), ("alarm-stop",), ("theme", 1)]
    assert not acts.alarm.active
    acts.free_memory.drop()
    assert calls[-1] == ("drop-caches",)


def test_layout_command_source_goes_to_the_helper(monkeypatch):
    from hmid.layouts.sources import Source
    monkeypatch.setattr(privileged, "direct", lambda: False)
    seen = []
    monkeypatch.setattr(privileged, "call", lambda op, *a, **kw: seen.append((op, *a)) or b"42")
    s = Source("n", {"type": "command", "run": "echo 1"}, allow_commands=True, log=lambda *a: None,
               layout_path="/etc/hmid/layouts/x.json")
    assert s.fetch() == b"42" and seen == [("source", "/etc/hmid/layouts/x.json", "n")]
