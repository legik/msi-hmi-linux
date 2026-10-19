"""Default screens the service can put on the panel.

A screen opens itself on the panel (boot, wake, `hmictl <screen>`) and says how the
keepalive should watch it. Screens on the dynamic canvas (stats, multi monitor) also
draw the overlay that the service uploads every `stats_interval` seconds.

To add a screen (weather, custom data, ...): subclass Screen or DynamicScreen and
register it in make_screen().
"""
from __future__ import annotations

import time

from .. import hwmon
from ..panel.protocol import DYNAMIC_VIDEO, Mode, Msg


class Screen:
    name = "?"
    keepalive_mode = Mode.DYNAMIC      # GetDisplay mode polled every 2 s
    dynamic = False                    # lives on the dynamic canvas (screen 25)

    def __init__(self, svc):
        self.svc = svc

    @property
    def p(self):
        return self.svc.panel

    def open(self) -> bool:
        raise NotImplementedError

    @property
    def interval(self) -> float:
        """Seconds between overlay redraws (dynamic screens)."""
        return self.svc.conf["stats_interval"]


class ClockScreen(Screen):
    name = "clock"

    def open(self):
        c = self.svc.conf
        self.p.clock(c["clock_style"], c["clock_24h"])
        return True


class MenuScreen(Screen):
    name = "menu"

    def open(self):
        self.p.set_display(Mode.MAIN_MENU)
        return True


class DynamicScreen(Screen):
    """MSI's dynamic screen: loading -> background video -> screen 25 -> PNG overlays.
    A shortcut (switching to 25 without re-uploading the video) froze the panel on the
    next upload, so opening always runs the full sequence, as MSI does."""
    dynamic = True

    def open(self):
        svc, p = self.svc, self.p
        try:
            video = svc.background_video()
        except OSError as e:
            svc.log("dynamic screen: background video missing:", e)
            return False
        p.msg(Msg.SET_TEMP)
        p.set_display(Mode.LOADING)
        time.sleep(1.5)
        p.upload(video, DYNAMIC_VIDEO)
        time.sleep(1.5)
        p.msg(Msg.last_hwmon(Mode.DYNAMIC))
        p.set_display(Mode.DYNAMIC)
        svc.dynamic_active = True
        svc.push_overlay()
        return True

    def render(self, sample) -> bytes:
        raise NotImplementedError


class StatsScreen(DynamicScreen):
    name = "stats"

    def render(self, sample):
        return self.svc.renderer.stats(sample)


class MultiMonitorScreen(DynamicScreen):
    """MSI's "Multi" hardware monitor: up to 12 sensor tiles per page, pages rotate."""
    name = "hwmon"

    def __init__(self, svc):
        super().__init__(svc)
        self.page, self.page_t = 0, time.time()

    def render(self, sample):
        names = self.svc.hwmon_names("multi", sample)
        per = hwmon.MULTI_PER_PAGE
        pages = max(1, -(-len(names) // per))
        if pages > 1 and time.time() - self.page_t >= self.svc.conf["hwmon_page_seconds"]:
            self.page, self.page_t = (self.page + 1) % pages, time.time()
        page = self.page % pages
        return self.svc.renderer.multi(sample, names[page * per:(page + 1) * per], page, pages)


class ListMonitorScreen(Screen):
    """MSI's panel-drawn hardware monitor: the panel composes each sensor screen from its
    stored digit images and cycles through them; we only send numbers (cmd 48 + 60)."""
    name = "hwmon"
    keepalive_mode = Mode.HWMON

    def open(self, loading=True):
        svc, p = self.svc, self.p
        if loading:
            p.msg(Msg.SET_TEMP)
            p.set_display(Mode.LOADING)
            time.sleep(1.5)
        net, slots = hwmon.list_layout(svc.hwmon_names("list"), svc.conf["hwmon_style"])
        p.msg(Msg.last_hwmon(Mode.HWMON))        # the panel's Hardware Monitor button opens this
        p.set_display(Mode.HWMON_NETWORK, net, sub=2)
        p.set_display(Mode.HWMON, slots, sub=2)
        svc.list_active = True
        svc.push_hw_values()
        return True


class LayoutScreen(DynamicScreen):
    """A user-defined screen from /etc/hmid/layouts/<name>.json (see docs/LAYOUTS.md)."""

    def __init__(self, svc, name):
        super().__init__(svc)
        from ..layouts import Layout
        self.layout = Layout(name, log=svc.log)
        self.name = "layout:" + self.layout.name

    @property
    def interval(self):
        return self.layout.refresh_seconds(self.svc.conf["stats_interval"])

    def render(self, sample):
        return self.svc.layout_renderer.render(self.layout, sample)


def make_screen(svc, name: str) -> Screen:
    if name.startswith("layout:"):
        return LayoutScreen(svc, name)
    if name == "hwmon":
        return MultiMonitorScreen(svc) if svc.conf["hwmon_mode"] == "multi" else ListMonitorScreen(svc)
    return {"stats": StatsScreen, "clock": ClockScreen, "menu": MenuScreen}.get(name, ClockScreen)(svc)
