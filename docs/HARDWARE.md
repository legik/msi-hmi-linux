# Hardware

## Supported

| Device | USB ID | Status |
|---|---|---|
| MSI HMI 2.0 panel (MEG Trident X2) | `1462:922c` | supported |
| Mystic Light controller (MEG Trident X2) | `1462:931b` | supported |

Other MSI desktops with the same panel probably work too. Run `lsusb | grep 1462` and
open an issue with the output if yours is different.

## Fans and VRM temperature

MSI boards use a Nuvoton **NCT6687** sensor chip. Linux includes a read-only driver
for it that has to be forced:

```sh
sudo modprobe nct6683 force=1
sensors nct6687-isa-0a20          # fan1..fan4, temperatures
```

To load it at every boot:

```sh
echo "options nct6683 force=1" | sudo tee /etc/modprobe.d/nct6683.conf
echo "nct6683" | sudo tee /etc/modules-load.d/nct6683.conf
```

As an alternative, the out-of-tree driver `nct6687d` (AUR: `nct6687d-dkms-git`) also works.

MSI's header order is fan1 = CPU fan, fan2 = pump, fan3+ = system fans; the VRM (MOS)
temperature is the chip's 3rd temperature (`Thermistor 15` on the Trident X2). If a
reading lands in the wrong place, watch `watch -n1 sensors nct6687-isa-0a20` under load
and set `fan_map` / `vrm_temp_label` (see [CONFIGURATION.md](CONFIGURATION.md#sensors)).

## GPU

- **NVIDIA**: read through NVML, the NVIDIA driver's own library (`libnvidia-ml.so`).
  `nvidia-smi` is built on it, but it starts a new process for every reading; NVML calls
  take well under a millisecond. When the library can't be loaded, hmid falls back to
  `nvidia-smi`. The log says which one is used (`GPU: … (NVML)`). The driver reports
  fan speed in percent only, so the GPU fan RPM screen stays hidden.
- **AMD**: read through amdgpu's sysfs files.

## RAM clock and CPU power

The RAM clock comes from `dmidecode`, and CPU package power from Intel RAPL. Both need
root, which the service has.

## FPS (MangoHud)

Linux has no system-wide frame counter, so FPS comes from MangoHud's log. MangoHud
works with Vulkan and OpenGL games, including Windows games running through Proton.
Put this in `~/.config/MangoHud/MangoHud.conf`:

```
fps_only
alpha=0.0
background_alpha=0.0
autostart_log=1
log_interval=1000
output_folder=/tmp/hmi-fps
```

The first three lines keep MangoHud's overlay running but fully transparent, so the FPS
appears only on the panel. Don't use `no_display` to hide the overlay: in some MangoHud
versions it also stops the logging, and then no game is detected.
Launch games with MangoHud: in Steam, set the launch option `mangohud %command%`, or put
`MANGOHUD=1` in `/etc/environment` for every game.

hmid reads the newest log row. A game counts as closed when its log stops changing
for 4 s. To switch the panel to a gaming screen automatically while you play, set
`"game_screen": "layout:gaming"` in `/etc/hmid.json`. Logs are never deleted by hmid; `/tmp` is cleared at reboot.

Flatpak Steam has its own `/tmp`. Point `output_folder` and `mangohud_folder` at a folder
in your home directory instead.

## Mystic Light

Effects are written straight to the controller over HID. To check what the controller
is currently showing, run `sudo hmictl lights-state`. OpenRGB does not detect this
controller.
