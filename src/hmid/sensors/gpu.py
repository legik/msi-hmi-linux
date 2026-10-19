"""GPU readings: NVIDIA through NVML (the driver's library, no process per reading;
nvidia-smi as fallback) or AMD (sysfs)."""
from __future__ import annotations

import ctypes
import glob
import shutil
import subprocess
from dataclasses import dataclass

from .sysfs import read, read_int


@dataclass
class GpuSample:
    load: float | None = None        # %
    temp: float | None = None        # degC
    mem_used: float = 0.0            # GB
    mem_total: float = 0.0           # GB
    power: float | None = None       # W
    clock: int = 0                   # MHz
    fan_pct: int | None = None       # % (NVIDIA only)
    power_limit: float | None = None # W (board power limit / TDP)


def _num(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


class NvidiaGpu:
    QUERY = "utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw,clocks.gr,fan.speed,power.limit"

    def __init__(self, smi: str, log=None):
        self.smi = smi
        self.log = log
        self.error = None               # last failure, logged once when it changes

    def _failed(self, why):
        if why != self.error and self.log:
            self.log(f"GPU: nvidia-smi gives no readings: {why}")
        self.error = why
        return None

    def sample(self) -> GpuSample | None:
        try:
            r = subprocess.run([self.smi, f"--query-gpu={self.QUERY}", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError) as e:
            return self._failed(str(e))
        out = r.stdout.splitlines()
        if r.returncode or not out:
            msg = (r.stdout + r.stderr).strip().splitlines()
            why = msg[0] if msg else f"exit {r.returncode}"
            if "mismatch" in why.lower():
                why += " (the NVIDIA driver was updated - reboot)"
            return self._failed(why)
        if self.error and self.log:
            self.log("GPU: nvidia-smi works again")
        self.error = None
        f = [_num(x.strip()) for x in out[0].split(",")]
        if len(f) < 7:
            return None
        u, t, mu, mt, pw, clk, fan = f[:7]
        limit = f[7] if len(f) > 7 else None
        return GpuSample(load=u, temp=t, mem_used=(mu or 0) / 1024, mem_total=(mt or 0) / 1024,
                         power=pw, clock=int(clk or 0), fan_pct=int(fan) if fan is not None else None,
                         power_limit=limit)


class _NvmlMemory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class _NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


NVML_SUCCESS = 0
# NVML error codes worth explaining (nvml.h)
NVML_ERRORS = {9: "driver not loaded", 12: "library not found",
               18: "driver/library version mismatch: the NVIDIA driver was updated - reboot"}
NVML_TEMPERATURE_GPU = 0
NVML_CLOCK_GRAPHICS = 0


class NvmlGpu:
    """NVIDIA GPU through libnvidia-ml (NVML) - what nvidia-smi uses internally, without
    starting a process for every reading. Values the card does not support stay None."""

    def __init__(self, lib=None, index=0):
        self.lib = lib if lib is not None else ctypes.CDLL("libnvidia-ml.so.1")
        self.index = index
        self.handle = None
        self.name = "NVIDIA GPU"
        self._init()

    def _init(self):
        lib = self.lib
        rc = lib.nvmlInit_v2()
        if rc != NVML_SUCCESS:
            raise OSError(f"nvmlInit failed: {NVML_ERRORS.get(rc, f'error {rc}')}")
        h = ctypes.c_void_p()
        if lib.nvmlDeviceGetHandleByIndex_v2(ctypes.c_uint(self.index), ctypes.pointer(h)) != NVML_SUCCESS:
            raise OSError("no NVIDIA GPU found by NVML")
        self.handle = h
        buf = ctypes.create_string_buffer(96)
        if lib.nvmlDeviceGetName(h, buf, ctypes.c_uint(96)) == NVML_SUCCESS:
            self.name = buf.value.decode(errors="replace")

    def _get(self, fn, ctype, *args):
        v = ctype()
        rc = getattr(self.lib, fn)(self.handle, *args, ctypes.pointer(v))
        return (v, rc) if rc == NVML_SUCCESS else (None, rc)

    def sample(self) -> GpuSample | None:
        util, rc = self._get("nvmlDeviceGetUtilizationRates", _NvmlUtilization)
        if util is None and rc not in (3,):              # 3 = not supported; anything else: re-init next time
            try:
                self._init()
            except OSError:
                pass
            return None
        temp, _ = self._get("nvmlDeviceGetTemperature", ctypes.c_uint, ctypes.c_int(NVML_TEMPERATURE_GPU))
        mem, _ = self._get("nvmlDeviceGetMemoryInfo", _NvmlMemory)
        power, _ = self._get("nvmlDeviceGetPowerUsage", ctypes.c_uint)               # mW
        limit, _ = self._get("nvmlDeviceGetEnforcedPowerLimit", ctypes.c_uint)       # mW
        clock, _ = self._get("nvmlDeviceGetClockInfo", ctypes.c_uint, ctypes.c_int(NVML_CLOCK_GRAPHICS))
        fan, _ = self._get("nvmlDeviceGetFanSpeed", ctypes.c_uint)                   # %
        return GpuSample(
            load=float(util.gpu) if util is not None else None,
            temp=float(temp.value) if temp is not None else None,
            mem_used=mem.used / 2**30 if mem is not None else 0.0,
            mem_total=mem.total / 2**30 if mem is not None else 0.0,
            power=power.value / 1000 if power is not None else None,
            clock=int(clock.value) if clock is not None else 0,
            fan_pct=int(fan.value) if fan is not None else None,
            power_limit=limit.value / 1000 if limit is not None else None,
        )


class AmdGpu:
    def __init__(self, dev: str, hwmon: str | None):
        self.dev, self.hw = dev, hwmon

    def sample(self) -> GpuSample:
        d, hw = self.dev, self.hw
        g = GpuSample(load=float(read_int(f"{d}/gpu_busy_percent") or 0),
                      mem_used=(read_int(f"{d}/mem_info_vram_used") or 0) / 2**30,
                      mem_total=(read_int(f"{d}/mem_info_vram_total") or 0) / 2**30)
        if hw:
            t = read_int(f"{hw}/temp1_input")
            g.temp = t / 1000 if t is not None else None
            pw = read_int(f"{hw}/power1_average") or read_int(f"{hw}/power1_input")
            g.power = pw / 1e6 if pw else None
            cap = read_int(f"{hw}/power1_cap")
            g.power_limit = cap / 1e6 if cap else None
            fr = read_int(f"{hw}/freq1_input")
            g.clock = fr // 1_000_000 if fr else 0
        return g


def detect(log=None):
    """NvmlGpu, NvidiaGpu (nvidia-smi), AmdGpu or None."""
    try:
        g = NvmlGpu()
        if log:
            log(f"GPU: {g.name} (NVML)")
        return g
    except (OSError, AttributeError) as e:
        why = str(e)
    smi = shutil.which("nvidia-smi")
    if smi:
        if log:
            log(f"GPU: NVIDIA via nvidia-smi (NVML not usable: {why})")
        return NvidiaGpu(smi, log)
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]")):
        dev = f"{card}/device"
        if read(f"{dev}/gpu_busy_percent") is not None:
            hw = (glob.glob(f"{dev}/hwmon/hwmon*") or [None])[0]
            return AmdGpu(dev, hw)
    return None
