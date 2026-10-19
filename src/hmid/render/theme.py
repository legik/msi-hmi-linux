"""Colour themes. A Theme carries every colour the renderer uses; named schemes switch the
whole panel (built-in screens and layouts) with one setting: "theme": "nord"."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass


def rgba(h: str, a: int = 255) -> tuple[int, int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a


# "Tiffany" palette (the original look; also the field defaults below)
BG_CANVAS = rgba("050707")
BG_GLOW = rgba("0A2E2C")
CARD_BG = (14, 20, 20, 217)            # rgba(14,20,20,0.85)
CARD_BORDER = (129, 216, 208, 64)
TIFFANY = rgba("81D8D0")
TIFFANY_DARK = rgba("0ABAB5")
TEXT_PRIMARY = rgba("FFFFFF")
TEXT_SECONDARY = rgba("8E9E9E")
BAR_TRACK = rgba("1E2424")
WARN = rgba("EAD07C")
CRIT = rgba("F56565")
TEMP_NORMAL = rgba("E2E8F0")


@dataclass(frozen=True)
class Theme:
    header: tuple                      # card titles
    normal_text: tuple                 # big values
    bar: tuple                         # bar gradient (start, end)
    primary: tuple = TEXT_PRIMARY      # plain text
    secondary: tuple = TEXT_SECONDARY  # units, labels, meta
    warn: tuple = WARN
    crit: tuple = CRIT
    accent: tuple = TIFFANY            # divider, graphs
    accent_dark: tuple = TIFFANY_DARK
    card_bg: tuple = CARD_BG
    card_border: tuple = CARD_BORDER
    track: tuple = BAR_TRACK
    canvas: tuple = BG_CANVAS
    glow: tuple | None = BG_GLOW       # radial glow at the top (None = flat canvas)
    temp_normal: tuple = TEMP_NORMAL

    def state_color(self, state, normal=None):
        if state == "crit":
            return self.crit
        if state == "warn":
            return self.warn
        return self.normal_text if normal is None else normal


# names usable in a layout's "colors" (and as colour names in widgets)
TOKENS = ("header", "value", "text", "secondary", "warn", "crit", "accent", "accent_dark",
          "card", "card_border", "track", "canvas", "glow", "bar_start", "bar_end")


def parse(spec) -> tuple | None:
    """'#RRGGBB' / '#RRGGBBAA' -> rgba, or None."""
    s = str(spec).lstrip("#")
    if len(s) not in (6, 8):
        return None
    try:
        return rgba(s[:6], int(s[6:8], 16) if len(s) == 8 else 255)
    except ValueError:
        return None


def with_colors(base: Theme, colors: dict) -> Theme:
    """Theme with "colors" overrides ("glow": null switches the glow off)."""
    field = {"value": "normal_text", "text": "primary", "card": "card_bg"}
    changes, bar = {}, list(base.bar)
    for k, v in (colors or {}).items():
        if k == "glow" and v is None:
            changes["glow"] = None
            continue
        c = parse(v)
        if c is None:
            continue
        if k == "bar_start":
            bar[0] = c
        elif k == "bar_end":
            bar[1] = c
        elif k in TOKENS:
            changes[field.get(k, k)] = c
    changes["bar"] = tuple(bar)
    return dataclasses.replace(base, **changes)


def _scheme(canvas, card, border, track, header, value, secondary, warn, crit, accent, accent_dark,
            bar_start, bar_end, text=None, glow=None):
    return {"canvas": canvas, "glow": glow, "card": card, "card_border": border, "track": track,
            "header": header, "value": value, "text": text or value, "secondary": secondary,
            "warn": warn, "crit": crit, "accent": accent, "accent_dark": accent_dark,
            "bar_start": bar_start, "bar_end": bar_end}


# Popular dark schemes, mapped onto the panel's colour roles. Secondary text is lifted a
# little where a scheme's own "comment" colour is too dark to read on the small panel.
SCHEMES: dict[str, dict] = {
    "graphite":         _scheme("#0b0c0e", "#16181c", "#2a2d33", "#24272c", "#9aa0a8", "#f2f3f5", "#7d838b",
                                "#f0b429", "#ef4444", "#c9ced6", "#6b7280", "#8b929b", "#e5e7eb"),
    "catppuccin-mocha": _scheme("#11111b", "#1e1e2e", "#313244", "#313244", "#cba6f7", "#cdd6f4", "#9399b2",
                                "#f9e2af", "#f38ba8", "#89b4fa", "#74c7ec", "#89b4fa", "#cba6f7"),
    "nord":             _scheme("#242933", "#2e3440", "#3b4252", "#3b4252", "#88c0d0", "#eceff4", "#8a93a5",
                                "#ebcb8b", "#bf616a", "#88c0d0", "#5e81ac", "#5e81ac", "#88c0d0"),
    "dracula":          _scheme("#1e1f29", "#282a36", "#44475a", "#44475a", "#bd93f9", "#f8f8f2", "#8a92b8",
                                "#f1fa8c", "#ff5555", "#ff79c6", "#bd93f9", "#bd93f9", "#ff79c6"),
    "tokyo-night":      _scheme("#16161e", "#1a1b26", "#292e42", "#292e42", "#7aa2f7", "#c0caf5", "#737aa2",
                                "#e0af68", "#f7768e", "#7dcfff", "#7aa2f7", "#7aa2f7", "#bb9af7"),
    "one-dark":         _scheme("#1e2127", "#282c34", "#3e4451", "#3e4451", "#61afef", "#dcdfe4", "#8b929e",
                                "#e5c07b", "#e06c75", "#61afef", "#c678dd", "#61afef", "#56b6c2"),
    "github-dark":      _scheme("#0d1117", "#161b22", "#30363d", "#21262d", "#58a6ff", "#e6edf3", "#8b949e",
                                "#d29922", "#f85149", "#58a6ff", "#1f6feb", "#1f6feb", "#58a6ff"),
    "rose-pine":        _scheme("#191724", "#1f1d2e", "#26233a", "#26233a", "#c4a7e7", "#e0def4", "#908caa",
                                "#f6c177", "#eb6f92", "#9ccfd8", "#31748f", "#31748f", "#9ccfd8"),
    "everforest":       _scheme("#232a2e", "#2d353b", "#3d484d", "#3d484d", "#a7c080", "#d3c6aa", "#9da9a0",
                                "#dbbc7f", "#e67e80", "#83c092", "#7fbbb3", "#83c092", "#a7c080"),
    "kanagawa":         _scheme("#16161d", "#1f1f28", "#2a2a37", "#2a2a37", "#7e9cd8", "#dcd7ba", "#8a8980",
                                "#e6c384", "#e46876", "#7fb4ca", "#957fb8", "#7e9cd8", "#7fb4ca"),
    "solarized-dark":   _scheme("#00212b", "#002b36", "#073642", "#073642", "#268bd2", "#eee8d5", "#93a1a1",
                                "#b58900", "#dc322f", "#2aa198", "#268bd2", "#268bd2", "#2aa198"),
    "monokai":          _scheme("#1e1f1c", "#272822", "#3e3d32", "#3e3d32", "#66d9ef", "#f8f8f2", "#a59f85",
                                "#e6db74", "#f92672", "#a6e22e", "#66d9ef", "#a6e22e", "#66d9ef"),
    "gruvbox":          _scheme("#1d2021", "#282828", "#3c3836", "#3c3836", "#8ec07c", "#ebdbb2", "#a89984",
                                "#fabd2f", "#fb4934", "#8ec07c", "#689d6a", "#689d6a", "#8ec07c"),
    "tiffany":          {},                                          # the original look (field defaults)
    "tiffany-platinum": {"header": "#B0BEC5", "value": "#81D8D0", "bar_start": "#81D8D0", "bar_end": "#81D8D0"},
}
DEFAULT = "monokai"
LEGACY = {1: "tiffany-platinum", 2: "tiffany", 3: "gruvbox"}      # old numeric stats_theme

_BASE = Theme(header=TIFFANY, normal_text=rgba("E6F2F2"), bar=(TIFFANY_DARK, TIFFANY))


def _build(name: str) -> Theme:
    t = with_colors(_BASE, SCHEMES[name])
    # temperatures in normal range use the plain text colour, so the built-in stats screen
    # and the classic layout look identical in every theme
    return dataclasses.replace(t, temp_normal=t.primary)


THEMES: dict[str, Theme] = {name: _build(name) for name in SCHEMES}
NAMES = tuple(SCHEMES)


def name_of(theme) -> str:
    """'nord' / 3 / '3' -> a valid scheme name (unknown -> the default)."""
    if isinstance(theme, str) and theme.isdigit():
        theme = int(theme)
    if isinstance(theme, int) and not isinstance(theme, bool):
        return LEGACY.get(theme, DEFAULT)
    return theme if theme in THEMES else DEFAULT


def get(theme) -> Theme:
    return THEMES[name_of(theme)]


def step(current: str, delta: int) -> str:
    """Next / previous theme name, wrapping around."""
    i = NAMES.index(name_of(current))
    return NAMES[(i + delta) % len(NAMES)]
