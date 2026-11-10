"""Light formatting (T011, K91 = A): indentation, spaces around =, line ends, empty lines."""

import pytest

from vic2toolmod.format import FormatError, changed_lines, format_mod, format_text
from vic2toolmod.server.app import ApiError, Engine
from vic2toolmod.workspace import Workspace

MESSY = (
    "\n\n# head  \n"
    "country_event={\n"
    "    id=5 # five \n"
    "  trigger = {   tag   =ENG}\n"
    "\n\n\n"
    "\toption = {\n"
    ' name = "A  =  B"   \n'
    "\t\t}   \n"
    "  }\n\n\n"
)
TIDY = (
    "# head\n"
    "country_event = {\n"
    "\tid = 5 # five\n"
    "\ttrigger = {   tag = ENG}\n"
    "\n"
    "\toption = {\n"
    '\t\tname = "A  =  B"\n'
    "\t}\n"
    "}\n"
)


def test_light_style():
    assert format_text(MESSY) == TIDY
    assert format_text(TIDY) == TIDY  # nothing more to do
    # line breaks stay, so one-line blocks stay one-line; CRLF stays CRLF
    assert format_text("a={ 1  2   3 }\r\nb  >=  3\r\n\r\n\r\nc = d") == (
        "a = { 1  2   3 }\r\nb >= 3\r\n\r\nc = d"
    )
    # a comment inside a block before its "}" keeps the block's depth
    assert format_text("a = {\nb = c\n# last\n}\n") == "a = {\n\tb = c\n\t# last\n}\n"


def test_refuses_what_it_cannot_do_safely():
    with pytest.raises(FormatError, match="'\\{' without"):
        format_text("a = {\n b = c\n")
    with pytest.raises(FormatError, match="too many"):
        format_text("a = b }\n")
    with pytest.raises(FormatError, match="closing quote"):
        format_text('a = "open\n')


def test_changed_lines():
    assert changed_lines(MESSY, TIDY) == 13  # 6 empty lines gone, 7 lines changed
    assert changed_lines(TIDY, TIDY) == 0


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("cp1252"))


def make(tmp_path):
    game = tmp_path / "game"
    write(game / "events/vanilla.txt", "x=1\n")  # a game file: never formatted
    mod = tmp_path / "mod"
    write(mod / "events/a.txt", MESSY)
    write(mod / "events/b.txt", TIDY)
    write(mod / "interface/w.gui", 'guiTypes={\nwindowType={ name = "w" }\n}\n')
    write(mod / "events/broken.txt", "a = {\n")
    write(mod / "localisation/x.csv", "KEY;x=1;\n")  # not a script file
    return Workspace.open(game, mod)


def test_format_mod(tmp_path):
    ws = make(tmp_path)
    plan = format_mod(ws)
    assert sorted(c.rel for c in plan.changes) == ["events/a.txt", "interface/w.gui"]
    assert plan.same == 1 and list(plan.skipped) == ["events/broken.txt"]
    assert plan.lines["events/a.txt"] == 13
    ws.set_text("events/a.txt", MESSY + "# typing\n")
    plan = format_mod(ws)
    assert plan.skipped["events/a.txt"] == "unsaved changes in the editor"
    assert format_mod(ws, ["interface/w.gui"]).changes[0].new_text == (
        'guiTypes = {\n\twindowType = { name = "w" }\n}\n'
    )


def test_api(tmp_path):
    ws = make(tmp_path)
    engine = Engine(ws)
    assert engine.format_text(MESSY) == {"text": TIDY}
    with pytest.raises(ApiError):
        engine.format_text("a = {")
    plan = engine.format_plan()
    assert {f["rel"] for f in plan["files"]} == {"events/a.txt", "interface/w.gui"}
    assert plan["skipped"][0]["rel"] == "events/broken.txt"
    assert "+\tid = 5 # five" in engine.format_diff("events/a.txt")["diff"]
    done = engine.format_write(["events/a.txt"])
    assert done["written"] == 1 and done["backup"]
    assert (tmp_path / "mod/events/a.txt").read_bytes() == TIDY.encode("cp1252")
    assert (tmp_path / "mod/interface/w.gui").read_text().startswith("guiTypes={")  # not chosen
    assert (tmp_path / "game/events/vanilla.txt").read_text() == "x=1\n"
    engine.format_plan()
    (tmp_path / "mod/interface/w.gui").write_text("guiTypes={ }\n")  # changed after the plan
    with pytest.raises(ApiError, match="changed since the plan"):
        engine.format_write(["interface/w.gui"])
