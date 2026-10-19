import pytest

from hmid.lighting import mystic as M


def report():
    buf = bytearray(M.SIZE)
    buf[0] = M.REPORT
    buf[M.STRIP_CONTROL] = 0x0F
    buf[M.SAVE_BYTE] = 1
    return buf


def test_steady_tiffany_disables_animated_zone():
    out = M.apply_effect(report(), 82, "0ABAB5")
    for o in M.EFFECT_OFFSETS[:5]:
        assert out[o] == 1 and out[o + 1:o + 4] == bytes.fromhex("0ABAB5")
    assert out[M.STRIP_CONTROL] == 0 and out[M.SAVE_BYTE] == 0


def test_rainbow_only_touches_strip():
    before = report()
    out = M.apply_effect(before, 92)
    assert out[74] == 0x1A
    assert out[:74] == before[:74]


def test_off_and_errors():
    out = M.apply_effect(M.apply_effect(report(), 82), 80)
    assert all(out[o] == 0 for o in M.EFFECT_OFFSETS)
    with pytest.raises(ValueError):
        M.apply_effect(report(), 101)
    bad = report()
    bad[0] = 0
    with pytest.raises(OSError):
        M.apply_effect(bad, 82)


def test_controller_read_modify_write():
    class Dev:
        def __init__(self):
            self.buf = report()

        def read(self):
            return bytearray(self.buf)

        def write(self, b):
            self.buf = bytearray(b)

    ml = M.MysticLight(Dev())
    ml.apply(92)
    ml.cpu_temp_color(95)
    assert ml.dev.buf[75:78] == bytes((255, 0, 0)) and ml.dev.buf[74] == 0x1A
    assert "rainbow" in ml.describe()


def test_temp_colors():
    assert M.temp_color(40) == (0, 255, 0) and M.temp_color(80) == (0, 0, 255) and M.temp_color(95) == (255, 0, 0)
