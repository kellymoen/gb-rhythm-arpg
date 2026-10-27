import pytest
from PIL import Image

from gbtools import tiles
from gbtools.errors import ConvertError


def indexed(w, h, pixels=()):
    img = Image.new("P", (w, h), 0)
    img.putpalette([255, 255, 255, 170, 170, 170, 85, 85, 85, 0, 0, 0])
    for (x, y), v in pixels:
        img.putpixel((x, y), v)
    return img


def test_2bpp_encoding_of_indexed_png(tmp_path):
    p = tmp_path / "t.png"
    indexed(8, 8, [((0, 0), 1), ((1, 0), 2), ((2, 0), 3)]).save(p)
    data = tiles.convert(p, sprite8x16=False)
    assert len(data) == 1
    # row 0: pixels 1,2,3 -> low plane 1,0,1 ; high plane 0,1,1
    assert data[0][0] == 0b10100000
    assert data[0][1] == 0b01100000


def test_rgb_png_maps_lightest_to_zero(tmp_path):
    p = tmp_path / "t.png"
    img = Image.new("RGB", (8, 8), (240, 240, 240))
    img.putpixel((0, 0), (10, 10, 10))
    img.save(p)
    data = tiles.convert(p, sprite8x16=False)
    assert data[0][0] == 0b10000000 and data[0][1] == 0b10000000  # black stays shade 3


def test_rgb_colours_on_the_same_shade_are_rejected(tmp_path):
    p = tmp_path / "t.png"
    img = Image.new("RGB", (8, 8), (250, 250, 250))
    img.putpixel((0, 0), (240, 240, 240))
    img.save(p)
    with pytest.raises(ConvertError, match="indexed PNG"):
        tiles.convert(p, sprite8x16=False)


def test_sprite8x16_orders_top_then_bottom(tmp_path):
    p = tmp_path / "s.png"
    indexed(16, 16, [((0, 8), 3), ((8, 0), 3)]).save(p)
    data = tiles.convert(p, sprite8x16=True)
    assert [t[0] for t in data] == [0, 0x80, 0x80, 0]


def test_errors(tmp_path):
    p = tmp_path / "bad.png"
    indexed(12, 8).save(p)
    with pytest.raises(ConvertError, match="width must be a multiple of 8"):
        tiles.convert(p, sprite8x16=False)
    img = Image.new("RGB", (8, 8))
    for i in range(5):
        img.putpixel((i, 0), (i * 50, 0, 0))
    img.save(p)
    with pytest.raises(ConvertError, match="has 5 colours"):
        tiles.convert(p, sprite8x16=False)
