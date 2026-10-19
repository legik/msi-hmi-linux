# HMI 2.0 panel protocol

This page documents the panel's protocol as far as it is known. It was worked out by
observing the USB traffic between the panel and MSI Center on Windows, then confirmed
on Linux. Anything marked *unconfirmed* has been seen but not tested.

The protocol code lives in `src/hmid/panel/protocol.py`, which has no I/O, and
`src/hmid/panel/device.py`.

## Device

| | |
|---|---|
| USB ID | `1462:922c`, product "HMI2.0(MS-B922C)" |
| Display | 480 × 800 portrait, capacitive touch |
| Interface 0 | HID; interrupt IN `0x81` (64 bytes), interrupt OUT `0x02` (1024 bytes) |

Until a host completes the handshake, the panel shows a loading animation, and its
watchdog keeps resetting it.

## Transport

| Direction | How | Format |
|---|---|---|
| command | control `SET_REPORT`: bmRequestType `0x21`, bRequest `0x09`, wValue `0x0201`, 64 bytes | `01 6B 5A <cmd> 00 <u32 LE length> <payload ≤ 55>` |
| reply | control `GET_REPORT`: `0xA1`, `0x01`, wValue `0x0101`, 64 bytes | `6B 5A <cmd+1> 00 <u32 LE length> <data>`, sometimes shifted one byte to the right |
| file data | interrupt OUT `0x02` | 1024-byte packets: `02` + 1023 data bytes (the last one zero-padded) |
| events | interrupt IN `0x81` | `01 <counter> <item> <flag> <X u16 LE> <Y u16 LE>` |

> **Important:** Linux's `hidraw` sends output reports over the interrupt OUT endpoint,
> which is the panel's file-data pipe. Commands sent that way freeze the firmware. Use
> control transfers as above. hmid detaches the kernel HID driver and uses libusb.

The event pipe should be drained continuously, as MSI Center does.

## Commands

| cmd | Name | Payload | Reply |
|---|---|---|---|
| 16 | GetDeviceID | `00 00 00 00` | 17: answers the preceding `55AAGET…` text command |
| 20 | GetDeviceInfo | `00 00 00 00` | 21: byte 4 = brightness; byte 12 alternates `00`/`f0` |
| 24 | SetBacklight | u32 0–100 | – |
| 32 | FileNode | u32 size + ASCII file name (≤ 32) | – |
| 34 | StartData | length field = file size, payload zeros | – |
| 38 | EndData | zeros, length 0 | – |
| 42 | DeleteFile | ASCII file name padded to 32, length 32 | – (hmid only deletes slot-7 still pictures, see below) |
| 48 | HW values A | 16 × u16 (values 0–15) | – |
| 60 | HW values B | 11 × u16 (values 16–26), padded to 32 bytes, length 32 | – |
| 54 | HostTime | u32 format (1 = 24 h, 0 = 12 h), f32 0, u32 local epoch seconds | – |
| 56 | Weather | *format unknown* | – |
| 58 | HostMessage | ASCII text command, padded to 55, length 55 | – |
| 80 | SetDisplay | `mode, sub, n, data[n]`, padded to 19, length 19 | – |
| 82 | GetDisplay | `mode` | 83: byte 0 = 1 if that screen is showing; on mode 25, byte 3 = 1 when ready for an overlay |

MSI's software also contains firmware-update, rescue, file-delete and settings-save
commands. They are intentionally not documented or used here.

## Text commands (cmd 58)

| Text | Meaning |
|---|---|
| `55AAGETLCID5AA5` then cmd 16 | language ID (`09 04 00 00`) |
| `55AAGETNANDFATVERSION5AA5` then cmd 16 | firmware/storage version |
| `55AASETTEMP05AA5` | sent before every screen switch |
| `55AASETLASTHWM255AA5` / `55AASETLASTHWM005AA5` | which screen the panel's own *Hardware Monitor* button opens: 25 or 0 |
| `55AAMODESTATUS08_15AA5` | "MSI Center present". **Never send `_0`**: the panel then only shows "install MSI Center" |
| `55AAMODESTATUS13_<0/1>5AA5` | show the User Scenario menu |
| `55AAMODESTATUS17_<0/1>5AA5` | show the Mystic Light menu |
| `55AAMODESTATUS09/18/19_…`, `55AASCREENSTATUS…` | other handshake flags, sent as MSI does (see `protocol.handshake`) |
| `55AAMEMORY4_<MB 5 digits>5AA5` | result for the Free Up Memory page; `MEMORY5` when ≥ 10000 MB |

## Display modes (SetDisplay / GetDisplay)

| Mode | Screen | SetDisplay data |
|---|---|---|
| 0 | Hardware monitor, panel-drawn | sub = 2, 16 bytes: style 1–3 per sensor screen, 0 = hidden |
| 1 | Picture | 8 bytes, one-hot slot: 0–5 = the panel's built-in pictures, 7 = user picture |
| 5 | Clock | 10 bytes, one-hot clock face |
| 7 | Hardware monitor network page | sub = 2, 16 bytes: `[upload style, download style, 0…]` |
| 8 | Main menu | `01` |
| 11–19 | Function pages: 11 Nahimic, 12 volume, 13 user scenario, 14 music, 15 free memory, 16 countdown, 17 Mystic Light, 18 gaming mode, 19 monitor OSD | opened from the panel's menu |
| 20 | Sleep (S3) | `01 01` |
| 21 | Hibernate (S4) | `01` |
| 22 | Shutdown (S5) | `01` |
| 23 | Restart | `01` |
| 24 | Loading | `01` |
| 25 | Dynamic: background video plus PNG overlay | `01` |
| 26 | Power menu | |

Modes 2–4, 6, 9 and 10 have never been seen. MSI also uploads `M10-S1-O-R00NN.jpg` files
(probably for the weather screen) and `HMI_FW_Setting.ini` (settings, not used by hmid).

## File upload

Every upload runs `FileNode(size, name)` → `StartData(len = size)` → data packets on `0x02`
→ `EndData`. The panel picks the file's role from its name:

| Name | Use |
|---|---|
| `M25-S0-V-R0.mp4` | dynamic-screen background video: H.264 Constrained Baseline, 480×800, yuv420p |
| `M25-S0-O-R000.png` | dynamic-screen overlay, 480×800 PNG |
| `M0-S0-V-R6.png`, `M0-S1-O-R000…049.png` | custom images for hardware-monitor style 4 (*unconfirmed*) |
| `M1-S7-O-R0.png` (`.jpg` `.bmp` `.gif`) | user picture in slot 7; `R1` instead of `R0` for 90/270° rotation. PNG works; a JPEG upload was not shown |
| `M1-S7-V-R0.avi` | animated user picture: H.264 Constrained Baseline, level 3.0, no B-frames, 480×800 yuv420p, in AVI; loops |

## Picture mode (1)

A still picture: loading (24), upload `M1-S7-O-R0.png`, then SetDisplay 1 with slot 7
selected. Built-in pictures: SetDisplay 1 with slot 0–5, no upload.

Animated (MSI converts GIFs to video): `55AASETTEMP05AA5`, loading, **DeleteFile** for
`M1-S7-O-R0.png/.jpg/.bmp/.gif` (1 s apart; a still picture in the slot is shown instead
of the video), upload `M1-S7-V-R0.avi`, then SetDisplay 1 slot 7.

## Dynamic screen (25)

MSI's sequence, which must be followed exactly:

1. `55AASETTEMP05AA5`, then SetDisplay 24 (loading); wait ~1.5 s
2. upload `M25-S0-V-R0.mp4`; wait ~1.5 s
3. `55AASETLASTHWM255AA5`, then SetDisplay 25
4. for every overlay: GetDeviceInfo, GetDisplay(25), then upload `M25-S0-O-R000.png`,
   **only if the reply has byte 0 = 1 and byte 3 = 1**

Things that freeze the firmware:
- uploading while another page is showing, such as the countdown alarm
- switching back to 25 without re-uploading the video, followed by an overlay upload
- skipping the queries in step 4: the upload is then ignored

## Panel-drawn hardware monitor (0 + 7)

To open it: `55AASETTEMP05AA5`, loading, `55AASETLASTHWM005AA5`, SetDisplay 7 (network
styles), then SetDisplay 0 (per-sensor styles). Then send cmd 48 + 60 about once a second
with these 27 u16 values:

| # | Value | # | Value |
|---|---|---|---|
| 0 | CPU clock / 100 (MHz) | 9 | RAM clock (MHz) |
| 1 | CPU load % | 10 | FPS |
| 2 | CPU temperature °C | 11 | VRM (MOS) temperature °C |
| 3 | CPU fan RPM | 12 | CPU fan % |
| 4 | pump RPM | 13 | GPU fan % |
| 5 | GPU clock (MHz) | 14 | system fan RPM |
| 6 | GPU load % | 15 | system fan % |
| 7 | GPU temperature °C | 16 | upload |
| 8 | GPU fan RPM | 17 | download |

Network values are KB/s × 10. Flag `0x4000` means MB/s and `0x8000` GB/s. Values 18–26
are sent as 0.

MSI Center's "Multi" switch doesn't use this screen at all. MSI draws all sensors into one
picture and shows it on the dynamic screen instead, which is what hmid's `multi` mode does.

## Events (EP 0x81)

`01 <counter> <item> <flag> <x> <y>`: `item` is the panel's current menu function
(MSI's `Enum_TouchModeIndex`, listed in [CONFIGURATION.md](CONFIGURATION.md#panel-items)).
It changes when a menu button is tapped, and usually drops to 0 when a finger touches
down. `flag` is 1 while a finger is down.

- When the countdown reaches zero, the panel switches to its alarm page and reports item 70.
  Stop reports item 71.
- The panel leaves its function pages by itself. The host only needs to notice, by
  polling GetDisplay, that its own screen is back.

## Keepalive

MSI Center sends GetDisplay every ~2 s and syncs the time every 60 s. If the panel stops
answering, its firmware has hung, and its watchdog restarts it, usually within 40 s.

## Mystic Light controller (1462:931b)

This is a separate HID device. It takes one 185-byte feature report, ID `0x52`. Read it
with `HIDIOCGFEATURE`, change it, then write it with `HIDIOCSFEATURE`.

- Basic-effect zones have effect bytes at 11, 21, 31, 42 and 53. Colour 1 is at offset
  +1..3 and colour 2 at +5..7.
- The animated zone's effect byte is at 74, and byte 82 is its control byte: `00` for
  basic effects, `0f` or `8f` for animated ones.
- Byte 184 (save to flash) is always written as 0.
- Effect codes: 01 steady, 02 breathing, 03 flashing, 04 double flashing, 05 lightning,
  07 meteor, 0a–0e music effects, 0f colour ring, 16 colour shift, 18 marquee,
  1a rainbow, 1b visor, 24 stack, 26 MSI default.

The exact bytes for every panel item are in `src/hmid/lighting/mystic.py`.
