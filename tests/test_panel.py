import struct

from hmid.panel import protocol as P


def test_upload_sequence(panel, fake):
    data = bytes(3000)
    panel.upload(data, "M25-S0-V-R0.mp4")
    kinds = [s[0] if s[0] == "data" else s[1] for s in fake.sent]
    assert kinds == [P.Cmd.FILE_NODE, P.Cmd.START_DATA, "data", "data", "data", P.Cmd.END_DATA]
    assert fake.sent[1][3] == 3000                 # START_DATA length = file size


def test_queries_get_replies(panel):
    assert panel.device_info()[4] == 50
    assert panel.lcid() == bytes([9, 4, 0, 0])


def test_clock_syncs_time_first(panel, fake):
    panel.clock(style=3, fmt24=False)
    cmds = fake.commands()
    assert cmds[0][1] == P.Cmd.HOST_TIME and struct.unpack_from("<I", cmds[0][2])[0] == 0
    body = cmds[1][2]
    assert body[0] == P.Mode.CLOCK and body[2] == 10 and body[3 + 3] == 1


def test_hw_values_two_commands(panel, fake):
    panel.hw_values([1] * 27)
    assert [c[1] for c in fake.commands()] == [P.Cmd.HW_VALUES_A, P.Cmd.HW_VALUES_B]
    assert fake.commands()[1][3] == 32


def test_sleep_screen_turns_backlight_off(panel, fake, no_sleep):
    panel.power_screen(P.Mode.SLEEP, backlight_off=True)
    assert fake.script()[0] == "display 20 sub=0 0101"
    assert fake.commands()[-1][1] == P.Cmd.SET_BACKLIGHT and fake.commands()[-1][2][0] == 0


def test_describe_last(panel):
    panel.msg("55AASETTEMP05AA5")
    assert panel.describe_last() == "msg 55AASETTEMP05AA5"
