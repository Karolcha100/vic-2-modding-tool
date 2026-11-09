import pytest

from vic2toolmod.generators.templates import (
    defaults,
    delete_template,
    fill,
    get_template,
    list_templates,
    parse_template,
    save_template,
)
from vic2toolmod.script import parse_text
from vic2toolmod.workspace import Workspace


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("latin-1"))


def make(tmp_path):
    g = tmp_path / "game"
    write(g / "events/a.txt", "country_event = { id = 100 }\n")
    write(g / "common/countries.txt", 'ENG = "countries/England.txt"\n')
    write(g / "common/countries/England.txt", "color = { 1 2 3 }\n")
    (tmp_path / "mod").mkdir()
    return Workspace.open(g, tmp_path / "mod")


def test_fields_and_header():
    t = parse_template(
        "own/x",
        "#@ name: X\n#@ folder: events\n#@ loc: K{{id}} = {{title}}\n"
        "a = {{id:event_id}}\nb = {{id}}\nc = {{n:int=3}}\nd = {{n}}\n",
    )
    assert (t.name, t.folder, t.loc) == ("X", "events", ["K{{id}} = {{title}}"])
    assert [(f.name, f.type, f.default) for f in t.fields] == [
        ("id", "event_id", ""),
        ("n", "int", "3"),
        ("title", "text", ""),
    ]


def test_builtin_templates_fill_and_parse(tmp_path):
    ws = make(tmp_path)
    builtins = [t for t in list_templates(tmp_path / "none") if t.builtin]
    assert len(builtins) >= 5
    for t in builtins:
        values = defaults(ws, t)
        values = {k: v or "x" for k, v in values.items()}
        result = fill(ws, t, values)
        doc = parse_text(result.text)
        assert not doc.diagnostics, (t.id, doc.diagnostics)
        assert "{{" not in result.text


def test_two_free_event_ids(tmp_path):
    ws = make(tmp_path)
    t = get_template("builtin/event_chain", tmp_path / "none")
    values = defaults(ws, t)
    assert (values["first"], values["second"]) == ("101", "102")
    values.update(first_title="A", first_description="B", second_title="C", second_description="D")
    result = fill(ws, t, values, file="events/chain.txt")
    files = {c.rel: c.new_text for c in result.changes}
    assert "country_event = { id = 102 days = 30 }" in files["events/chain.txt"]
    assert "\r\n" in files["events/chain.txt"]
    assert "EVTNAME102;C;" in files["localisation/00_vic2toolmod.csv"]


def test_append_to_existing_file_and_checks(tmp_path):
    ws = make(tmp_path)
    t = parse_template("own/y", "x = {{tag:ref:country}}\nn = {{n:int}}\n")
    result = fill(ws, t, {"tag": "ENG", "n": "5"}, file="events/a.txt")
    (change,) = result.changes
    assert change.new_text == "country_event = { id = 100 }\n\nx = ENG\nn = 5\n"
    assert not result.notes
    assert fill(ws, t, {"tag": "XXX", "n": "1"}).notes == [
        "tag: country 'XXX' does not exist (yet)"
    ]
    with pytest.raises(ValueError, match="n: a whole number"):
        fill(ws, t, {"tag": "ENG", "n": "five"})
    with pytest.raises(ValueError, match="bad file name"):
        fill(ws, t, {"tag": "ENG", "n": "1"}, file="../x.txt")


def test_own_templates(tmp_path):
    own = tmp_path / "templates"
    t = save_template("My Event!", "a = {{v}}\n", "desc", "events", ["K = {{v}}"], own=own)
    assert t.id == "own/my_event"
    again = get_template("own/my_event", own)
    assert (again.name, again.description, again.loc, again.body) == (
        "My Event!",
        "desc",
        ["K = {{v}}"],
        "a = {{v}}\n",
    )
    with pytest.raises(ValueError, match="already exists"):
        save_template("My Event", "b\n", own=own)
    with pytest.raises(ValueError, match="unknown type"):
        save_template("Bad", "a = {{v:colour}}\n", own=own)
    with pytest.raises(ValueError, match="only your own"):
        delete_template("builtin/event_chain", own)
    delete_template("own/my_event", own)
    assert not [x for x in list_templates(own) if not x.builtin]
