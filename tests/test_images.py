import struct
import zlib

import pytest

from vic2toolmod.images import ImageError, png, tga_to_png, tga_to_rgba


def tga(width, height, pixels_bgr, rle=False, top=False):
    header = struct.pack(
        "<BBBHHBHHHHBB",
        0,
        0,
        10 if rle else 2,
        0,
        0,
        0,
        0,
        0,
        width,
        height,
        24,
        0x20 if top else 0,
    )
    if not rle:
        return header + b"".join(pixels_bgr)
    body = b""
    for px in pixels_bgr:  # one raw packet per pixel
        body += bytes([0]) + px
    return header + body


def test_uncompressed_bottom_origin_is_flipped():
    blue, red = b"\xff\x00\x00", b"\x00\x00\xff"  # BGR
    w, h, rgba = tga_to_rgba(tga(1, 2, [blue, red]))
    assert (w, h) == (1, 2)
    assert rgba == bytes((255, 0, 0, 255, 0, 0, 255, 255))  # top row = last stored (red)


def test_rle_and_top_origin():
    data = tga(2, 1, [b"\x00\xff\x00", b"\x00\xff\x00"], rle=True, top=True)
    assert tga_to_rgba(data)[2] == bytes((0, 255, 0, 255)) * 2


def test_png_structure():
    out = tga_to_png(tga(1, 1, [b"\x01\x02\x03"]))
    assert out.startswith(b"\x89PNG\r\n\x1a\n") and out.endswith(b"IEND\xaeB`\x82")
    idat = out[out.index(b"IDAT") + 4 : out.index(b"IEND") - 8]
    assert zlib.decompress(idat) == b"\x00" + bytes((3, 2, 1, 255))
    assert png(1, 1, b"\x00\x00\x00\x00")[:8] == b"\x89PNG\r\n\x1a\n"


def test_unsupported():
    with pytest.raises(ImageError):
        tga_to_rgba(b"\x00" * 10)


def test_stretch_keeps_the_frame_and_writes_dds_and_tga():
    """K94: nine-slice stretching; uncompressed DDS / Targa read back the same."""
    from vic2toolmod.images import dds, dds_to_rgba, stretch, tga, tga_to_rgba

    w, h = 6, 4
    px = bytes(v for i in range(w * h) for v in (i * 10 % 256, 0, 255 - i, 255))
    out = stretch(w, h, px, 10, 7, 1)
    assert len(out) == 10 * 7 * 4

    def at(data, width, x, y):
        return data[(y * width + x) * 4 : (y * width + x) * 4 + 4]

    # the corner pixels (frame of 1) stay as they were
    assert at(out, 10, 0, 0) == at(px, w, 0, 0)
    assert at(out, 10, 9, 6) == at(px, w, 5, 3)
    assert at(out, 10, 9, 0) == at(px, w, 5, 0)
    assert stretch(w, h, px, w, h, 1) == px  # same size: unchanged
    assert dds_to_rgba(dds(10, 7, out)) == (10, 7, out)
    assert tga_to_rgba(tga(10, 7, out)) == (10, 7, out)
