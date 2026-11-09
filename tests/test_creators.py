from pathlib import Path

import pytest

from vic2toolmod.generators.ideology import IdeologySpec, plan_ideology
from vic2toolmod.generators.reform import OptionSpec, ReformSpec, plan_reform
from vic2toolmod.script import parse_text
from vic2toolmod.workspace import Workspace


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("latin-1"))


def make(tmp_path):
    g = tmp_path / "game"
    write(
        g / "common/issues.txt",
        "political_reforms = {\n\tslavery = {\n\t\tyes_slavery = { }\n"
        "\t\tno_slavery = { }\n\t}\n}\nsocial_reforms = {\n}\n",
    )
    write(
        g / "common/ideologies.txt",
        "conservative_group = {\n\tconservative = {\n\t\tcolor = { 1 2 3 }\n"
        "\t\tdate = 1836.1.1\n\t}\n}\n"
        "liberal_group = {\n\tliberal = {\n\t\tcolor = { 4 5 6 }\n\t}\n}\n",
    )
    write(
        g / "common/governments.txt",
        "democracy = {\n\tconservative = yes\n\tliberal = yes\n"
        "\telection = yes\n}\nabsolute_monarchy = {\n\tliberal = yes\n}\n",
    )
    write(
        g / "poptypes/farmers.txt", "ideologies = {\n\tconservative = {\n\t\tfactor = 1\n\t}\n}\n"
    )
    write(g / "poptypes/slaves.txt", "ideologies = {\n\tliberal = { factor = 0 }\n}\n")
    write(
        g / "interface/country_politics.gui",
        'guiTypes = {\n\twindowType = {\n\t\tname = "reforms_window"\n'
        '\t\tsize = { x=1024 y=768 }\n\t\twindowType = {\n\t\t\tname = "slavery"\n'
        "\t\t\tposition = { x = 686 y = 58 }\n\t\t\tsize = { x=310 y=100 }\n\t\t}\n\t}\n}\n",
    )
    return Workspace.open(g, tmp_path / "mod")


def by_rel(changes):
    return {c.rel: c.new_text for c in changes}


def test_new_reform(tmp_path):
    ws = make(tmp_path)
    plan = plan_reform(
        ws,
        ReformSpec(
            "political_reforms",
            "press_rights",
            "Press Rights",
            [
                OptionSpec("censored_press", "Censored Press", "The state controls the press."),
                OptionSpec(
                    "free_press",
                    "Free Press",
                    modifiers={"global_pop_consciousness_modifier": "0.01"},
                ),
            ],
        ),
    )
    files = by_rel(plan.changes)
    issues = parse_text(files["common/issues.txt"])
    pr = issues.find("political_reforms").value.find("press_rights").value
    assert [a.key_text for a in pr.assignments()] == [
        "next_step_only",
        "censored_press",
        "free_press",
    ]
    loc = files["localisation/00_vic2toolmod.csv"]
    assert (
        "press_rights;Press Rights;" in loc
        and "censored_press_desc;The state controls the press.;" in loc
    )
    gui = files["interface/country_politics.gui"]
    assert 'name = "press_rights"' in gui and "position = { x = 686 y = 133 }" in gui
    assert parse_text(gui).diagnostics == []
    assert not ws.registries().has("issue", "press_rights")  # nothing written, buffer reverted


def test_reform_checks(tmp_path):
    ws = make(tmp_path)
    with pytest.raises(ValueError, match="already exists"):
        plan_reform(
            ws,
            ReformSpec(
                "political_reforms", "slavery", "X", [OptionSpec("a", "A"), OptionSpec("b", "B")]
            ),
        )
    with pytest.raises(ValueError, match="at least two"):
        plan_reform(ws, ReformSpec("political_reforms", "x", "X", [OptionSpec("a", "A")]))
    with pytest.raises(ValueError, match="bad name"):
        plan_reform(
            ws,
            ReformSpec(
                "political_reforms", "X Y", "X", [OptionSpec("a", "A"), OptionSpec("b", "B")]
            ),
        )


def test_new_ideology(tmp_path):
    ws = make(tmp_path)
    plan = plan_ideology(
        ws,
        IdeologySpec(
            "christian_democrat",
            "Christian Democrat",
            "conservative",
            group="liberal_group",
            color=(7, 8, 9),
        ),
    )
    files = by_rel(plan.changes)
    ide = parse_text(files["common/ideologies.txt"])
    new = ide.find("liberal_group").value.find("christian_democrat").value
    assert new.find("color").value.to_text().strip() == "{ 7 8 9 }"
    assert new.find("date").value.text == "1836.1.1"
    assert "\tchristian_democrat = {\n\t\tfactor = 1\n\t}\n" in files["poptypes/farmers.txt"]
    assert "poptypes/slaves.txt" not in files and any("slaves" in n for n in plan.notes)
    gov = parse_text(files["common/governments.txt"])
    assert gov.find("democracy").value.find("christian_democrat").value.text == "yes"
    assert gov.find("absolute_monarchy").value.find("christian_democrat") is None
    assert "christian_democrat;Christian Democrat;" in files["localisation/00_vic2toolmod.csv"]


def test_new_event_and_decision(tmp_path):
    from vic2toolmod.generators.event_decision import (
        DecisionSpec,
        EventSpec,
        plan_decision,
        plan_event,
    )

    ws = make(tmp_path)
    write(
        ws.project.game_dir / "events/mine.txt",
        "### Events 500-510 used\ncountry_event = { id = 500 }\n",
    )
    ws.refresh()
    plan = plan_event(
        ws, EventSpec("mine.txt", "Title", "Text", ["Yes", "No"], triggered_only=False, months=6)
    )
    files = by_rel(plan.changes)
    ev = parse_text(files["events/mine.txt"]).items[-1].value
    assert ev.find("id").value.text == "501"
    assert ev.find("mean_time_to_happen").value.find("months").value.text == "6"
    assert [o.value.find("name").value.value for o in ev.assignments("option")] == [
        "EVTOPTA501",
        "EVTOPTB501",
    ]
    assert "EVTNAME501;Title;" in files["localisation/00_vic2toolmod.csv"]
    plan = plan_decision(ws, DecisionSpec("new.txt", "build_homes", "Build Homes", "Homes."))
    files = by_rel(plan.changes)
    dec = (
        parse_text(files["decisions/new.txt"]).find("political_decisions").value.find("build_homes")
    )
    assert [a.key_text for a in dec.value.assignments()] == [
        "potential",
        "allow",
        "effect",
        "ai_will_do",
    ]
    assert "build_homes_title;Build Homes;" in files["localisation/00_vic2toolmod.csv"]
