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


def test_unit_and_rebel_icons(game):
    # T006: units/*.txt icon -> GFX_unit_strip, rebel icon -> GFX_politics_rebel_strip
    write(
        game / "interface/unit.gfx",
        'spriteTypes = { spriteType = { name = "GFX_unit_strip"\n'
        '  textureFile = "gfx\\\\interface\\\\unit_strip.dds" noOfFrames = 2 }\n'
        'spriteType = { name = "GFX_politics_rebel_strip"\n'
        '  textureFile = "gfx\\\\interface\\\\rebels.dds" noOfFrames = 2 } }\n',
    )
    write(game / "units/infantry.txt", "infantry = { icon = 2 }\nguard = { icon = 3 }\n")
    write(game / "common/rebel_types.txt", "reactionary = { icon = 1 }\n")
    ws = Workspace.open(game)
    report = ws.check_file("units/infantry.txt")
    assert [d.message for d in report.diagnostics] == [
        "icon 3 does not exist: GFX_unit_strip has 2 icons (1..2)"
    ]
    svc = LanguageService(ws)
    text = ws.document("units/infantry.txt").text
    assert svc.hover("units/infantry.txt", text.index("= 2") + 2).sprite == ("GFX_unit_strip", 2)
    text = ws.document("common/rebel_types.txt").text
    hover = svc.hover("common/rebel_types.txt", text.index("= 1") + 2)
    assert hover.sprite == ("GFX_politics_rebel_strip", 1)


def test_pictures_are_checked_and_shown(game):
    # T006: picture = name in events / decisions names a file of gfx/pictures/...
    write(game / "gfx/pictures/decisions/railways.dds", dds(2, 2, bytes(16)))
    write(
        game / "decisions/test.txt",
        "political_decisions = {\n"
        "  a = { picture = railways potential = { } allow = { } effect = { } }\n"
        "  b = { picture = nothing_here potential = { } allow = { } effect = { } }\n"
        "}\n",
    )
    ws = Workspace.open(game)
    report = ws.check_file("decisions/test.txt")
    assert [d.message for d in report.diagnostics] == [
        "picture 'nothing_here' not found: no gfx/pictures/decisions/nothing_here.tga or .dds"
    ]
    svc = LanguageService(ws)
    text = ws.document("decisions/test.txt").text
    hover = svc.hover("decisions/test.txt", text.index("railways") + 2)
    assert hover.picture == "gfx/pictures/decisions/railways.dds"
    engine = Engine(ws)
    assert engine.image(hover.picture)[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(Exception, match="not a picture"):
        engine.image("common/crime.txt")


def test_palette_dds():
    # 8-bit palette (flags 0x20), as RPM's decision pictures: palette after the header
    header = bytearray(dds(2, 1, b""))
    struct.pack_into("<II4sI", header, 76, 32, 0x20, b"\0\0\0\0", 8)
    palette = bytes([10, 20, 30, 0]) + bytes([200, 100, 50, 0]) + bytes(254 * 4)
    w, h, px = dds_to_rgba(bytes(header) + palette + bytes([1, 0]))
    assert (w, h, px) == (2, 1, bytes([200, 100, 50, 255, 10, 20, 30, 255]))


def test_tga_16_bits():
    # A1R5G5B5, origin at the top (RPM's events/farming.tga): pure red, then white
    header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, 2, 1, 16, 0x20)
    w, h, px = image_to_rgba(header + struct.pack("<HH", 31 << 10, 0x7FFF))
    assert (w, h, px) == (2, 1, bytes([255, 0, 0, 255, 255, 255, 255, 255]))


def test_stretch_picture_endpoint(tmp_path):
    """K94: a picture stretched into a new file and sprite; only the element points at it."""
    from vic2toolmod.images import dds as make_dds
    from vic2toolmod.images import dds_to_rgba
    from vic2toolmod.server.app import ApiError

    game = tmp_path / "game"
    (game / "interface").mkdir(parents=True)
    tex = "gfx\\\\interface\\\\bg.dds"
    (game / "interface/x.gfx").write_text(
        f'spriteTypes = {{ spriteType = {{ name = "GFX_bg" texturefile = "{tex}" }}\n'
        f'spriteType = {{ name = "GFX_strip" texturefile = "{tex}" noOfFrames = 2 }} }}\n'
    )
    (game / "interface/w.gui").write_text(
        'guiTypes = {\n\twindowType = {\n\t\tname = "w"\n\t\ticonType = {\n'
        '\t\t\tname = "back"\n\t\t\tspriteType = "GFX_bg"\n\t\t}\n\t}\n}\n'
    )
    (game / "gfx/interface").mkdir(parents=True)
    original = make_dds(8, 6, bytes([10, 20, 30, 255]) * 48)
    (game / "gfx/interface/bg.dds").write_bytes(original)
    (tmp_path / "mod").mkdir()
    engine = Engine(Workspace.open(game, tmp_path / "mod"))
    body = {"sprite": "GFX_bg", "width": 12, "height": 9, "border": 2}
    preview = engine.stretch_picture(body)
    assert preview["from"] == [8, 6] and preview["to"] == [12, 9] and preview["preview"]
    assert not (tmp_path / "mod/gfx").exists()
    done = engine.stretch_picture({**body, "write": True, "rel": "interface/w.gui", "line": 4})
    assert done["sprite"] == "GFX_bg_12x9"
    assert done["texture"] == "gfx/interface/vic2toolmod/bg_12x9.dds"
    w, h, px = dds_to_rgba((tmp_path / "mod" / done["texture"]).read_bytes())
    assert (w, h) == (12, 9) and px[:4] == bytes([10, 20, 30, 255])
    assert (game / "gfx/interface/bg.dds").read_bytes() == original  # shared texture untouched
    gfx = (tmp_path / "mod/interface/vic2toolmod_stretched.gfx").read_text()
    assert 'name = "GFX_bg_12x9"' in gfx and "vic2toolmod\\\\bg_12x9.dds" in gfx
    assert 'spriteType = "GFX_bg_12x9"' in (tmp_path / "mod/interface/w.gui").read_text()
    sprite = engine.ws.registries().sprites.get("gfx_bg_12x9")
    assert sprite is not None and engine.texture(sprite.texture) == done["texture"]
    with pytest.raises(ApiError, match="strip"):
        engine.stretch_picture({**body, "sprite": "GFX_strip"})
    with pytest.raises(ApiError, match="no element"):
        engine.stretch_picture({**body, "write": True, "rel": "interface/w.gui", "line": 2})
