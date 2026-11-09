"""Light Python scripts (T007): header, ModApi, built-in scripts, CLI and API."""

import pytest

from vic2toolmod.cli import main
from vic2toolmod.pyscripts import (
    ScriptError,
    delete_script,
    get_script,
    list_scripts,
    parse_script,
    run,
    save_script,
    values,
)
from vic2toolmod.server.app import ApiError, Engine
from vic2toolmod.workspace import Workspace

EVENTS = (
    "country_event = {\r\n\tid = 1\r\n\ttrigger = { has_country_flag = CT_regional_elects_a }\r\n"
    "\tmean_time_to_happen = { months = 12 }\r\n\toption = { name = A }\r\n}\r\n"
    "country_event = {\r\n\tid = 2 # keep\r\n"
    "\ttrigger = { has_country_flag = CT_regional_elects_b }\r\n"
    "\tmean_time_to_happen = { months = 6 }\r\n}\r\n"
)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("cp1252"))


def make(tmp_path):
    g = tmp_path / "game"
    write(g / "events/vanilla.txt", "country_event = { id = 100 months = 3 }\n")
    mod = tmp_path / "mod"
    write(mod / "events/501_Tribunal.txt", EVENTS)
    write(mod / "events/other.txt", "# CT_regional_elects_ in a comment\n")
    return Workspace.open(g, mod)


def test_header_fields():
    s = parse_script(
        "own/x",
        "#@ name: X\n# @ description: D\n#@ param: files = events/*.txt | which files\n"
        "#@ param: n:int = 3\n#@ param: on:bool = no\n#@ param: text\nprint(1)\n#@ param: late\n",
    )
    assert (s.name, s.description) == ("X", "D")
    assert [(p.name, p.type, p.default, p.help) for p in s.params] == [
        ("files", "text", "events/*.txt", "which files"),
        ("n", "int", "3", ""),
        ("on", "bool", "no", ""),
        ("text", "text", "", ""),
    ]  # the header ends at the first line of code
    assert values(s, {"n": "5", "on": "yes"}) == {
        "files": "events/*.txt",
        "n": 5,
        "on": True,
        "text": "",
    }
    with pytest.raises(ScriptError, match="whole number"):
        values(s, {"n": "x"})
    with pytest.raises(ScriptError, match="unknown field"):
        values(s, {"nope": "1"})
    with pytest.raises(ScriptError, match="unknown type"):
        parse_script("own/y", "#@ param: a:float\n")


def test_replace_plans_without_writing(tmp_path):
    ws = make(tmp_path)
    s = get_script("replace_text", tmp_path / "own")
    r = run(
        ws,
        s,
        {"files": "events/501_*.txt", "old": "CT_regional_elects_", "new": "CT_ruling_elects_"},
    )
    assert r.error == ""
    assert "2 replacement(s) in 1 file(s)" in r.output
    assert [c.rel for c in r.changes] == ["events/501_Tribunal.txt"]
    new = r.changes[0].new_text
    assert new == EVENTS.replace("CT_regional_elects_", "CT_ruling_elects_")  # CRLF kept
    assert "regional" in (tmp_path / "mod/events/501_Tribunal.txt").read_text()  # not written


def test_set_value_uses_the_syntax_tree(tmp_path):
    ws = make(tmp_path)
    s = get_script("set_value", tmp_path / "own")
    r = run(
        ws, s, {"key": "months", "inside": "mean_time_to_happen", "only_if": "12", "value": "24"}
    )
    assert r.error == "" and "1 value(s) changed" in r.output
    assert r.changes[0].new_text == EVENTS.replace("months = 12", "months = 24")
    # game files are not touched unless asked for
    assert all(c.rel.startswith("events/501") for c in r.changes)


def test_find_and_errors(tmp_path):
    ws = make(tmp_path)
    r = run(ws, get_script("find_text", tmp_path / "own"), {"text": "CT_regional"})
    assert "3 line(s) in 2 file(s)" in r.output and not r.changes
    r = run(ws, get_script("find_text", tmp_path / "own"), {"text": "months", "game": "yes"})
    assert "events/vanilla.txt:1:" in r.output
    bad = parse_script(
        "own/bad", "x = 1\nmod.write('events/a.txt', 'a')\nraise ValueError('boom')\n"
    )
    r = run(ws, bad)
    assert r.error.startswith("ValueError: boom") and "line 3" in r.error
    r = run(ws, parse_script("own/syntax", "if :\n"))
    assert r.error.startswith("SyntaxError")
    r = run(ws, parse_script("own/out", "mod.write('../x.txt', 'a')\n"))
    assert "bad file name" in r.error


def test_unsaved_editor_text_blocks_writing(tmp_path):
    ws = make(tmp_path)
    ws.set_text("events/501_Tribunal.txt", EVENTS + "# typing\r\n")
    code = "mod.replace('CT_regional', 'CT_ruling', files='events/501*')\n"
    r = run(ws, parse_script("own/x", code))
    assert "unsaved changes" in r.error
    ws.set_text("events/501_Tribunal.txt", EVENTS)  # same as on disk: fine
    assert run(ws, parse_script("own/x", code)).error == ""


def test_read_sees_planned_changes_and_game_copy(tmp_path):
    ws = make(tmp_path)
    code = (
        "mod.write('events/vanilla.txt', mod.read('events/vanilla.txt').replace('3', '4'))\n"
        "print(mod.read('events/vanilla.txt').strip())\n"
        "mod.write('events/new.txt', 'a = 1\\n')\n"
        "print(len(mod.names('event')))\n"
    )
    r = run(ws, parse_script("own/x", code))
    assert r.error == "", r.error
    assert r.output.splitlines() == ["country_event = { id = 100 months = 4 }", "3"]
    old = {c.rel: c.old_text for c in r.changes}
    assert old == {"events/vanilla.txt": None, "events/new.txt": None}  # both new in the mod
    assert {c.path for c in r.changes} == {
        tmp_path / "mod/events/vanilla.txt",
        tmp_path / "mod/events/new.txt",
    }


def test_own_scripts(tmp_path):
    own = tmp_path / "own"
    s = save_script("Fix Flags!", "print('hi')\n", own=own)
    assert s.id == "own/fix_flags" and (own / "fix_flags.py").read_text().startswith(
        "#@ name: Fix Flags!"
    )
    with pytest.raises(ScriptError, match="already exists"):
        save_script("Fix flags", "print(1)\n", own=own)
    with pytest.raises(SyntaxError):
        save_script("Broken", "if :\n", own=own)
    assert [x.id for x in list_scripts(own) if not x.builtin] == ["own/fix_flags"]
    assert {"builtin/replace_text", "builtin/find_text", "builtin/set_value"} <= {
        x.id for x in list_scripts(own)
    }
    with pytest.raises(ScriptError):
        delete_script("builtin/replace_text", own)
    delete_script("own/fix_flags", own)
    assert not (own / "fix_flags.py").exists()


def test_cli_preview_and_write(tmp_path, capsys):
    make(tmp_path)
    args = [
        "run-script",
        "replace_text",
        "--game",
        str(tmp_path / "game"),
        "--mod",
        str(tmp_path / "mod"),
        "-p",
        "files=events/501_*.txt",
        "-p",
        "old=CT_regional_elects_",
        "-p",
        "new=CT_ruling_elects_",
    ]
    assert main(args) == 0
    out = capsys.readouterr()
    assert "+\ttrigger = { has_country_flag = CT_ruling_elects_a }" in out.out
    assert "dry run" in out.err
    target = tmp_path / "mod/events/501_Tribunal.txt"
    assert b"regional" in target.read_bytes()
    assert main([*args, "--write"]) == 0
    assert target.read_bytes() == EVENTS.replace("regional", "ruling").encode("cp1252")


def test_api_run_and_write(tmp_path):
    ws = make(tmp_path)
    engine = Engine(ws, scripts_dir=tmp_path / "own")
    listed = engine.scripts()["scripts"]
    assert any(
        s["id"] == "builtin/replace_text" and s["params"][0]["name"] == "files" for s in listed
    )
    body = {
        "id": "builtin/replace_text",
        "values": {"files": "events/501_*.txt", "old": "regional", "new": "ruling"},
    }
    preview = engine.script_run(body)
    assert preview["files"] == ["events/501_Tribunal.txt"] and "written" not in preview
    ws.set_text("events/501_Tribunal.txt", EVENTS)  # the file is open (unchanged) in the editor
    done = engine.script_run({**body, "write": True})
    assert done["written"] and done["backup"]
    assert ws.document("events/501_Tribunal.txt").text == EVENTS.replace("regional", "ruling")
    edited = engine.script_run({"id": "edited", "code": "print(params)\n", "values": {}})
    assert edited["output"] == "{}\n"
    with pytest.raises(ApiError):
        engine.script_run({"id": "builtin/nope", "values": {}})
    saved = engine.script_save({"name": "Mine", "code": "print(2)\n"})
    assert engine.script_run({"id": saved["id"], "values": {}})["output"] == "2\n"
    assert engine.script_delete(saved["id"]) == {"deleted": "own/mine"}
