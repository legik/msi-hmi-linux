# Contributing

## Setup

```sh
git clone https://github.com/legik/msi-hmi-linux && cd msi-hmi-linux
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q && ruff check src tests
```

To run your checkout against the panel, stop the installed service first, then run it
from the virtualenv:

```sh
sudo systemctl stop hmid
sudo .venv/bin/hmid
```

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first. It explains where things go
and how to add a screen, sensor or action.

## Pull requests

- Keep the tests passing, and add a test for new behaviour. The `FakeTransport` in
  `tests/conftest.py` lets you test panel sequences without hardware.
- If you change a sequence the panel sees, describe how you tested it on real hardware.
- Update `docs/` and `CHANGELOG.md` for anything users notice.

## Protocol research rules

- Document behaviour, not MSI's code. Describe what goes over the wire in
  `docs/PROTOCOL.md`; never copy decompiled code, MSI's images, videos or fonts.
- Never commit captures (`.pcapng`), replays or files extracted from MSI's software.
  `.gitignore` blocks the common ones.
- **Never implement firmware update, rescue mode or settings-save commands, and don't widen
  file delete.** A wrong write can brick the panel, and nobody can repair it. The one delete
  hmid sends (slot 7's still pictures before an animation, as MSI does) is whitelisted in
  `protocol.delete_payload`.
- New commands should be ones MSI Center actually sends. Test each new one alone, with
  the service stopped, before building on it.

Capturing on Windows: use Wireshark with USBPcap while MSI Center does the action, then
decode with `tools/hmicap.py capture.pcapng timeline`. On Linux:
`modprobe usbmon` and capture the panel's bus in Wireshark.

## Reporting bugs

Please include:
- `journalctl -u hmid -b`
- `sudo hmictl status`
- `lsusb | grep 1462`
- what the panel was showing at the time
