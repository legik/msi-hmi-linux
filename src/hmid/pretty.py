"""Readable output for hmictl. The service answers in JSON (for scripts: hmictl --json ...);
these turn the answers into lines for people."""
from __future__ import annotations

import json


def _v(x) -> str:
    if x is True:
        return "yes"
    if x is False:
        return "no"
    if x is None:
        return "–"
    if isinstance(x, (dict, list)):
        return json.dumps(x, ensure_ascii=False)
    return str(x)


def _table(rows, indent="") -> list[str]:
    rows = [(str(a), str(b)) for a, b in rows]
    w = max((len(a) for a, _ in rows), default=0)
    return [f"{indent}{a:<{w}}  {b}".rstrip() for a, b in rows]


def themes(d) -> list[str]:
    return [("* " if n == d.get("current") else "  ") + n for n in d.get("available", [])]


def layouts(d) -> list[str]:
    return _table(d.items())


def sensors(d) -> list[str]:
    return _table(d.items())


def status(d) -> list[str]:
    game = d.get("game")
    rows = [("connected", _v(d.get("connected"))), ("sleeping", _v(d.get("sleeping"))),
            ("screen", _v(d.get("screen"))),
            ("last panel packet", "–" if d.get("seconds_since_panel_packet") is None
             else f"{d['seconds_since_panel_packet']} s ago"),
            ("missed replies", _v(d.get("missed_replies"))),
            ("game", f"{game['app']} ({game['fps']} fps)" if game else "none"),
            ("game screen active", _v(d.get("game_mode")))]
    out = _table(rows)
    conf = d.get("config") or {}
    if conf:
        if conf.get("proxy"):                          # no password on screen
            from .net import describe
            try:
                conf = {**conf, "proxy": describe(conf["proxy"])}
            except ValueError:
                pass
        out += ["", "settings (/etc/hmid.json and defaults):"] + _table(((k, _v(v)) for k, v in conf.items()), "  ")
    return out


def where(d) -> list[str]:
    act = d.get("active") or {}
    rows = [("panel shows", ", ".join(f"{name} ({mode})" for mode, name in act.items()) or "–")]
    rows += [(k.replace("_", " "), _v(v)) for k, v in d.items() if k != "active"]
    return _table(rows)


def sources(d) -> list[str]:
    out = _table([("layout", f"{d.get('layout')} ({d.get('origin')})"), ("file", d.get("file")),
                  ("errors", "; ".join(d.get("errors") or []) or "none")])
    src = d.get("sources") or {}
    out += ["", "sources:" if src else "sources: none"]
    for name, s in src.items():
        info = [f"as {s['as']}"] if s.get("as") else []
        if s.get("updated_s_ago") is not None:
            info.append(f"updated {s['updated_s_ago']} s ago")
        out.append(f"  {name}" + (f"  ({', '.join(info)})" if info else ""))
        if s.get("error"):
            out.append(f"    error: {s['error']}")
        value = s.get("value")
        lines = str(value).splitlines() if value not in (None, "") else ["(empty)"]
        for i, line in enumerate(lines):
            out.append(f"    {i}: {line}" if len(lines) > 1 else f"    {line}")   # numbered: line(n)
    pics = d.get("pictures") or []
    if pics:
        out += ["", "pictures:"]
        for p in pics:
            out += [f"  widget {p['widget']}  {p['path_template']}", f"    {p['path'] or '(empty)'}",
                    f"    {p['state']}"]
    return out


def settings(d) -> list[str]:
    conf, mine = d.get("settings") or {}, set(d.get("in_file") or [])
    if conf.get("proxy"):
        from .net import describe
        try:
            conf = {**conf, "proxy": describe(conf["proxy"])}
        except ValueError:
            pass
    rows = [(k, _v(v) + ("" if k in mine else "   (default)")) for k, v in conf.items()]
    return [f"{d.get('file', '/etc/hmid.json')} - change with: hmictl set <setting> <value>", ""] + _table(rows)


def one_value(v) -> list[str]:
    return [v if isinstance(v, str) else _v(v)]


FORMATS = {"themes": themes, "layouts": layouts, "sensors": sensors, "status": status,
           "where": where, "sources": sources}


def format_get(args, answer: str) -> str:
    """get / get <key>."""
    if answer.startswith("error"):
        return answer
    try:
        d = json.loads(answer)
        return "\n".join(one_value(d) if len(args) > 1 else settings(d))
    except (ValueError, TypeError, AttributeError):
        return answer


def format_answer(command: str, answer: str) -> str:
    """The service's answer for people; anything unexpected is shown as it came."""
    fmt = FORMATS.get(command)
    if not fmt or answer.startswith(("error", "ok")):
        return answer
    try:
        return "\n".join(fmt(json.loads(answer)))
    except (ValueError, TypeError, KeyError, AttributeError):
        return answer
