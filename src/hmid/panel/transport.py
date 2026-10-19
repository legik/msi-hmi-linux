"""USB transport for the panel (pyusb / libusb).

Linux's hidraw driver sends output reports over the interrupt OUT endpoint, which is
the panel's file-data pipe - that freezes the firmware. So the kernel HID driver is
detached and the same USB requests as MSI Center are made directly.
"""
from __future__ import annotations

from . import protocol as P


class PanelError(Exception):
    """Any USB failure talking to the panel. errno 110 = timeout (firmware hung)."""

    def __init__(self, msg, errno=None):
        super().__init__(msg)
        self.errno = errno


class PanelNotFound(PanelError):
    pass


def _usb():
    try:
        import usb.core
        import usb.util
    except ImportError as e:            # pragma: no cover - packaging problem
        raise PanelError("pyusb is not installed (python-pyusb)") from e
    return usb


def present() -> bool:
    usb = _usb()
    return usb.core.find(idVendor=P.VID, idProduct=P.PID) is not None


class UsbTransport:
    def __init__(self):
        usb = _usb()
        self._usb = usb
        self.dev = usb.core.find(idVendor=P.VID, idProduct=P.PID)
        if self.dev is None:
            raise PanelNotFound("HMI panel 1462:922c not found (it may be resetting)")
        self.detached = False
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
                self.detached = True
        except usb.core.USBError:
            pass
        self._wrap(usb.util.claim_interface, self.dev, 0)

    def _wrap(self, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except self._usb.core.USBTimeoutError:
            raise
        except self._usb.core.USBError as e:
            raise PanelError(str(e), getattr(e, "errno", None)) from e

    def control_out(self, packet: bytes):
        self._ctrl(*P.CTRL_OUT, packet)

    def control_in(self) -> bytes:
        return bytes(self._ctrl(*P.CTRL_IN, P.PACKET))

    def _ctrl(self, rt, req, val, data):
        try:
            return self._wrap(self.dev.ctrl_transfer, rt, req, val, 0, data, timeout=1000)
        except self._usb.core.USBTimeoutError as e:
            raise PanelError(str(e), 110) from e

    def read_event(self, timeout: float) -> bytes | None:
        try:
            return bytes(self._wrap(self.dev.read, P.EP_EVENTS_IN, P.PACKET, timeout=max(1, int(timeout * 1000))))
        except self._usb.core.USBTimeoutError:
            return None

    def write_data(self, packet: bytes):
        try:
            self._wrap(self.dev.write, P.EP_DATA_OUT, packet, timeout=3000)
        except self._usb.core.USBTimeoutError as e:
            raise PanelError(str(e), 110) from e

    def close(self):
        usb = self._usb
        try:
            usb.util.release_interface(self.dev, 0)
            if self.detached:
                self.dev.attach_kernel_driver(0)
        except usb.core.USBError:
            pass
        usb.util.dispose_resources(self.dev)
