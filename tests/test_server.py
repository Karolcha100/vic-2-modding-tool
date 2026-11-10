import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from vic2toolmod.server import make_server
from vic2toolmod.workspace import Workspace


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("latin-1"))


@pytest.fixture
def api(tmp_path):
    g = tmp_path / "game"
    write(g / "common/countries.txt", 'ENG = "countries/UK.txt"\n')
    write(g / "events/a.txt", "country_event = { id = 1 trigger = { tag = ENG } }\n")
    mod = tmp_path / "mod"
    write(mod / "events/b.txt", "country_event = { id = 2 colour = red }\n")
    server, token = make_server(Workspace.open(g, mod))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, body=None, token_=token):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data, headers={"X-Token": token_})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    call.base = base
    call.mod = mod
    yield call
    server.shutdown()
    server.server_close()


def test_token_required(api):
    with pytest.raises(urllib.error.HTTPError) as info:
        api("/api/project", token_="wrong")
    assert info.value.code == 403


def test_project_file_and_check(api):
    files = {f["rel"]: f["origin"] for f in api("/api/project")["files"]}
    assert files["events/a.txt"] == "game" and files["events/b.txt"] == "mod"
    f = api("/api/file?rel=events/b.txt")
    assert f["encoding"] == "cp1252"
    assert [d["code"] for d in f["diagnostics"]] == ["schema.unknown-key"]
    assert [x["rel"] for x in api("/api/check")["files"]] == ["events/b.txt"]


def test_buffer_complete_hover_definition(api):
    r = api(
        "/api/buffer",
        {"rel": "events/b.txt", "text": "country_event = { id = 2 trigger = { tag = E } }"},
    )
    assert [d["code"] for d in r["diagnostics"]] == ["schema.wrong-value"]  # "E" is no tag
    offset = len("country_event = { id = 2 trigger = { tag = E")
    labels = [c["label"] for c in api(f"/api/complete?rel=events/b.txt&offset={offset}")["items"]]
    assert labels == ["ENG"]
    at = len("country_event = { id = 1 trigger = { tag = E")
    d = api(f"/api/definition?rel=events/a.txt&offset={at}")
    assert d["definition"]["file"] == "common/countries.txt"


def test_save_writes_into_mod_with_backup(api, tmp_path, monkeypatch):
    monkeypatch.setattr("vic2toolmod.changes.backup_dir", lambda: tmp_path / "backup")
    r = api("/api/save", {"rel": "events/a.txt", "text": "country_event = { id = 1 }\n"})
    assert (api.mod / "events/a.txt").read_text() == "country_event = { id = 1 }\n"
    assert r["backup"] is None  # the mod had no such file before
    r = api("/api/save", {"rel": "events/b.txt", "text": "country_event = { id = 3 }\n"})
    assert Path(r["backup"], "events/b.txt").read_text().startswith("country_event = { id = 2")
    with pytest.raises(urllib.error.HTTPError) as info:
        api("/api/save", {"rel": "events/b.txt", "text": "name = Łódź"})
    assert info.value.code == 422


def test_changed_and_static(api):
    first = api("/api/changed")
    assert first["changed"] == [] and first["stale"] is False
    (api.mod / "events/c.txt").write_text("country_event = { id = 9 }\n")
    assert api("/api/changed")["changed"] == ["events/c.txt"]
    with urllib.request.urlopen(api.base + "/") as r:
        assert b"vic2toolmod" in r.read()


def test_trigger_and_localisation_endpoints(api):
    text = "country_event = { id = 2 trigger = { tag = ENG war = no } }"
    api("/api/buffer", {"rel": "events/b.txt", "text": text})
    at = text.index("war")
    r = api("/api/trigger", {"rel": "events/b.txt", "offset": at})
    assert [f["key"] for f in r["facts"]] == ["tag", "war"] and r["result"] is None
    r = api(
        "/api/trigger", {"rel": "events/b.txt", "offset": at, "answers": {"0": "ENG", "1": "yes"}}
    )
    assert r["result"]["value"] is False and r["result"]["failed"] == ["1"]
    r = api("/api/localisation", {"key": "K1", "english": "Hello"})
    assert "+K1;Hello" in r["diff"]
    assert "files" in api("/api/vanilla/diff") and "nodes" in api("/api/events/graph")


def test_file_drops_old_editor_buffer(api):
    api("/api/buffer", {"rel": "events/b.txt", "text": "country_event = { id = 77 }"})
    assert "id = 2" in api("/api/file?rel=events/b.txt")["text"]  # disk, not the stale buffer


def test_blocks_and_edit(api):
    api(
        "/api/buffer",
        {
            "rel": "events/b.txt",
            "text": "country_event = {\n\tid = 2\n\ttrigger = { war = no }\n}\n",
        },
    )
    items = api("/api/blocks?rel=events/b.txt")["items"]
    ev = items[0]
    assert ev["key"] == "country_event" and ev["block"] and ev["context"] == "event"
    war = ev["children"][1]["children"][0]
    assert (war["key"], war["role"], war["value_kind"], war["choices"]) == (
        "war",
        "trigger",
        "bool",
        ["yes", "no"],
    )
    r = api(
        "/api/edit", {"rel": "events/b.txt", "op": "set", "start": war["start"], "value": "yes"}
    )
    assert r["edits"][0]["new_text"] == "yes"
    r = api(
        "/api/edit",
        {
            "rel": "events/b.txt",
            "op": "insert",
            "parent": ev["children"][1]["lbrace"],
            "key": "tag",
            "value": "ENG",
        },
    )
    assert r["edits"][0]["new_text"].strip() == "tag = ENG"
    r = api(
        "/api/edit", {"rel": "events/b.txt", "op": "delete", "start": ev["children"][1]["start"]}
    )
    assert r["edits"][0]["new_text"] == ""


def test_template_endpoints(api, tmp_path, monkeypatch):
    monkeypatch.setattr("vic2toolmod.generators.templates.user_dir", lambda: tmp_path / "tpl")
    r = api("/api/templates")
    ids = [t["id"] for t in r["templates"]]
    assert "builtin/event_chain" in ids and r["dir"] == str(tmp_path / "tpl")
    r = api("/api/template?id=builtin/event_chain&file=events/b.txt")
    assert (r["defaults"]["first"], r["defaults"]["second"]) == ("3", "4")
    api("/api/template/save", {"name": "Tag", "body": "tag = {{t:ref:country}}\n"})
    assert "ENG" in [c.upper() for c in api("/api/template?id=own/tag")["choices"]["t"]]
    r = api("/api/template/fill", {"id": "own/tag", "values": {"t": "ENG"}})
    assert r["text"] == "tag = ENG\n" and r["files"] == [] and r["notes"] == []
    r = api("/api/template/fill", {"id": "own/tag", "values": {"t": "ENG"}, "file": "events/b.txt"})
    assert r["files"] == ["events/b.txt"] and "+tag = ENG" in r["diff"]
    api("/api/template/delete", {"id": "own/tag"})
    with pytest.raises(urllib.error.HTTPError) as info:
        api("/api/template/delete", {"id": "builtin/event_chain"})
    assert info.value.code == 422


def test_create_country_endpoint(api, tmp_path, monkeypatch):
    monkeypatch.setattr("vic2toolmod.changes.backup_dir", lambda: tmp_path / "backup")
    write(tmp_path / "game/common/countries/UK.txt", "color = { 1 2 3 }\n")
    write(tmp_path / "game/gfx/flags/ENG.tga", "flag")
    api("/api/changed")  # the engine notices the new files
    spec = {
        "tag": "BOE",
        "name": "Boer",
        "adjective": "Boer",
        "template": "ENG",
        "color": [1, 2, 3],
    }
    r = api("/api/create/country", {"spec": spec})
    assert "gfx/flags/BOE.tga" in r["files"] and not (api.mod / "gfx/flags/BOE.tga").exists()
    r = api("/api/create/country", {"spec": spec, "write": True})
    assert (api.mod / "gfx/flags/BOE.tga").read_bytes() == b"flag"
    assert 'BOE\t= "countries/Boer.txt"' in (api.mod / "common/countries.txt").read_text()


def test_open_another_project_and_read_only_game(api, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    # a second mod, registered in the game's mod/ folder like the launcher does
    other = tmp_path / "game" / "mod" / "Other"
    write(other / "events/c.txt", "country_event = { id = 3 }\n")
    write(tmp_path / "game" / "mod" / "Other.mod", 'name = "Other mod"\npath = "mod/Other"\n')
    listed = api("/api/projects")
    assert listed["current"] == str(api.mod)
    assert {"name": "Other mod", "path": str(other), "source": "game"} in listed["mods"]

    api("/api/project/open", {"mod": str(other)})
    project = api("/api/project")
    assert project["mod_dir"] == str(other) and not project["read_only"]
    assert "events/c.txt" in {f["rel"] for f in project["files"]}
    assert api("/api/projects")["recent"] == [str(other)]

    # the game alone: everything readable, nothing writable
    api("/api/project/open", {"mod": None})
    assert api("/api/project")["read_only"]
    assert api("/api/file?rel=events/a.txt")["text"].startswith("country_event")
    with pytest.raises(urllib.error.HTTPError) as err:
        api("/api/save", {"rel": "events/a.txt", "text": "x = 1\n"})
    assert err.value.code == 409


def test_gui_window_endpoints(api, tmp_path, monkeypatch):
    monkeypatch.setattr("vic2toolmod.changes.backup_dir", lambda: tmp_path / "backup")
    write(
        api.mod / "interface/x.gui",
        'guiTypes = { windowType = { name = "w" size = { x = 100 y = 50 }\n'
        'iconType = { name = "i" spriteType = "GFX_i" position = { x = 1 y = 2 } } } }\n',
    )
    api("/api/changed")
    assert api("/api/gui/windows?rel=interface/x.gui")["windows"] == [
        {"name": "w", "line": 1, "depth": 0}
    ]
    w = api("/api/gui/window?rel=interface/x.gui&name=w")
    icon = w["tree"]["children"][0]
    assert (icon["name"], icon["x"], icon["sprite"]) == ("i", 1, "GFX_i")
    assert w["sprites"] == {"GFX_i": {"frames": 0, "w": 0, "h": 0, "found": False}}
    plan = api("/api/gui/plan", {"rel": "interface/x.gui", "changes": {"2": {"x": 7}}})
    assert "+iconType = { name" in plan["diff"] and "x = 7 y = 2" in plan["diff"]
    api("/api/gui/plan", {"rel": "interface/x.gui", "changes": {"2": {"x": 7}}, "write": True})
    assert "position = { x = 7 y = 2 }" in (api.mod / "interface/x.gui").read_text()
