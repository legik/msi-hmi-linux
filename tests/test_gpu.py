"""NVML reader against a fake libnvidia-ml (no NVIDIA driver needed)."""
import ctypes

from hmid.sensors import gpu as G


class FakeNvml:
    """Mimics the libnvidia-ml functions hmid calls (return 0 = success)."""

    def __init__(self, fan_supported=True):
        self.fan_supported = fan_supported
        self.inits = 0
        self.lost = False

    def nvmlInit_v2(self):
        self.inits += 1
        self.lost = False
        return 0

    def nvmlDeviceGetHandleByIndex_v2(self, index, handle):
        handle.contents.value = 0x1234
        return 0

    def nvmlDeviceGetName(self, h, buf, size):
        ctypes.memmove(buf, b"NVIDIA GeForce RTX 4080\0", 24)
        return 0

    def nvmlDeviceGetUtilizationRates(self, h, p):
        if self.lost:
            return 15                                   # NVML_ERROR_GPU_IS_LOST
        p.contents.gpu, p.contents.memory = 37, 12
        return 0

    def nvmlDeviceGetTemperature(self, h, sensor, p):
        p.contents.value = 61
        return 0

    def nvmlDeviceGetMemoryInfo(self, h, p):
        p.contents.total, p.contents.used, p.contents.free = 16 * 2**30, 5 * 2**30, 11 * 2**30
        return 0

    def nvmlDeviceGetPowerUsage(self, h, p):
        p.contents.value = 281500                       # mW
        return 0

    def nvmlDeviceGetEnforcedPowerLimit(self, h, p):
        p.contents.value = 320000
        return 0

    def nvmlDeviceGetClockInfo(self, h, kind, p):
        p.contents.value = 2610
        return 0

    def nvmlDeviceGetFanSpeed(self, h, p):
        if not self.fan_supported:
            return 3                                    # NVML_ERROR_NOT_SUPPORTED
        p.contents.value = 55
        return 0


def test_nvml_sample():
    g = G.NvmlGpu(FakeNvml())
    assert g.name == "NVIDIA GeForce RTX 4080"
    s = g.sample()
    assert (s.load, s.temp, s.clock, s.fan_pct) == (37.0, 61.0, 2610, 55)
    assert (s.mem_used, s.mem_total) == (5.0, 16.0)
    assert (s.power, s.power_limit) == (281.5, 320.0)


def test_nvml_unsupported_value_is_none():
    s = G.NvmlGpu(FakeNvml(fan_supported=False)).sample()
    assert s.fan_pct is None and s.load == 37.0


def test_nvml_recovers_after_driver_error():
    lib = FakeNvml()
    g = G.NvmlGpu(lib)
    lib.lost = True
    assert g.sample() is None and lib.inits == 2       # re-initialised
    assert g.sample().load == 37.0


def test_detect_falls_back_to_nvidia_smi(monkeypatch):
    def no_nvml(*a, **k):
        raise OSError("libnvidia-ml.so.1: cannot open shared object file")
    monkeypatch.setattr(G.ctypes, "CDLL", no_nvml)
    monkeypatch.setattr(G.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    logs = []
    assert isinstance(G.detect(logs.append), G.NvidiaGpu)
    assert "nvidia-smi" in logs[0]


def test_detect_prefers_nvml(monkeypatch):
    monkeypatch.setattr(G.ctypes, "CDLL", lambda name: FakeNvml())
    logs = []
    assert isinstance(G.detect(logs.append), G.NvmlGpu)
    assert logs == ["GPU: NVIDIA GeForce RTX 4080 (NVML)"]


def test_nvidia_smi_failure_is_logged_once(tmp_path):
    from hmid.sensors.gpu import NvidiaGpu
    smi = tmp_path / "nvidia-smi"
    smi.write_text("#!/bin/sh\necho 'Failed to initialize NVML: Driver/library version mismatch'\n"
                   "echo 'NVML library version: 615.78'\nexit 18\n")
    smi.chmod(0o755)
    logs = []
    g = NvidiaGpu(str(smi), logs.append)
    assert g.sample() is None and g.sample() is None
    assert len(logs) == 1 and "version mismatch" in logs[0] and "reboot" in logs[0]


def test_nvml_init_error_explained():
    import pytest

    from hmid.sensors.gpu import NvmlGpu

    class Lib:
        def nvmlInit_v2(self):
            return 18
    with pytest.raises(OSError, match="mismatch.*reboot"):
        NvmlGpu(lib=Lib())
