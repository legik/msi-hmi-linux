from hmid import hwmon
from hmid.sensors import GameSample, GpuSample, Sample


def sample(**kw):
    base = dict(cpu_load=37.0, cpu_temp=71.0, cpu_mhz=4250, cpu_power=55, mem_used=11.3, mem_total=32,
                mem_mhz=4400, gpu=GpuSample(load=96, temp=67, mem_used=8, mem_total=12, power=281, clock=2600, fan_pct=55),
                net_down=2.4e6, net_up=120e3, fans={"cpu_fan": (653, 41), "pump": (2977, 100), "sys_fan": (1016, 31)},
                vrm_temp=57.0, game=GameSample(143.7, 6.96, "eldenring"))
    base.update(kw)
    return Sample(**base)


def test_encode_msi_order():
    v = hwmon.encode(sample())
    assert len(v) == 27
    assert v[:16] == [42, 37, 71, 653, 2977, 2600, 96, 67, 0, 4400, 144, 57, 41, 55, 1016, 31]


def test_encode_network_units():
    v = hwmon.encode(sample(net_up=500, net_down=50e6))
    assert v[16] == int(500 / 1024 * 10)                 # KB/s x10
    assert v[17] & 16384 and not v[17] & 32768           # MB/s flag
    assert hwmon.encode(sample(net_down=5e9))[17] & 32768


def test_encode_without_gpu_or_game():
    v = hwmon.encode(sample(gpu=None, game=None, fans={}))
    assert v[5] == v[6] == v[7] == v[13] == v[10] == v[3] == 0


def test_select_modes():
    assert hwmon.select(None, "multi") == hwmon.MULTI_DEFAULT
    lst = hwmon.select(None, "list")
    assert "ram_used" not in lst and "upload" in lst and "cpu_clock" in lst
    assert hwmon.select(["cpu_load", "bogus", "fps"], "multi", {"fps"}) == ["cpu_load"]
    assert hwmon.select(["fps"], "multi", {"fps"}) == ["fps"]        # never empty


def test_list_layout():
    net, slots = hwmon.list_layout(["cpu_load", "gpu_temp", "download"], style=2)
    assert len(slots) == 16 and slots[1] == 2 and slots[7] == 2 and sum(slots) == 4
    assert net[:2] == bytes([0, 2]) and len(net) == 16


def test_readings_text():
    r = hwmon.readings(sample())
    assert r["cpu_clock"].text == "4200"
    assert r["fps"].text == "144"
    assert r["download"].text == "2.4 MB/s"
    assert r["ram_used"].unit == "/ 32 GB" and r["ram_used"].pct is not None
    assert r["gpu_load"].state == "crit"
