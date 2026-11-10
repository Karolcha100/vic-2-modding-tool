"""Modifier groups (T008): finding, rewriting, API."""

import pytest

from vic2toolmod.analysis.modifier_groups import find_groups, rewrite, rewrite_edits
from vic2toolmod.edit import apply_edits
from vic2toolmod.schema.loader import default_schema
from vic2toolmod.script import parse_text
from vic2toolmod.server.app import ApiError, Engine
from vic2toolmod.workspace import Workspace

EVENT = (
    "country_event = {\r\n"
    "\tid = 7\r\n"
    "\tmean_time_to_happen = {\r\n"
    "\t\tmonths = 12\r\n"
    "\t\tmodifier = {\r\n\t\t\tfactor = 1.1\r\n\t\t\tnum_of_cities = 20 # small\r\n\t\t}\r\n"
    "\t\tmodifier = {\r\n\t\t\tfactor = 1.1\r\n\t\t\tnum_of_cities = 30\r\n\t\t}\r\n"
    "\t\tmodifier = { factor = 0.5 war = yes }\r\n"
    "\t\tmodifier = {\r\n\t\t\tfactor = 1.1\r\n\t\t\tnum_of_cities = 50\r\n\t\t}\r\n"
    "\t\tmodifier = { factor = 2 NOT = { literacy = 0.2 } is_greater_power = yes }\r\n"
    "\t\tmodifier = { factor = 3 NOT = { literacy = 0.4 } is_greater_power = yes }\r\n"
    "\t\tmodifier = { factor = 3 NOT = { literacy = 0.4 } is_greater_power = no }\r\n"
    "\t}\r\n"
    "}\r\n"
)


def groups(text, rel="events/a.txt"):
    return find_groups(parse_text(text), rel, default_schema())


def test_find():
    found = groups(EVENT)
    assert [(g.key, g.negated, len(g.steps)) for g in found] == [
        ("num_of_cities", False, 3),
        ("literacy", True, 2),
    ]
    cities, lit = found
    assert cities.path == ["country_event 7", "mean_time_to_happen"]
    assert (cities.base_key, cities.base, cities.combine, cities.compare) == (
        "months",
        "12",
        "multiply",
        "gte",
    )
    assert [(s.value, s.factor) for s in cities.steps] == [
        ("20", "1.1"),
        ("30", "1.1"),
        ("50", "1.1"),
    ]
    assert cities.steps[0].line == 5
    assert lit.context == ["is_greater_power = yes"]  # the "no" modifier is not part of it
    assert [(s.value, s.factor) for s in lit.steps] == [("0.2", "2"), ("0.4", "3")]


def test_one_value_or_one_modifier_is_no_group():
    text = "a = { modifier = { factor = 2 year = 1850 } modifier = { factor = 3 year = 1850 } }\n"
    assert groups(text) == []
    assert groups("a = { modifier = { factor = 2 year = 1850 } }\n") == []


def test_additive_files():
    text = (
        "promotion_chance = { factor = 0.4 group = {\n"
        + "".join(f"modifier = {{ factor = 0.03 literacy = {v} }}\n" for v in (0.1, 0.2))
        + "} }\n"
    )
    assert groups(text, "common/pop_types.txt")[0].combine == "add"
    assert groups(text, "events/x.txt")[0].combine == "multiply"


def test_rewrite_keeps_the_layout():
    doc = parse_text(EVENT)
    cities = find_groups(doc, "events/a.txt", default_schema())[0]
    new = apply_edits(doc.text, rewrite_edits(doc, cities, [("10", "1.2"), ("40", "1.5")]))
    again = find_groups(parse_text(new), "events/a.txt", default_schema())[0]
    assert [(s.value, s.factor) for s in again.steps] == [("10", "1.2"), ("40", "1.5")]
    assert "num_of_cities = 30" not in new and "num_of_cities = 50" not in new
    assert new.count("# small") == 2 and "\r\n" in new and "\n" not in new.replace("\r\n", "")
    assert "factor = 0.5 war = yes" in new
    # one-line modifiers stay one-line
    lit = find_groups(doc, "events/a.txt", default_schema())[1]
    new = apply_edits(
        doc.text, rewrite_edits(doc, lit, [("0.1", "1.5"), ("0.3", "2"), ("0.5", "4")])
    )
    assert (
        "\t\tmodifier = { factor = 1.5 NOT = { literacy = 0.1 } is_greater_power = yes }\r\n"
        "\t\tmodifier = { factor = 2 NOT = { literacy = 0.3 } is_greater_power = yes }\r\n"
        "\t\tmodifier = { factor = 4 NOT = { literacy = 0.5 } is_greater_power = yes }\r\n"
    ) in new
    # no steps: the group goes
    new = apply_edits(doc.text, rewrite_edits(doc, lit, []))
    assert "literacy = 0.2" not in new and "is_greater_power = no" in new
    with pytest.raises(ValueError, match="not a number"):
        rewrite_edits(doc, lit, [("x", "1")])


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("cp1252"))


def make(tmp_path):
    g = tmp_path / "game"
    write(g / "events/vanilla.txt", "x = 1\n")
    write(tmp_path / "mod/events/a.txt", EVENT)
    write(tmp_path / "mod/events/b.txt", EVENT.replace("id = 7", "id = 8"))
    return Workspace.open(g, tmp_path / "mod")


def test_rewrite_files_and_copies(tmp_path):
    ws = make(tmp_path)
    a = find_groups(ws.document("events/a.txt"), "events/a.txt", ws.schema)[0]
    b = find_groups(ws.document("events/b.txt"), "events/b.txt", ws.schema)[0]
    assert a.signature == b.signature  # copies: same block key, variable, conditions and steps
    steps = [("25", "1.3")]
    changes = rewrite(ws, [("events/a.txt", a.id, steps), ("events/b.txt", b.id, steps)])
    assert [c.rel for c in changes] == ["events/a.txt", "events/b.txt"]
    assert all("num_of_cities = 25" in c.new_text and "= 30" not in c.new_text for c in changes)
    with pytest.raises(ValueError, match="gone"):
        rewrite(ws, [("events/a.txt", "1:nope:x", steps)])
    ws.set_text("events/a.txt", EVENT + "# typing\r\n")
    with pytest.raises(ValueError, match="unsaved"):
        rewrite(ws, [("events/a.txt", a.id, steps)])


def test_api(tmp_path):
    ws = make(tmp_path)
    engine = Engine(ws)
    all_groups = engine.modgroups("")["groups"]
    assert len(all_groups) == 4 and all("signature" in g for g in all_groups)
    one = engine.modgroups("events/a.txt")["groups"]
    g = one[0]
    edits = engine.modgroup_edits({"rel": "events/a.txt", "id": g["id"], "steps": [["5", "2"]]})[
        "edits"
    ]
    text = ws.document("events/a.txt").text
    new = "".join(text)  # apply in reverse order like the editor does
    for e in sorted(edits, key=lambda e: -e["start"]):
        new = new[: e["start"]] + e["text"] + new[e["end"] :]
    assert "num_of_cities = 5" in new and "num_of_cities = 30" not in new
    preview = engine.modgroup_plan(
        {"plans": [{"rel": "events/a.txt", "id": g["id"], "steps": [["5", "2"]]}]}
    )
    assert preview["files"] == ["events/a.txt"] and "written" not in preview
    done = engine.modgroup_plan(
        {"plans": [{"rel": "events/a.txt", "id": g["id"], "steps": [["5", "2"]]}], "write": True}
    )
    assert done["written"] and "num_of_cities = 5" in (tmp_path / "mod/events/a.txt").read_text()
    with pytest.raises(ApiError):
        engine.modgroup_edits({"rel": "events/a.txt", "id": g["id"], "steps": []})  # id changed


def test_combine_rule():
    from vic2toolmod.analysis.modifier_groups import combine_of

    assert combine_of("poptypes/artisans.txt", ["promote_to", "farmers"])[0] == "add"
    assert combine_of("poptypes/artisans.txt", ["issues", "trinket_pensions"])[0] == "multiply"
    assert combine_of("poptypes/artisans.txt", ["ideologies", "liberal"])[0] == "multiply"
    assert combine_of("poptypes/artisans.txt", ["migration_target"])[0] == "multiply"
    assert combine_of("poptypes/artisans.txt", ["country_migration_target"])[0] == "multiply"
    assert combine_of("inventions/army_inventions.txt", ["x", "chance"])[0] == "add"
    assert combine_of("common/rebel_types.txt", ["x", "spawn_chance"])[0] == "multiply"
    assert combine_of("common/pop_types.txt", ["promotion_chance", "group"])[0] == "add"
    path = ["conservative_group", "conservative", "add_political_reform", "group"]
    assert combine_of("common/ideologies.txt", path)[0] == "add"
    assert combine_of("events/a.txt", ["country_event 7", "mean_time_to_happen"])[0] == "multiply"


def test_copies_are_the_same_place_not_the_same_parent_key():
    """T014: migration and emigration groups of one file are not copies of each other."""
    block = (
        "group = {\n"
        + "".join(
            f"modifier = {{ factor = -0.1 not = {{ literacy = {v} }} }}\n" for v in (0.4, 0.3)
        )
        + "}\n"
    )
    text = f"migration_chance = {{\n{block}}}\nemigration_chance = {{\n{block}}}\n"
    a, b = groups(text, "common/pop_types.txt")
    assert a.signature != b.signature
    # the same place of an event in two files: the event id does not count
    one = groups(EVENT, "events/a.txt")[0]
    two = groups(EVENT.replace("id = 7", "id = 9"), "events/b.txt")[0]
    assert one.signature == two.signature


def test_scan_cache_follows_the_text(tmp_path):
    from vic2toolmod.analysis.modifier_groups import scan

    ws = make(tmp_path)
    cache = {}
    first = scan(ws, cache=cache)
    assert len(first) == 4 and set(cache) == {"events/a.txt", "events/b.txt"}
    again = scan(ws, cache=cache)
    assert [g is h for g, h in zip(first, again, strict=True)] == [True] * 4  # not searched again
    ws.set_text("events/a.txt", "x = 1\n")
    assert len(scan(ws, cache=cache)) == 2


MIXED = (
    "e = { mean_time_to_happen = { months = 120\n"
    "\tmodifier = {\n\t\tfactor = 0.9\n\t\taverage_consciousness = 5\n\t}\n"
    "\tmodifier = {\n\t\tfactor = 0.9\n\t\taverage_consciousness = 7\n\t}\n"
    "\tmodifier = {\n\t\tfactor = 1.1\n\t\tNOT = { average_consciousness = 3 }\n\t}\n"
    "} }\n"
)


def test_plain_and_not_steps_are_one_group():
    """T023: ``key = N`` and ``NOT = { key = N }`` of one variable make one group."""
    (g,) = groups(MIXED)
    assert (g.key, g.negated) == ("average_consciousness", False)
    assert [(s.value, s.factor, s.negated) for s in g.steps] == [
        ("5", "0.9", False),
        ("7", "0.9", False),
        ("3", "1.1", True),
    ]
    only_not = MIXED.replace(
        "\t\taverage_consciousness = 5", "\t\tNOT = { average_consciousness = 5 }"
    )
    only_not = only_not.replace(
        "\t\taverage_consciousness = 7", "\t\tNOT = { average_consciousness = 7 }"
    )
    assert groups(only_not)[0].negated is True


def test_rewrite_keeps_or_flips_not():
    doc = parse_text(MIXED)
    (g,) = find_groups(doc, "events/a.txt", default_schema())
    steps = [("4", "0.8", False), ("2", "1.2", True), ("1", "1.5", True), ("9", "0.5")]
    new = apply_edits(doc.text, rewrite_edits(doc, g, steps))
    (again,) = groups(new)
    assert [(s.value, s.factor, s.negated) for s in again.steps] == [
        ("4", "0.8", False),
        ("2", "1.2", True),
        ("1", "1.5", True),
        ("9", "0.5", False),  # no flag: written like the first modifier
    ]
    assert "NOT = { average_consciousness = 2 }" in new
    # a spelling the group did not have: the condition is written the other way
    plain = "a = { modifier = { factor = 2 literacy = 0.2 }\n"
    plain += "modifier = { factor = 3 literacy = 0.4 } }\n"
    doc = parse_text(plain)
    (g,) = find_groups(doc, "events/a.txt", default_schema())
    new = apply_edits(doc.text, rewrite_edits(doc, g, [("0.2", "2", False), ("0.1", "0.5", True)]))
    assert "modifier = { factor = 0.5 NOT = { literacy = 0.1 } }" in new
    assert [s.negated for s in groups(new)[0].steps] == [False, True]
