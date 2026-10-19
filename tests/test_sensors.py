import os
import time

from hmid.sensors import Sample, Sensors
from hmid.sensors.board import Board
from hmid.sensors.fps import MangoHudFps, app_name

HEADER = ("os,cpu,gpu,ram,kernel,driver,cpuscheduler\nArch,i9,RTX,32,6.12,nv,x\n"
          "fps,frametime,cpu_load,cpu_power,gpu_load,cpu_temp,gpu_temp,gpu_core_clock,gpu_mem_clock,"
          "gpu_vram_used,gpu_power,ram_used,swap_used,process_rss,cpu_mhz,elapsed\n")


def nct_chip(tmp_path):
    """sysfs of the Trident X2's NCT6687 as seen with `nct6683 force=1`."""
    hw = tmp_path / "hwmon5"
    hw.mkdir()
    (hw / "name").write_text("nct6687\n")
    for n, rpm, pwm in ((1, 653, 105), (2, 2977, 255), (3, 0, 79), (4, 1016, 79)):
        (hw / f"fan{n}_input").write_text(f"{rpm}\n")
        (hw / f"pwm{n}").write_text(f"{pwm}\n")
    for i, (label, t) in enumerate((("PECI 0.0", 41000), ("Diode 0 (curr)", 47000), ("Thermistor 15", 57000),
                                    ("Thermistor 16", 43000)), 1):
        (hw / f"temp{i}_label").write_text(label + "\n")
        (hw / f"temp{i}_input").write_text(f"{t}\n")
    return str(hw)


def test_board_msi_order(tmp_path):
    b = Board(chip=nct_chip(tmp_path))
    assert b.fans() == {"cpu_fan": (653, 41), "pump": (2977, 100), "sys_fan": (1016, 31)}
    assert b.vrm_temp() == 57.0


def test_board_mapping_and_label(tmp_path):
    b = Board({"cpu_fan": "fan2", "sys_fan": "fan3"}, "Thermistor 16", chip=nct_chip(tmp_path))
    assert b.fans() == {"cpu_fan": (2977, 100)}           # fan3 does not spin -> no reading
    assert b.vrm_temp() == 43.0


def test_fps_live_and_stale(tmp_path):
    f = tmp_path / "eldenring.exe_2026-10-18_15-02-11.csv"
    f.write_text(HEADER + "141.2,7.08,30,60,95,70,66,2600,10000,8.1,280,12,0,4,5200,1\n"
                          "143.7,6.96,31,61,96,71,67,2600,10000,8.1,281,12,0,4,5200,2\n")
    r = MangoHudFps(str(tmp_path))
    g = r.read()
    assert (g.fps, g.frametime, g.app) == (143.7, 6.96, "eldenring")
    old = time.time() - 10
    os.utime(f, (old, old))
    assert r.read() is None
    assert os.path.exists(f)                              # never deleted


def test_fps_ignores_summary_and_headers_only(tmp_path):
    (tmp_path / "game_2026-10-18_15-00-00_summary.csv").write_text("x\n1\n")
    (tmp_path / "game_2026-10-18_15-00-01.csv").write_text(HEADER)
    assert MangoHudFps(str(tmp_path)).read() is None


def test_app_name():
    assert app_name("/x/vkcube_2026-10-18_15-00-00.csv") == "vkcube"
    assert app_name("/x/my_game_2026-10-18_15-00-00.csv") == "my_game"


def test_missing_sensors():
    sn = Sensors.__new__(Sensors)
    sn.cpu = type("C", (), {"has_power": False})()
    gone = sn.missing(Sample())
    assert {"fps", "cpu_fan", "pump", "vrm_temp", "gpu_load", "cpu_power", "ram_clock"} <= gone
    assert "cpu_load" not in gone and "upload" not in gone


def test_missing_fan_percent_is_a_dash():
    from test_hwmon import sample

    from hmid import hwmon
    r = hwmon.readings(sample(gpu=None, fans={}))
    assert r["gpu_fan_pct"].text == "–" and r["gpu_fan_pct"].pct is None
    assert r["cpu_fan_pct"].text == "–"
    r = hwmon.readings(sample())
    assert r["gpu_fan_pct"].text == "55" and r["cpu_fan_pct"].text == "41"
