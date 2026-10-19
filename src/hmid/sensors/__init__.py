"""All readings the panel shows, collected into one typed Sample per update."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import memory
from .board import Board
from .cpu import Cpu
from .fps import GameSample, MangoHudFps
from .gpu import GpuSample
from .gpu import detect as detect_gpu
from .network import Network


@dataclass
class Sample:
    time: time.struct_time = field(default_factory=time.localtime)
    cpu_load: float | None = None
    cpu_temp: float | None = None
    cpu_mhz: float | None = None
    cpu_power: float | None = None
    mem_used: float = 0.0
    mem_total: float = 0.0
    mem_mhz: int = 0
    gpu: GpuSample | None = None
    net_down: float | None = None
    net_up: float | None = None
    fans: dict = field(default_factory=dict)       # role -> (rpm, pct)
    vrm_temp: float | None = None
    game: GameSample | None = None


class Sensors:
    def __init__(self, fan_map=None, vrm_label=None, mangohud_folder="/tmp/hmi-fps", log=None):
        self.cpu = Cpu()
        self.gpu = detect_gpu(log)
        self.net = Network()
        self.board = Board(fan_map, vrm_label)
        self.fps = MangoHudFps(mangohud_folder)

    def sample(self) -> Sample:
        used, total = memory.usage()
        down, up = self.net.rates()
        return Sample(
            time=time.localtime(),
            cpu_load=self.cpu.load(), cpu_temp=self.cpu.temp(), cpu_mhz=self.cpu.mhz(),
            cpu_power=self.cpu.power(),
            mem_used=used, mem_total=total, mem_mhz=memory.clock_mhz(),
            gpu=self.gpu.sample() if self.gpu else None,
            net_down=down, net_up=up,
            fans=self.board.fans(), vrm_temp=self.board.vrm_temp(),
            game=self.fps.read(),
        )

    def missing(self, s: Sample) -> set[str]:
        """Hardware-monitor sensor names this PC has no reading for (see hmid.hwmon)."""
        out = {"gpu_fan"}                               # NVIDIA reports fan % only
        if not s.game:
            out.add("fps")                              # only while a game runs with MangoHud
        if "cpu_fan" not in s.fans:
            out |= {"cpu_fan", "cpu_fan_pct"}
        if "pump" not in s.fans:
            out.add("pump")
        if "sys_fan" not in s.fans:
            out |= {"sys_fan", "sys_fan_pct"}
        if s.vrm_temp is None:
            out.add("vrm_temp")
        g = s.gpu
        if not g:
            out |= {"gpu_clock", "gpu_load", "gpu_temp", "gpu_fan_pct", "gpu_power"}
        else:
            if g.power is None:
                out.add("gpu_power")
            if g.fan_pct is None:
                out.add("gpu_fan_pct")
        if not s.mem_mhz:
            out.add("ram_clock")
        if s.cpu_temp is None:
            out.add("cpu_temp")
        if not self.cpu.has_power:
            out.add("cpu_power")
        return out


__all__ = ["Sample", "Sensors", "GpuSample", "GameSample"]
