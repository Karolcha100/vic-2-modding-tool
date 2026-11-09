"""Windows of interface/*.gui as element trees (K80)."""

from pathlib import Path

import pytest

from vic2toolmod.analysis import gui_tree
from vic2toolmod.workspace import Workspace

GUI = """guiTypes = {
\twindowType = {
\t\tname = "country_politics"
\t\tsize = { x=1024 y=632 }
\t\ticonType = { name = "bg" spriteType = "GFX_bg" position = { x = -70 y = -70 } }
\t\ticonType = { name = "chart" spriteType = "GFX_chart" position = { x = 95 y = 104 } }
\t\twindowType = {
\t\t\tname = "reforms_window"
\t\t\tposition = { x = 10 y = 20 }
\t\t\tsize = { x=1024 y=768 }
\t\t\tinstantTextBoxType = { name = "label" position = { x = 390 y = 52 }
\t\t\t\ttext = "POLITICS_SOCIAL_REFORMS" maxWidth = 290 maxHeight = 20 format = centre }
\t\t\twindowType = {
\t\t\t\tname = "slavery"
\t\t\t\tposition = { x = 834 y = 262 }
\t\t\t\ticonType = { name = "icon" spriteType = "GFX_politics_slavery"
\t\t\t\t\tposition = { x = -10 y = 7 } Orientation = "UPPER_RIGHT" }
\t\t\t}
\t\t}
\t}
\twindowType = {
\t\tname = "reform_option_window"
\t\tsize = { x=130 y=14 }
\t\tguiButtonType = { name = "reform_option" quadTextureSprite = "GFX_select" buttonText = "" }
\t}
}
"""


@pytest.fixture
def ws(tmp_path):
    p = tmp_path / "game/interface/country_politics.gui"
    p.parent.mkdir(parents=True)
    p.write_bytes(GUI.encode("latin-1"))
    return Workspace.open(tmp_path / "game")


def test_window_tree(ws):
    w = gui_tree.read_window(ws, "interface/country_politics.gui", "reforms_window")
    assert (w.kind, w.x, w.y, w.w, w.h) == ("windowtype", 10, 20, 1024, 768)
    label, box = w.children
    assert (label.kind, label.text, label.max_w, label.format) == (
        "instanttextboxtype",
        "POLITICS_SOCIAL_REFORMS",
        290,
        "centre",
    )
    icon = box.children[0]
    assert (icon.sprite, icon.orientation, icon.x) == ("GFX_politics_slavery", "upper_right", -10)
    assert gui_tree.sprites_of(w) == {"GFX_politics_slavery"}
    row = gui_tree.read_window(ws, "interface/country_politics.gui", "reform_option_window")
    assert row.children[0].sprite == "GFX_select"
    with pytest.raises(ValueError):
        gui_tree.read_window(ws, "interface/country_politics.gui", "nothing")


def test_backdrop_is_relative_to_the_window(ws):
    behind = gui_tree.backdrop(ws, "interface/country_politics.gui", "reforms_window")
    assert [(e.name, e.x, e.y) for e in behind] == [("bg", -80, -90), ("chart", 85, 84)]


def test_texture_size(tmp_path: Path):
    dds = bytearray(128)
    dds[:4] = b"DDS "
    dds[12:16] = (32).to_bytes(4, "little")  # height
    dds[16:20] = (288).to_bytes(4, "little")  # width
    (tmp_path / "a.dds").write_bytes(bytes(dds))
    tga = bytearray(18)
    tga[2] = 2
    tga[12:14] = (64).to_bytes(2, "little")
    tga[14:16] = (16).to_bytes(2, "little")
    (tmp_path / "b.tga").write_bytes(bytes(tga))
    assert gui_tree.texture_size(tmp_path / "a.dds") == (288, 32)
    assert gui_tree.texture_size(tmp_path / "b.tga") == (64, 16)
    assert gui_tree.texture_size(tmp_path / "missing.dds") is None


def test_windows_and_planned_moves(ws, tmp_path):
    rel = "interface/country_politics.gui"
    found = gui_tree.windows(ws, rel)
    assert [(n, d) for n, _, d in found] == [
        ("country_politics", 0),
        ("reforms_window", 1),
        ("slavery", 2),
        ("reform_option_window", 0),
    ]
    with pytest.raises(ValueError, match="mod folder"):
        gui_tree.plan_changes(ws, rel, {})
    mod_ws = Workspace.open(tmp_path / "game", tmp_path / "mod")
    slavery = next(line for n, line, _ in found if n == "slavery")
    button = gui_tree.read_window(mod_ws, rel, "reform_option_window").children[0]
    change = gui_tree.plan_changes(
        mod_ws, rel, {slavery: {"x": 800, "w": 200, "h": 90}, button.line: {"y": 5}}
    )
    assert change.path == tmp_path / "mod" / rel
    assert "position = { x = 800 y = 262 }" in change.new_text
    assert "size = { x = 200 y = 90 }" in change.new_text  # added: the box had no size
    assert "position = { x = 0 y = 5 }" in change.new_text
    with pytest.raises(ValueError, match="no element"):
        gui_tree.plan_changes(mod_ws, rel, {9999: {"x": 1}})
