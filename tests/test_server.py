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
    assert api("/api/changed") == {"changed": []}
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
