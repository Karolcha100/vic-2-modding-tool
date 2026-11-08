from pathlib import Path

import pytest

from vic2toolmod.project import Project, build_registries
from vic2toolmod.project.defines import DefinesError, parse_defines
from vic2toolmod.project.events import declared_range, next_free_id
from vic2toolmod.project.localisation import load_localisation
from vic2toolmod.workspace import Workspace


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("latin-1"))


@pytest.fixture
def game(tmp_path):
    g = tmp_path / "game"
    write(g / "common/countries.txt", 'ENG = "countries/UK.txt"\nFRA = "countries/France.txt"\n')
    write(g / "localisation/text.csv", "EVTNAME1;Old title;;;;;;;;;;;;;x\nB_KEY;B;;;;;;;;;;;;;x\n")
    write(g / "localisation/00_mod.csv", "EVTNAME1;New title;;;;;;;;;;;;;x\n#comment\n;;;\n")
    write(
        g / "events/a.txt",
        (
            "### Events 1-5 used\n"
            "country_event = { id = 1 title = EVTNAME1 desc = EVTDESC1 "
            "trigger = { has_country_flag = f } "
            'option = { name = "Fine!" set_country_flag = g ENG = { prestige = 1 } } }\n'
            'country_event = { id = 2 title = "Some text" option = { name = OK } }\n'
        ),
    )
    write(g / "events/b.txt", "country_event = { id = 2 }\n")
    return g


def test_localisation_first_definition_wins(game):
    loc = load_localisation(Project.open(game))
    assert loc.get("evtname1").text() == "New title"  # 00_mod.csv sorts before text.csv
    assert [e.file for e in loc.shadowed] == ["localisation/text.csv"]
    assert "B_KEY" in loc and "#comment" not in loc


def test_flags_and_duplicates(game):
    reg = build_registries(Project.open(game))
    assert reg.has("country_flag", "g") and not reg.has("country_flag", "f")
    assert reg.tested["country_flag"]["f"].file == "events/a.txt"
    assert [(d.name, d.file) for d in reg.duplicates["event"]] == [("2", "events/b.txt")]


def test_free_event_ids(game):
    reg = build_registries(Project.open(game))
    text = (game / "events/a.txt").read_text()
    assert declared_range(text) == (1, 5)
    assert next_free_id(reg, text) == 3
    assert next_free_id(reg) == 3  # no range: highest + 1
    assert declared_range("country_event = { id = 1 }") is None


def test_workspace_check_and_navigation(game):
    ws = Workspace.open(game)
    codes = {(r.file.rel, d.code) for r in ws.check() for d in r.diagnostics}
    assert ("events/a.txt", "ref.flag-never-set") in codes  # f is tested, never set
    assert ("events/a.txt", "loc.missing") in codes  # EVTDESC1
    assert ("events/b.txt", "ref.duplicate-id") in codes
    msgs = [d.message for r in ws.check() for d in r.diagnostics]
    assert not any("Fine!" in m or "Some text" in m for m in msgs)  # literal text, not keys
    assert ws.definition("country", "eng").file == "common/countries.txt"
    usages = ws.usages("country", "ENG")
    assert [(u.file, u.line) for u in usages] == [("events/a.txt", 2)]
    assert ws.usages("localisation", "evtname1")[0].file == "events/a.txt"


def test_workspace_editor_buffer(game):
    ws = Workspace.open(game)
    ws.set_text("events/b.txt", "country_event = { id = 9 option = { set_country_flag = f } }\n")
    assert ws.registries().has("event", "9")
    codes = {d.code for r in ws.check() for d in r.diagnostics}
    assert "ref.flag-never-set" not in codes and "ref.duplicate-id" not in codes
    ws.revert("events/b.txt")
    assert not ws.registries().has("event", "9")


def test_ignore_rules(tmp_path, game):
    mod = tmp_path / "mod"
    write(mod / "events/c.txt", "country_event = { id = 50 colour = red }\n")
    write(mod / "vic2toolmod.toml", 'ignore_codes = ["schema.unknown-key"]\n')
    ws = Workspace.open(game, mod)
    assert [d.code for r in ws.check() for d in r.diagnostics] == []


def test_defines():
    d = parse_defines(
        "defines = {\n start_date = '1836.1.1', -- c\n country = { A = 1, B = -0.5 },\n}\n"
    )
    assert d["defines"]["start_date"].value == "1836.1.1"
    assert d["defines"]["country"]["B"].value == -0.5
    assert d["defines"]["country"]["A"].line == 3
    with pytest.raises(DefinesError):
        parse_defines("defines = { a = }")
