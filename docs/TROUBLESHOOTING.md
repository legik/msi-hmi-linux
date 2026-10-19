# Troubleshooting

Start with the log:

```sh
journalctl -u hmid -b --no-pager | tail -50
sudo hmictl status
```

**The panel only shows the MSI loading logo.** The service isn't talking to the panel.
Check `systemctl status hmid` and `lsusb | grep 1462:922c`. Only one program can use the
panel at a time, so stop anything else that has it open.

**The panel says "install MSI Center".** Something sent `55AAMODESTATUS08_0`. Restart
the service, which sends `_1` again: `sudo systemctl restart hmid`.

**The panel freezes or restarts.** The log shows "panel froze" or "stopped answering".
The firmware's watchdog restarts it, and hmid waits up to 40 s before resetting the USB
port. If it keeps happening, open an issue with the log and what was on screen.

**Stats don't update after using the panel menu.** The panel returns from its menu by
itself, and hmid resumes when the next keepalive sees the screen again (≤ 2 s). Overlays
are paused while the menu is open, which is intentional.

**Fans, pump or VRM temperature are missing.** Load the sensor driver; see
[HARDWARE.md](HARDWARE.md#fans-and-vrm-temperature). Then check with `sudo hmictl sensors`.

**The game isn't detected (no FPS, no switch to the game screen).** Run `sudo hmictl status`
while the game runs. `game  eldenring (144 fps)` means it is detected; then check
`game_screen` in `/etc/hmid.json`. `game  none` means MangoHud isn't logging; continue below.
The log shows `game detected: <name>` when a game starts.

**FPS doesn't show.** Run `ls -la /tmp/hmi-fps` while the game runs. If there's no
growing `.csv`, MangoHud isn't logging; check the config in
[HARDWARE.md](HARDWARE.md#fps-mangohud) and that the game starts with MangoHud.

**Touch buttons do nothing.** The log shows `tap: <name>` for every tap. If the tap is
there, run the action's command yourself as your user (e.g. `wpctl set-volume
@DEFAULT_AUDIO_SINK@ 0.5`). "no desktop session found" means no graphical login was
detected through `loginctl`.

**Something happens without a tap, or a tap is missed.** Menu buttons only count while
the panel's menu is open. While your screen is showing, an item change just means the menu
is opening (or the panel changed its item by itself, which it does when it leaves a page),
and the log says `panel menu opened (… - no action)`. If a real tap is missed or something
fires on its own, set `"debug_events": true` in `/etc/hmid.json`, restart the service,
reproduce it and send the log: it shows every item the panel reports.

**A web source fails ("timed out", "could not reach").** Check the address from this PC,
e.g. `curl -I https://api.met.no`. If the network blocks it, set a `proxy` in
`/etc/hmid.json` ([CONFIGURATION.md](CONFIGURATION.md#network)). Proxy problems are named
in the log: `SOCKS proxy rejected the user name or password`, `SOCKS proxy could not reach
api.met.no:443: host unreachable`, `connection refused` (nothing listens at the proxy's
address).

**No GPU values (`hmictl sensors` says "no reading").** `journalctl -u hmid -b | grep GPU`
says why. `Driver/library version mismatch` means the NVIDIA driver was updated and the old
one is still loaded: reboot (`nvidia-smi` fails the same way until then).

**"panel not found" or "Access denied" for USB in the log.** hmid runs as the user `hmid`
and gets the panel through the udev rule `/usr/lib/udev/rules.d/70-hmid.rules`. Check
`ls -l /dev/bus/usb/*/* | grep hmid` and run `sudo ./install.sh` again (it reloads the
rule), or reboot.

**A power, shell-command or alarm button, a layout command or Free Up Memory does nothing**
and the log says `hmid-helper is not running`: `sudo systemctl enable --now hmid-helper`.
`journalctl -u hmid-helper` shows what it ran.

**`hmictl` says permission denied.** The control socket is root-only, so use `sudo`.

**Testing a page without the panel:** `hmictl preview /tmp/p.png` (or `... multi`).

**Debugging the panel directly:** stop the service, then run
`sudo hmictl probe` and `sudo hmictl watch`.
