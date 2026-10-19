# Architecture

```
src/hmid/
├── panel/              talking to the display
│   ├── protocol.py     packet formats, commands, modes, text messages (pure, no I/O)
│   ├── transport.py    USB via pyusb; maps USB errors to PanelError
│   ├── device.py       Panel: the commands MSI Center uses (upload, set_display, ...)
│   └── recovery.py     USB port reset (last resort)
├── sensors/            reading the PC
│   ├── __init__.py     Sample (one typed snapshot) + Sensors facade + missing()
│   ├── cpu.py memory.py network.py
│   ├── gpu.py          NVIDIA via NVML (ctypes; nvidia-smi fallback), AMD via sysfs
│   ├── board.py        MSI NCT6687 fans and VRM temperature
│   └── fps.py          MangoHud live log
├── hwmon.py            hardware-monitor catalog: sensor table, MSI 27-value encoding, tile text
├── render/             drawing 480x800 overlays (Pillow)
│   ├── theme.py        colour themes: Theme roles + named schemes (graphite, nord, ...)
│   ├── draw.py         primitives: text, cards, bars, background
│   └── pages.py        Renderer.stats(), Renderer.multi()
├── actions/            what panel taps do
│   ├── items.py        panel item numbers (MSI Enum_TouchModeIndex)
│   ├── session.py      run commands as the desktop user
│   ├── builtins.py     FreeMemory, Alarm, Lights
│   └── __init__.py     Actions: item -> "user:" / "root:" / "builtin:" dispatch
├── layouts/            user-defined screens (JSON)
│   ├── __init__.py     Layout: load, validate, hot reload; trusted-file check
│   ├── values.py       named values + template formatter
│   ├── sources.py      command / file / http sources, refreshed in the background
│   └── draw.py         LayoutRenderer: widgets -> PNG
├── lighting/mystic.py  Mystic Light HID controller (pure apply_effect + device)
├── daemon/
│   ├── service.py      the service: session loop, keepalive, reader, recovery, control
│   ├── screens.py      Clock / Menu / Stats / MultiMonitor / ListMonitor screens
│   └── control.py      unix socket server + client
├── config.py           /etc/hmid.json and the state file: defaults, validation, migration, edits
├── privileged.py       the few root operations, through hmid-helper (or directly as root)
├── helper.py           hmid-helper: the small root process
├── cli.py              `hmid` and `hmictl` entry points
└── data/bg_default.mp4 built-in background video
```

The dependencies only point one way: `daemon` → `screens` → `render`/`hwmon` →
`sensors`; `daemon` → `panel`. Nothing below `daemon` knows about threads or the
socket, and `panel/protocol.py`, `hwmon.py` and `lighting/mystic.apply_effect` are pure
functions, which keeps them easy to test.

## Runtime

```
             ┌──────────── control socket (/run/hmid/control.sock) ◄── hmictl, sleep hook
             │
 Service ────┼── session loop (every 0.2 s)
             │     connect → handshake → screen.open()
             │     every 1 s       hw values           (list monitor)
             │     every N s       sample → render → upload overlay   (stats / multi)
             │     every 2 s       GetDisplay keepalive → check_dynamic / check_list
             │     every 60 s      time sync
             │     no replies / timeout → wait for the watchdog restart → port reset
             │
             ├── reader thread: drains EP 0x81, detects taps → Actions (thread per tap)
             └── lights thread: Mystic Light effect at start
```

All panel I/O happens under `Service.lock`.

## Privileges

hmid runs as its own user, `hmid`. It can use only its two USB devices (the panel and the
Mystic Light controller, by the udev rule `70-hmid.rules`) and read sensors, settings and
layouts. That is where nearly all the code is, including everything that reads outside
data: USB, web answers, pictures from players, layout files.

The few things that need root are done by **hmid-helper**, a small root service
(`helper.py`) with a socket only root and the `hmid` user may use. It does a fixed list
of operations (`privileged.OPS`) and never runs a command it is sent:

| Operation | What hmid sends | What the helper does |
|---|---|---|
| `action` | a panel item number | looks the action up in `/etc/hmid.json` itself; runs `root:` / `user:` commands and the countdown alarm |
| `source` | a layout file and a source name | checks the file is in the built-in folder or `/etc/hmid/layouts` and only root can change it, then runs that source's command |
| `drop-caches`, `ram-clock`, `cpu-energy`, `usb-cycle` | nothing | Free Up Memory, `dmidecode`, the RAPL power counter, the USB port reset |

So a bug in hmid can at worst trigger actions you have configured (like tapping the
panel), not run its own commands as root. hmid cannot write `/etc/hmid.json` (it holds
`root:` commands); choices made while running (screen, theme, brightness, monitor mode)
go to its own `/var/lib/hmid/state.json`, and `sudo hmictl set` edits `/etc/hmid.json`
itself and then tells the service to `reload`.

When hmid runs as root (older installs, development), `privileged.call` does the same
operations in-process, so nothing else changes.

### Who owns the screen

The panel runs its own menu. When a user taps it, the panel leaves our screen and later
comes back to it by itself. The service never forces it back; it tracks what's showing:

| Flag | Meaning | Set by |
|---|---|---|
| `dynamic_active` | our dynamic canvas (stats / multi) is up | `DynamicScreen.open` |
| `list_active` | the panel-drawn monitor is up | `ListMonitorScreen.open` |
| `menu_open` | someone is using the panel's menu | reader (touch / item change) |
| `showing_default` | not a screen picked on the panel itself | keepalive |
| `picked_dynamic` | the panel's own Hardware Monitor button opened screen 25 | keepalive |

Overlays are uploaded only when `overlay_wanted()`, and never while the menu is open or
the countdown alarm is ringing. Uploading over another page freezes the firmware.

## Extending

**A new screen**: most of the time a layout file is enough ([LAYOUTS.md](LAYOUTS.md)), and a
new widget type is a `w_<type>` method in `layouts/draw.py` plus an entry in
`layouts.WIDGETS`. For a screen that needs code: subclass `DynamicScreen`, implement
`render(sample) -> png bytes` (usually a new `Renderer` method), register it in
`screens.make_screen()`, and add the name to `config.SCREENS`. The service handles the
video, upload guard, keepalive and returns from the menu.

**A new sensor**: read it in `sensors/`, add a field to `Sample`, add an entry to
`hwmon.SENSORS` with `slot=None` (multi mode only), a text in `hwmon.readings()`, and a
rule in `Sensors.missing()`.

**A new touch action**: add a builtin in `actions/builtins.py` and register it in
`Actions.builtins`. Users can map any item to a shell command without code changes.

**A frontend (GUI)**: talk to `/run/hmid/control.sock` with the same commands as `hmictl`.
`status`, `sensors`, `themes`, `layouts`, `sources` and `where` return JSON; `hmictl` turns it
into readable lines (`hmid/pretty.py`) unless it is called with `--json`.

## Tests

`tests/conftest.py` has a `FakeTransport` that records every packet and answers queries
like the panel does. `tests/test_service.py` checks the exact command order on the
hardware paths (dynamic screen, list monitor, upload guard, return from the menu). These
sequences were each found the hard way, so keep those tests green when refactoring.

```sh
pip install -e ".[dev]"
pytest -q && ruff check src tests
```
