"""Icons (T003): DDS decoding, sprites of interface/*.gfx, icon numbers in the schema."""

import struct
from pathlib import Path

import pytest

from vic2toolmod.images import ImageError, dds_to_rgba, frame, image_to_rgba
from vic2toolmod.server.app import Engine
from vic2toolmod.services import LanguageService
from vic2toolmod.workspace import Workspace


def dds(width: int, height: int, body: bytes, fourcc: bytes = b"", bits: int = 32) -> bytes:
    """A minimal DDS file: uncompressed ARGB (masks of crime_strip.dds) or a FourCC."""
    header = bytearray(128)
    header[:4] = b"DDS "
    struct.pack_into("<IIII", header, 4, 124, 0x1007, height, width)
    if fourcc:
        struct.pack_into("<II4s", header, 76, 32, 0x4, fourcc)
    else:
        struct.pack_into(
            "<II4s5I", header, 76, 32, 0x41, b"\0\0\0\0", bits,
            0xFF0000, 0xFF00, 0xFF, 0xFF000000,
        )  # fmt: skip
    return bytes(header) + body


def test_uncompressed_argb():
    # pixels are B G R A in memory (masks: R 0xFF0000, G 0xFF00, B 0xFF, A 0xFF000000)
    w, h, px = dds_to_rgba(dds(2, 1, bytes([1, 2, 3, 255, 9, 8, 7, 0])))
    assert (w, h, px) == (2, 1, bytes([3, 2, 1, 255, 7, 8, 9, 0]))


def test_dxt1_block():
    # c0 = pure red (0xF800), c1 = pure blue (0x001F); c0 > c1: four opaque colours;
    # index 0 for the first row, 1 for the second, 2 and 3 below.
    idx = sum(code << (2 * i) for i, code in enumerate([0] * 4 + [1] * 4 + [2] * 4 + [3] * 4))
    w, h, px = dds_to_rgba(dds(4, 4, struct.pack("<HHI", 0xF800, 0x001F, idx), b"DXT1"))
    pixel = lambda x, y: tuple(px[(y * 4 + x) * 4 : (y * 4 + x) * 4 + 4])  # noqa: E731
    assert pixel(0, 0) == (255, 0, 0, 255) and pixel(3, 1) == (0, 0, 255, 255)
    assert pixel(0, 2) == (170, 0, 85, 255) and pixel(0, 3) == (85, 0, 170, 255)


def test_frames_and_errors():
    w, h, px = 6, 1, bytes(range(24))
    assert frame(w, h, px, 3, 2) == (2, 1, bytes(range(8, 16)))
    with pytest.raises(ImageError):
        frame(w, h, px, 3, 4)
    with pytest.raises(ImageError):
        dds_to_rgba(dds(4, 4, b"", b"ATI2"))
    assert image_to_rgba(dds(1, 1, bytes(4)))[:2] == (1, 1)


def write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("latin-1") if isinstance(data, str) else data)


@pytest.fixture
def game(tmp_path):
    g = tmp_path / "game"
    # the .gfx names a .tga, the file is a .dds - like the game itself
    write(
        g / "interface/province_interface.gfx",
        'spriteTypes = { spriteType = { name = "GFX_crime_strip"\n'
        '  textureFile = "gfx\\\\interface\\\\crime_strip.tga" noOfFrames = 3 } }\n',
    )
    write(g / "gfx/interface/crime_strip.dds", dds(6, 2, bytes(range(48))))
    write(
        g / "common/crime.txt",
        "bombs = { icon = 1 trigger = { } }\nbad = { icon = 5 trigger = { } }\n",
    )
    return g


def test_icon_numbers_are_checked_and_shown(game):
    ws = Workspace.open(game)
    assert ws.registries().frames("gfx_crime_strip") == 3
    report = ws.check_file("common/crime.txt")
    assert [d.message for d in report.diagnostics] == [
        "icon 5 does not exist: GFX_crime_strip has 3 icons (0..2)"
    ]
    svc = LanguageService(ws)
    text = ws.document("common/crime.txt").text
    hover = svc.hover("common/crime.txt", text.index("= 1") + 2)
    assert hover.sprite == ("GFX_crime_strip", 2)  # crimes count from 0: icon 1 = 2nd frame
    key = svc.hover("common/crime.txt", text.index("icon") + 1)
    assert key.sprite == ("GFX_crime_strip", 2) and "crime_strip" in key.text
    # the server sends that frame as PNG
    image = Engine(ws).sprite("GFX_crime_strip", 2)
    assert image[:8] == b"\x89PNG\r\n\x1a\n"


def test_missing_required_icon(game):
    write(game / "common/crime.txt", "bombs = { trigger = { } }\n")
    report = Workspace.open(game).check_file("common/crime.txt")
    assert [d.message for d in report.diagnostics] == ["required key 'icon' is missing"]
