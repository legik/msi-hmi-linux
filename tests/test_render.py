import io

from PIL import Image
from test_hwmon import sample

from hmid import hwmon
from hmid.render import Renderer


def size(png):
    im = Image.open(io.BytesIO(png))
    return im.size, im.mode


def test_stats_page():
    r = Renderer(2)
    assert size(r.stats(sample())) == ((480, 800), "RGBA")
    assert size(r.stats(sample(gpu=None, game=None, cpu_load=None, cpu_temp=None))) == ((480, 800), "RGBA")


def test_multi_pages():
    r = Renderer(1)
    for names in (hwmon.MULTI_DEFAULT, ["cpu_load", "ram_used"], list(hwmon.SENSORS)[:12]):
        assert size(r.multi(sample(), names, 0, 2))[0] == (480, 800)


def test_game_card_changes_page():
    r = Renderer(2)
    assert r.stats(sample()) != r.stats(sample(game=None))
