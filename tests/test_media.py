import json
import shutil
import subprocess

import pytest
from PIL import Image

from hmid import media
from hmid.panel import protocol as P


def animated_gif(path, frames=12):
    ims = [Image.new("RGB", (200, 120), (i * 20, 80, 255 - i * 20)) for i in range(frames)]
    ims[0].save(path, save_all=True, append_images=ims[1:], duration=40, loop=0)


def test_delete_only_slot7_still_pictures():
    for name in P.deletable():
        payload, n = P.delete_payload(name)
        assert n == 32 and payload.rstrip(b"\0") == name.encode()
    for bad in ("M1-S7-V-R0.avi", "M25-S0-V-R0.mp4", "HMI_FW_Setting.ini", "M1-S3-O-R0.png", "../x"):
        with pytest.raises(ValueError):
            P.delete_payload(bad)


def test_is_animated(tmp_path):
    animated_gif(tmp_path / "a.gif")
    Image.new("RGB", (10, 10)).save(tmp_path / "still.gif")
    assert media.is_animated(str(tmp_path / "a.gif"))
    assert not media.is_animated(str(tmp_path / "still.gif"))
    assert media.is_animated("clip.mp4")


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="needs ffmpeg")
def test_gif_to_avi_matches_msi_format(tmp_path):
    animated_gif(tmp_path / "a.gif")
    data = media.animation_avi(str(tmp_path / "a.gif"))
    out = tmp_path / "out.avi"
    out.write_bytes(data)
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                      "stream=codec_name,profile,width,height,pix_fmt,has_b_frames:format=format_name",
                                      "-of", "json", str(out)], capture_output=True, text=True).stdout)
    s = info["streams"][0]
    assert (s["codec_name"], s["profile"], s["width"], s["height"], s["pix_fmt"], s["has_b_frames"]) == \
        ("h264", "Constrained Baseline", 480, 800, "yuv420p", 0)
    assert info["format"]["format_name"] == "avi"


def test_show_video_sequence(panel, fake, no_sleep):
    panel.show_video(b"AVI" * 500)
    assert fake.script() == ["msg 55AASETTEMP05AA5", "display 24 sub=0 01",
                             "cmd 42", "cmd 42", "cmd 42", "cmd 42",
                             "upload M1-S7-V-R0.avi", "display 1 sub=0 " + bytes([0] * 7 + [1]).hex()]
    deleted = [c[2][:c[3]].rstrip(b"\0").decode() for c in fake.commands() if c[1] == P.Cmd.DELETE_FILE]
    assert deleted == P.deletable()


def test_still_modes(tmp_path):
    import io
    p = tmp_path / "wide.png"
    im = Image.new("RGB", (1600, 900), (255, 0, 0))
    im.paste((0, 0, 255), (0, 0, 100, 900))            # blue strip on the left edge
    im.save(p)

    def load(**kw):
        return Image.open(io.BytesIO(media.still_png(str(p), **kw))).convert("RGB")
    fill, fit, stretch = load(), load(mode="fit"), load(mode="stretch")
    assert fill.size == fit.size == stretch.size == (480, 800)
    assert fill.getpixel((240, 5)) == (255, 0, 0) and fill.getpixel((2, 400)) == (255, 0, 0)   # covered, edge cropped
    assert fit.getpixel((240, 5)) == (0, 0, 0)                                                 # black border
    assert stretch.getpixel((2, 400))[2] > 200                                                 # nothing cropped
    rot = load(rotate=True)                                                                    # left edge -> top
    assert rot.getpixel((240, 2))[2] > 200


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_animation_modes(tmp_path):
    animated_gif(tmp_path / "a.gif")
    for mode in media.MODES:
        for rotate in (False, True):
            assert media.animation_avi(str(tmp_path / "a.gif"), mode, rotate)[:4] == b"RIFF"
