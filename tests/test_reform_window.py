from pathlib import Path

from vic2toolmod.analysis.reform_window import grid, plan_layout, read_layout
from vic2toolmod.script import parse_text
from vic2toolmod.workspace import Workspace

GUI = """guiTypes = {
\twindowType = {
\t\tname = "reforms_window"
\t\tposition = { x = 0 y = 0 }
\t\tsize = { x=1024 y=768 }
\t\twindowType = {
\t\t\tname = "slavery"
\t\t\tposition = { x = 834 y = 262 }
\t\t\tsize = { x=310 y=100 }
\t\t}
\t\twindowType = {
\t\t\tname = "wage_reform"
\t\t\tposition = { x = 1100 y = 58 }
\t\t\tsize = { x=310 y=100 }
\t\t}
\t\twindowType = {
\t\t\tname = "old_thing"
\t\t\tposition = { x = 10 y = 10 }
\t\t}
\t}
}
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", "\r\n").encode("latin-1"))


def make(tmp_path):
    g = tmp_path / "game"
    write(g / "interface/country_politics.gui", GUI)
    write(
        g / "common/issues.txt",
        "political_reforms = { slavery = { } press_rights = { } }\n"
        "social_reforms = { wage_reform = { } }\n",
    )
    return Workspace.open(g, tmp_path / "mod")


def test_read_layout(tmp_path):
    layout = read_layout(make(tmp_path))
    assert (layout.width, layout.height) == (1024, 768)
    boxes = {b.name: b for b in layout.boxes}
    assert boxes["slavery"].category == "political_reforms" and boxes["slavery"].clipped
    assert boxes["wage_reform"].outside
    assert layout.missing == {"political_reforms": ["press_rights"]}
    assert layout.unknown == ["old_thing"]


def test_grid_and_plan(tmp_path):
    ws = make(tmp_path)
    pos = grid(["slavery", "press_rights"], origin=(400, 60), columns=2, cell=(150, 90))
    assert pos == {"slavery": (400, 60), "press_rights": (550, 60)}
    change = plan_layout(ws, pos)
    new = change.new_text
    assert "position = { x = 400 y = 60 }" in new
    assert 'name = "press_rights"' in new and "position = { x = 550 y = 60 }" in new
    assert "\r\n" in new and "\n" not in new.replace("\r\n", "")  # keeps CRLF
    doc = parse_text(new)
    assert doc.diagnostics == []
    assert change.path == tmp_path / "mod" / "interface/country_politics.gui"
