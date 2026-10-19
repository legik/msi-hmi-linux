# Configuration

Settings live in `/etc/hmid.json`. Every key is optional, and unknown or invalid keys are
logged and ignored.

The easy way to change them is `hmictl`. It checks the value, saves it, keeps everything
else in the file as you wrote it, and applies the change at once (the few settings read
only at start say so):

```sh
sudo hmictl get                                   # every setting; "(default)" = not in the file
sudo hmictl set debug_events true
sudo hmictl set proxy socks5h://127.0.0.1:1080
sudo hmictl set game_screen layout:gaming
sudo hmictl set touch_actions.250 builtin:theme_next     # one entry of touch_actions, light_colors, fan_map
sudo hmictl set hwmon_sensors '["cpu_load", "gpu_temp", "fps"]'
sudo hmictl unset proxy                           # back to the default
```

Values are JSON when they look like it (`true`, `50`, `null`, `[…]`), otherwise text.
Choices made while running (`screen`, `theme`, `brightness`, `hwmon_mode`, from `hmictl` or
the panel) are kept in `/var/lib/hmid/state.json` and win over this file; `hmictl unset`
removes them from both.
Tab completes setting names and their values. After editing the file by hand, run
`sudo systemctl restart hmid`.

## Panel

| Key | Default | |
|---|---|---|
| `screen` | `"stats"` | default screen: `stats`, `hwmon`, `clock`, `menu`, or `layout:<name>` for your own screen from `/etc/hmid/layouts/<name>.json` ([LAYOUTS.md](LAYOUTS.md)) |
| `brightness` | `50` | 0–100 |
| `sleep_backlight_off` | `true` | backlight off while the PC sleeps |
| `clock_style` | `0` | panel clock face 0–9 |
| `clock_24h` | `true` | |
| `menu_mystic_light` | `true` | show the panel's Mystic Light menu |
| `menu_user_scenario` | `false` | show the panel's User Scenario menu |

## Stats screen and multi monitor

| Key | Default | |
|---|---|---|
| `stats_interval` | `3` | seconds between redraws |
| `theme` | `"monokai"` | colour scheme for every screen; see [Themes](#themes) |
| `background` | `null` | path to your own background MP4 (readable by the `hmid` user, e.g. in `/etc/hmid/`); make one with `tools/make_background.py` |

## Themes

One colour scheme for the whole panel: the built-in stats screen, multi mode and every
layout. Switch it with `sudo hmictl theme <name>`, which applies at once and is saved.
`sudo hmictl theme next` cycles through them, and `sudo hmictl themes` lists them.

`graphite` · `catppuccin-mocha` · `nord` · `dracula` · `tokyo-night` · `one-dark` ·
`github-dark` · `rose-pine` · `everforest` · `kanagawa` · `solarized-dark` · `monokai` ·
`gruvbox` · `tiffany` · `tiffany-platinum`

![every theme](images/themes.png)

To compare them with your own readings: `hmictl preview-themes /tmp/themes.png` (or
`… /tmp/themes.png gaming` for a layout). To cycle themes from the panel, map one of its
user shortcut buttons to it: `"touch_actions": {"250": "builtin:theme_next"}` (the User
Scenario buttons 40–45 switch power profiles by default). The new colours appear when the
panel closes its menu (drawing pauses while the menu is open). The old
numeric `stats_theme` setting is converted automatically.

## Hardware monitor

| Key | Default | |
|---|---|---|
| `hwmon_mode` | `"list"` | `list`: drawn by the panel, one sensor per screen; `multi`: up to 12 tiles per page |
| `hwmon_style` | `2` | list mode: the panel's built-in style 1–3 |
| `hwmon_sensors` | `null` | sensor names in display order. `null` shows every available sensor in list mode, and the set below in multi mode |
| `hwmon_auto_hide` | `true` | leave out sensors this PC has no reading for |
| `hwmon_page_seconds` | `6` | multi mode with more than 12 sensors: seconds per page |

Sensor names (`sudo hmictl sensors` shows current readings):

| | | |
|---|---|---|
| `cpu_load` `cpu_temp` `cpu_clock` `cpu_power`¹ | `gpu_load` `gpu_temp` `gpu_clock` `gpu_power`¹ | `ram_used`¹ `ram_clock` |
| `cpu_fan` `cpu_fan_pct` `pump` | `gpu_fan` `gpu_fan_pct` | `sys_fan` `sys_fan_pct` |
| `vrm_temp` | `fps` (while gaming) | `upload` `download` |

¹ multi mode only; the panel-drawn monitor has no screen for these.

The default multi set is: `fps cpu_load cpu_temp cpu_clock cpu_fan gpu_load gpu_temp gpu_clock gpu_fan_pct ram_used download upload`.

## Sensors

| Key | Default | |
|---|---|---|
| `fan_map` | `null` | which header is which, e.g. `{"cpu_fan": "fan1", "pump": "fan2", "sys_fan": "fan4"}`. `null` uses MSI's order: fan1 CPU, fan2 pump, first spinning fan3+ |
| `vrm_temp_label` | `null` | label of the VRM temperature, e.g. `"Thermistor 15"`. `null` uses the chip's 3rd temperature |
| `mangohud_folder` | `"/tmp/hmi-fps"` | MangoHud's `output_folder` |
| `game_screen` | `null` | screen to show while a game runs, e.g. `"layout:gaming"`. The panel switches when MangoHud reports a game and goes back to `screen` 15 s after it ends. A screen you pick during a game stays. `null` = never switch |

## Lights

| Key | Default | |
|---|---|---|
| `light_on_start` | `92` | effect item applied when the service starts (92 = Rainbow); `null` keeps the current effect |
| `light_colors` | `{"82": "0ABAB5"}` | colour per effect item: 82 Steady, 83 Breathing, 84 Flashing, 85 Double flashing |

## Network

| Key | Default | |
|---|---|---|
| `proxy` | `null` | send the web requests of layouts (weather, creator counters, album covers…) through a proxy. `null` = direct |

```json
"proxy": "socks5h://127.0.0.1:1080"
```

| Address | |
|---|---|
| `socks5h://host:port` | SOCKS5; the proxy also resolves host names. Use this one if DNS is filtered too (Tor, ssh -D, most VPN clients) |
| `socks5://host:port` | SOCKS5; host names are resolved on this PC |
| `socks5h://user:password@host:port` | with a login (special characters in the password as `%40` for `@` etc.) |
| `http://host:port` | an ordinary HTTP proxy |

No extra package is needed. hmid ignores `http_proxy` / `all_proxy` from the environment:
this setting decides. A single layout source can override it with its own `"proxy"`, or
go direct with `"proxy": false` (see [LAYOUTS.md](LAYOUTS.md#sources-your-own-data)). Restart
the service after changing it. The log says at start `web requests: through socks5h://…` (or
`direct (no proxy set)`). With `"debug_events": true` it also logs one line per request, with
where it went and how it ended:

```
web GET https://i.scdn.co/image/ab67616d0000b273… via socks5h://127.0.0.1:1080 -> 200 image/jpeg 61 KB in 0.48 s
web GET https://api.met.no/weatherapi/… direct -> failed after 10.00 s: timed out
```

`sudo journalctl -u hmid -f | grep "web GET"` follows them live.
Commands in layouts (`curl` and the like) don't use this setting.

## Troubleshooting

| Key | Default | |
|---|---|---|
| `debug_events` | `false` | log every item/touch change the panel reports (for tap problems), and every web request with its proxy, result and time |

## Touch actions

`touch_actions` maps a panel item number to an action:

| Action | |
|---|---|
| `"user:<shell command>"` | run as the logged-in desktop user, e.g. `"user:steam"` |
| `"root:<shell command>"` | run as root |
| `"builtin:free_memory"` | drop the kernel's clean caches and show the freed MB |
| `"builtin:timer_alarm"` / `"builtin:timer_stop"` | countdown alarm |
| `"builtin:mystic"` | Mystic Light effect for items 80–100 |
| `"builtin:theme_next"` / `"builtin:theme_prev"` | next / previous colour theme |
| `"none"` | do nothing |

```json
"touch_actions": {"2": "user:steam", "3": "user:firefox", "242": "none"}
```

`root:` commands run as root (by hmid-helper, which reads them from this file itself), so
keep `/etc/hmid.json` writable by root only. `install.sh` makes it `root:hmid`, mode 640:
the service reads it but cannot change it.

### Panel items

| Item | Button | Default action |
|---|---|---|
| 1 | MSI Center shortcut | – |
| 2–6, 250–255 | user shortcuts 1–11 | – (map your own) |
| 10–14 | Nahimic presets | – |
| 20 / 21 / 22 | speaker volume up / down / mute | wpctl (pactl fallback) |
| 23–26 | speaker 25 / 50 / 75 / 100 % | wpctl |
| 27 / 28 / 29 | mic up / down / mute | wpctl |
| 30–33 | mic 25 / 50 / 75 / 100 % | wpctl |
| 40–45 | user scenarios | powerprofilesctl |
| 50 / 51 / 52 | music volume up / down / mute | wpctl |
| 53 / 54 / 55 | next / previous / play-pause | playerctl |
| 60 | Free Up Memory | builtin |
| 70 / 71 | countdown alarm / Stop | builtin |
| 80 | Mystic Light off | builtin |
| 81–100 | 81 default, 82 steady, 83 breathing, 84 flashing, 85 double flashing, 86 visor, 87 stack, 88 marquee, 89 CPU temperature, 90 meteor, 91 lightning, 92 rainbow, 93 colour ring, 94 colour shift, 95 random, 96 pop, 97 rap, 98 jazz, 99 play, 100 movie | builtin |
| 110 / 111 | gaming mode on / off | – |
| 240 / 241 / 242 | sleep / reboot / power off | systemctl |
