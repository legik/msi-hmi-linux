# Changelog

## 0.2.0

First structured release.

- Custom screens: JSON layouts in `/etc/hmid/layouts` with text, cards, bars, sensor
  tiles, graphs and images; data from commands, files and web APIs; hot reload; errors
  shown on the panel; `hmictl layout`, `layouts`, `check`, `preview <layout>`. Three
  examples are included (classic, gaming, creator).
- Layouts can recolour everything (`colors`), for example Gruvbox. Text can be
  transformed (`transform`) and given a baseline-aligned unit (`suffix`). Sensor tiles
  take custom bar ranges (`bar_min` / `bar_max` / `bar_rule` / `bar_color`) and 22 px
  inline units. Graphs can be clipped to a card's corners (`clip`), and cards can be
  border-only.
- New value `gpu_power_limit` (TDP). Game names also lose `.x86_64` / `.x86` / `.bin`.
- Weather layout (Open-Meteo, no key; data hourly, screen once a minute). Whole-JSON
  sources with paths (`weather.current.temperature_2m`) and filters (`wmo`, `wmo_icon`,
  `compass`, `uv_level`, `time`, `now`, `hour_index`). New: `icon` widget (drawn weather
  icons), graphs of list values (`series`, `marker`), and `min`/`warn`/`crit` thresholds
  on bars and text.
- `weather.json` now uses MET Norway (no key), because Open-Meteo is blocked on some
  networks; the Open-Meteo version is `weather-openmeteo.json`. New filters: `met_text`,
  `met_icon`, `feels`, `today`, `pluck()`, `first()`, `max`, `min`, `mul()`. The `time`
  filter converts zoned times to the PC's time zone.
- 15 named colour themes (default `monokai`; also graphite, catppuccin-mocha, nord, dracula,
  tokyo-night, one-dark, github-dark, rose-pine, everforest, kanagawa, solarized-dark,
  gruvbox, tiffany, tiffany-platinum) for the built-in screens and all layouts.
  `hmictl theme <name|next|prev>` switches at once and saves; `hmictl themes`;
  `hmictl preview-themes`. `theme` replaces the numeric `stats_theme` (migrated). Built-in
  layouts follow the theme; a layout can pin one with `"theme": "<name>"`.
- Picture mode works: `hmictl picture <file>` shows a still picture (uploaded as PNG; the
  earlier JPEG attempt was why nothing showed) or an animated GIF / video clip (converted
  with ffmpeg to H.264 AVI, as MSI Center does); `hmictl picture builtin 0-5` shows a
  built-in picture. The only files hmid ever deletes are slot 7's still pictures before an
  animation, exactly like MSI.
- Built-in layouts now ship inside hmid and update with it, with no copying. Files in
  `/etc/hmid/layouts` are yours and replace a built-in layout of the same name.
  `hmictl customize <name>` makes an editable copy, and `hmictl layouts` lists both kinds.
  `install.sh` removes unchanged copies left by earlier versions and keeps edited ones.
- Game screen: `"game_screen": "layout:gaming"` switches the panel to that screen while
  a game runs (MangoHud) and back 15 s after it ends. A screen picked by hand during a
  game is kept. `hmictl status` shows the detected game. The gaming layout's GPU power
  tile is now RAM.
- The built-in stats screen (and multi mode) is pixel-identical to `layout:classic` in every
  theme.
- Fixed: false taps. When the panel left a page by itself, its item change was taken for
  a tap (seen as an unwanted Mystic Light change). Menu buttons now only count while the
  panel's menu is open; on your own screen an item change just opens the menu. (The panel
  never sets its touch flag: a tap is the item jumping to the button, then back to 0
  about 2 s later.) New `debug_events` option logs every reported item.
- Eight example layouts with pictures in `examples/layouts`: minimal, thermals, graphs,
  network, system, markets, github, world-clock. `tools/layout_gallery.py`
  draws them (and any layout) with demo data for the docs.
- `creator.json` is now a creator dashboard without hardware readings: YouTube (subscribers,
  views, latest upload), Twitch (followers, live status and viewers, next stream), Bluesky,
  Mastodon and GitHub followers, and the latest Bluesky post.
- New built-in layout `now-playing`: the track playing in any MPRIS player (Spotify, browsers,
  mpv…): album cover, title, artist, album and progress. Needs only `playerctl`.
- Command sources can run as the logged-in desktop user with `"as": "user"` (for
  `playerctl`, `wpctl` and other programs that need your session).
- The log says why the GPU can't be read, e.g. `driver/library version mismatch: the NVIDIA
  driver was updated - reboot`, instead of silently showing no GPU values.
- A missing fan percentage shows `–` instead of `0 %`.
- hmid runs as its own user `hmid` with access to only its two USB devices (udev rule
  `70-hmid.rules`) and a hardened systemd unit. The few things that need root (power and
  shell-command buttons, the countdown alarm, layout commands, Free Up Memory, RAM clock,
  CPU power, USB port reset) are done by the new `hmid-helper` service, which looks up what
  to run in root-owned files itself. Choices made while running go to
  `/var/lib/hmid/state.json`; `/etc/hmid.json` is only read by the service. The control
  socket moved to `/run/hmid/control.sock`.
- `hmictl get`, `set <setting> <value>` and `unset <setting>` change any setting in
  `/etc/hmid.json`: checked before saving, the rest of the file kept, applied at once where
  possible (`touch_actions.250` style for single entries). Tab completes names and values.
- `hmictl status`, `themes`, `layouts`, `sensors`, `sources` and `where` print readable lines
  instead of JSON; `--json` gives the JSON for scripts. Commands missing their arguments
  show how to use them instead of "unknown command".
- Tab completion for `hmictl` in zsh and bash: commands, layout and theme names, Mystic Light
  effects, files. Installed by `install.sh` and the PKGBUILD.
- `hmictl sources` shows what the shown layout gets: its file, each source's value or error,
  and each picture's link and whether it loaded.
- Web requests of layouts (sources, album covers) can go through a proxy: `"proxy":
  "socks5h://127.0.0.1:1080"` in `/etc/hmid.json` (SOCKS5 with or without login, or an HTTP
  proxy; no extra package), and per source `"proxy"` or `"proxy": false`.
- New `ring` widget: circular progress.
- `image` widgets take a value as `path` (a file or a web link, loaded in the background,
  e.g. a player's album cover), and `fit` (`cover`, `contain`) and `radius` (rounded corners).
- Layout filters `line(n)` (several values from one command), `compact` (128K), `date` and
  `ago` ("3 h ago"); `when` can compare (`"ci.conclusion=success"`, `"change<0"`). Command
  output may be up to 2000 characters.
- `install.sh` no longer installs or upgrades system packages, which caused partial
  upgrades on Arch/Manjaro. It only checks the dependencies, needs no venv or pip, and
  keeps the old install until the new one is in place.

- Installable Python package with two commands: `hmid` (the service) and `hmictl`
  (control and diagnostic tools).
- Arch PKGBUILD, a generic `install.sh` with uninstall, systemd unit and sleep hook.
- Hardware monitor in both of MSI's modes: `list` (drawn by the panel) and `multi` (tiles).
- Board fans and VRM temperature from MSI's NCT6687 chip, with `fan_map` and `vrm_temp_label`.
- FPS from MangoHud while gaming, on the stats screen, in multi mode and in the panel's FPS screen.
- Configuration is validated. Settings from the script version are migrated
  (`hwmon_hide` and `hwmon_network` become `hwmon_sensors`).
- NVIDIA GPU readings come from NVML (the driver library, through `ctypes`) instead of
  starting `nvidia-smi` on every update; `nvidia-smi` is still the fallback.
- Fixed: sensor files were looked up wrongly when their path contained `_label`.
- Removed experimental options: `menu_timeout`, `fast_stats_return`,
  `memory_back_to_menu` and `hw_values`.
- New `hmictl` commands: `light`, `preview`, `lights-state`, `probe` and `watch`.
- Tests with a fake panel, and CI.

## 0.1

Script version in `/opt/hmi`: boot and sleep handling, stats screen, touch actions,
countdown alarm, Mystic Light.
