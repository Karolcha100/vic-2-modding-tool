"""Meta relations between pops (T010)."""

import pytest

from vic2toolmod.generators.meta import (
    MetaError,
    Rule,
    copies,
    matches,
    parse_rule,
    plan,
    pop_types,
    rules,
    save_rule,
)
from vic2toolmod.workspace import Workspace

POP = (
    "strata = {strata}\n"
    "promote_to = {{\n"
    "\tsoldiers = {{\n"
    "\t\tfactor = 0.01\n"
    "\t}}\n"
    "}}\n"
    "issues = {{\n"
    "\tgood_pensions = {{\n"
    "\t\tfactor = 1\n"
    "\t}}\n"
    "}}\n"
)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("cp1252"))


def make(tmp_path):
    game = tmp_path / "game"
    write(game / "poptypes/farmers.txt", POP.format(strata="poor"))
    write(game / "poptypes/soldiers.txt", POP.format(strata="poor"))
    write(game / "poptypes/clerks.txt", POP.format(strata="middle"))
    write(game / "poptypes/slaves.txt", "strata = poor\n")
    write(game / "common/pop_types.txt", "promotion_chance = {\n\tfactor = 1\n}\n")
    (tmp_path / "mod").mkdir()
    return Workspace.open(game, tmp_path / "mod")


RULE = Rule(
    name="war_poor",
    block="promote_to",
    target="soldiers",
    strata=["poor"],
    modifiers="modifier = {\n\tfactor = 2\n\tcountry = { war = yes }\n}",
)


def apply(ws, result):
    for c in result.changes:
        ws.set_text(c.rel, c.new_text)


def test_rule_file_round_trip():
    rule = Rule(**{**RULE.__dict__, "description": 'say "hi"', "group": True})
    back = parse_rule(rule.to_text())
    assert back == Rule(**{**rule.__dict__, "description": "say 'hi'"})
    with pytest.raises(MetaError, match="target"):
        Rule("x", "issues", modifiers="modifier = { factor = 2 }").check()
    with pytest.raises(MetaError, match="unknown block"):
        Rule("x", "nope", modifiers="modifier = { factor = 2 }").check()
    with pytest.raises(MetaError, match="syntax"):
        Rule("x", "migration_target", modifiers="modifier = {").check()


def test_plan_insert_update_remove(tmp_path):
    ws = make(tmp_path)
    pops = pop_types(ws)
    assert pops == {"clerks": "middle", "farmers": "poor", "slaves": "poor", "soldiers": "poor"}
    assert matches(RULE, pops) == ["farmers", "slaves"]  # soldiers do not promote to themselves
    result = plan(ws, [RULE])
    assert result.added == [("war_poor", "poptypes/farmers.txt")]
    assert result.missing == [("war_poor", "poptypes/slaves.txt", "no promote_to = { } block")]
    farmers = result.changes[0]
    assert farmers.old_text is None and farmers.path == tmp_path / "mod/poptypes/farmers.txt"
    assert "\t\tfactor = 0.01\n\t\t# vic2toolmod meta: war_poor " in farmers.new_text
    assert "\t\tmodifier = {\n\t\t\tfactor = 2\n" in farmers.new_text
    apply(ws, result)
    assert plan(ws, [RULE]).changes == []  # nothing more to do
    # the rule changes: the copy is updated
    changed = Rule(**{**RULE.__dict__, "modifiers": "modifier = { factor = 3 war = yes }"})
    result = plan(ws, [changed])
    assert result.updated == [("war_poor", "poptypes/farmers.txt")]
    assert "modifier = { factor = 3 war = yes }" in result.changes[0].new_text
    # a copy changed by hand is kept and reported (or overwritten with force)
    text = ws.document("poptypes/farmers.txt").text.replace("factor = 2\n", "factor = 9\n")
    ws.set_text("poptypes/farmers.txt", text)
    assert [c.edited for c in copies(text)] == [True]
    result = plan(ws, [changed])
    assert result.edited == [("war_poor", "poptypes/farmers.txt")] and not result.changes
    assert plan(ws, [changed], force=True).updated == [("war_poor", "poptypes/farmers.txt")]
    # the rule is gone: its copies go too
    assert plan(ws, []).removed == [("war_poor", "poptypes/farmers.txt")]
    assert "vic2toolmod" not in plan(ws, []).changes[0].new_text


def test_new_target_block_group_and_chances(tmp_path):
    ws = make(tmp_path)
    issue = Rule("pensions", "issues", "trinket_pensions", strata=["middle"], group=True,
                 modifiers="modifier = { factor = 2 }")  # fmt: skip
    result = plan(ws, [issue])
    text = result.changes[0].new_text
    assert result.added == [("pensions", "poptypes/clerks.txt")]
    assert "\ttrinket_pensions = {\n\t\tfactor = 1\n\t\t# vic2toolmod meta: pensions" in text
    assert "\t\tgroup = {\n\t\t\tmodifier = { factor = 2 }\n\t\t}\n" in text
    chance = Rule("lit", "promotion_chance", modifiers="modifier = { factor = 0.1 literacy = 0.5 }")
    result = plan(ws, [chance])
    assert result.added == [("lit", "common/pop_types.txt")]


def test_save_and_list_rules(tmp_path):
    ws = make(tmp_path)
    change = save_rule(ws, RULE)
    assert change.rel == "vic2toolmod/meta/war_poor.txt" and change.old_text is None
    change.path.parent.mkdir(parents=True)
    change.path.write_text(change.new_text)
    assert [r.name for r in rules(ws)] == ["war_poor"]
    assert rules(ws)[0].modifiers == RULE.modifiers


def test_api(tmp_path):
    from vic2toolmod.server.app import ApiError, Engine

    ws = make(tmp_path)
    engine = Engine(ws)
    info = engine.meta()
    assert info["rules"] == [] and info["pops"]["clerks"] == "middle"
    assert "promotion_chance" in info["blocks"]["chance"]
    raw = {**RULE.__dict__}
    preview = engine.meta_plan({"rule": raw})
    assert preview["files"] == ["vic2toolmod/meta/war_poor.txt", "poptypes/farmers.txt"]
    assert "written" not in preview and not (tmp_path / "mod/vic2toolmod").exists()
    done = engine.meta_plan({"rule": raw, "write": True})
    assert done["written"] and (tmp_path / "mod/vic2toolmod/meta/war_poor.txt").is_file()
    assert "# vic2toolmod meta: war_poor" in (tmp_path / "mod/poptypes/farmers.txt").read_text()
    assert [r["pops"] for r in engine.meta()["rules"]] == [["farmers", "slaves"]]
    with pytest.raises(ApiError, match="already exists"):
        engine.meta_plan({"rule": raw})
    # rename: the old rule file goes, the copies get the new name
    renamed = engine.meta_plan(
        {"rule": {**raw, "name": "war_poor2"}, "old_name": "war_poor", "write": True}
    )
    assert ("war_poor", "poptypes/farmers.txt") in [tuple(x) for x in renamed["removed"]]
    assert not (tmp_path / "mod/vic2toolmod/meta/war_poor.txt").exists()
    assert "meta: war_poor2" in (tmp_path / "mod/poptypes/farmers.txt").read_text()
    gone = engine.meta_plan({"delete": True, "name": "war_poor2", "write": True})
    assert gone["written"] and engine.meta()["rules"] == []
    assert "vic2toolmod" not in (tmp_path / "mod/poptypes/farmers.txt").read_text()
    # groups in a rule's modifiers, edited as a function
    code = "modifier = { factor = 1.1 literacy = 0.2 }\nmodifier = { factor = 1.1 literacy = 0.4 }"
    groups = engine.modgroups_text({"text": code, "block": "promote_to"}, None)["groups"]
    assert groups[0]["key"] == "literacy" and groups[0]["combine"] == "add"
    new = engine.modgroups_text(
        {"text": code, "block": "promote_to", "id": groups[0]["id"]}, [("0.5", "0.3")]
    )["text"]
    assert new == "modifier = { factor = 0.3 literacy = 0.5 }"
