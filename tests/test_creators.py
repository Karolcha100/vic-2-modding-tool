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


def test_new_ideology_from_scratch_in_a_new_group(tmp_path):
    """T031: no template; a new group; pop support by strata; chosen governments."""
    ws = make(tmp_path)
    plan = plan_ideology(
        ws,
        IdeologySpec(
            "agrarian",
            "Agrarian",
            None,
            color=(1, 2, 3),
            date="1850.1.1",
            new_group="agrarian_group",
            new_group_english="Agrarians",
            uncivilized=False,
            reform_weights={"add_social_reform": 1, "remove_political_reform": 0.5},
            support={"poor": 2, "": 0.5},
            governments=["democracy"],
        ),
    )
    files = by_rel(plan.changes)
    ide = parse_text(files["common/ideologies.txt"])
    new = ide.find("agrarian_group").value.find("agrarian").value
    assert new.find("color").value.to_text().strip() == "{ 1 2 3 }"
    assert new.find("uncivilized").value.text == "no"
    assert new.find("add_social_reform").value.find("base").value.text == "1"
    assert new.find("remove_political_reform").value.find("base").value.text == "0.5"
    farmers = parse_text(files["poptypes/farmers.txt"]).find("ideologies").value.find("agrarian")
    assert farmers is not None and farmers.value.find("factor").value.text in ("2", "0.5")
    gov = parse_text(files["common/governments.txt"])
    assert gov.find("democracy").value.find("agrarian").value.text == "yes"
    loc = files["localisation/00_vic2toolmod.csv"]
    assert "agrarian;Agrarian;" in loc and "agrarian_group;Agrarians;" in loc
    with pytest.raises(ValueError, match="already exists"):
        plan_ideology(ws, IdeologySpec("x", "X", None, color=(1, 1, 1), new_group="liberal_group"))
    with pytest.raises(ValueError, match="needs a colour"):
        plan_ideology(ws, IdeologySpec("x", "X", None, group="liberal_group"))


def test_copied_ideology_in_a_new_group(tmp_path):
    ws = make(tmp_path)
    plan = plan_ideology(ws, IdeologySpec("x_dem", "X", "conservative", new_group="new_group"))
    ide = parse_text(by_rel(plan.changes)["common/ideologies.txt"])
    assert ide.find("new_group").value.find("x_dem") is not None


def test_reform_country_options_and_free_spot(tmp_path):
    """T030: the option every country starts with, exceptions, and a free box in the window."""
    from vic2toolmod.analysis import reform_window
    from vic2toolmod.generators.reform import free_spot

    ws = make(tmp_path)
    write(
        tmp_path / "game/history/countries/ENG - England.txt",
        "capital = 300\n1861.1.1 = { x = 1 }\n",
    )
    write(tmp_path / "game/history/countries/FRA - France.txt", "capital = 400\n")
    write(tmp_path / "game/history/countries/PRU - Prussia.txt", "capital = 549\n")
    ws.project._files = None
    options = [
        OptionSpec("no_courts", "No"),
        OptionSpec("some_courts", "Some"),
        OptionSpec("courts", "Yes"),
    ]
    spec = ReformSpec(
        "political_reforms",
        "court_reform",
        "Courts",
        options,
        country_default="some_courts",
        country_options={"eng": "courts"},
    )
    files = by_rel(plan_reform(ws, spec).changes)
    eng = files["history/countries/ENG - England.txt"]
    assert eng.index("court_reform = courts") < eng.index("1861.1.1")  # before the dated blocks
    assert "court_reform = some_courts" in files["history/countries/FRA - France.txt"]
    # the default is the game's own (the first option): only the exceptions are written
    spec2 = ReformSpec(
        "political_reforms", "court_reform", "Courts", options, country_options={"FRA": "courts"}
    )
    files2 = by_rel(plan_reform(ws, spec2).changes)
    assert "history/countries/PRU - Prussia.txt" not in files2
    assert "court_reform = courts" in files2["history/countries/FRA - France.txt"]
    with pytest.raises(ValueError, match="not an option"):
        plan_reform(
            ws, ReformSpec("political_reforms", "court_reform", "C", options, country_default="x")
        )
    # free_spot skips taken cells of the category's grid
    layout = reform_window.Layout(
        "f",
        1024,
        768,
        [
            reform_window.Box("a", 100, 60, 150, 70, "political_reforms", 1, False, False),
            reform_window.Box("b", 100, 140, 150, 70, "political_reforms", 2, False, False),
            reform_window.Box("c", 260, 60, 150, 70, "political_reforms", 3, False, False),
        ],
    )
    assert free_spot(layout, "political_reforms") == (100, 220)


def test_new_event_with_id_range_trigger_and_options(tmp_path):
    """T033: a new file claims an id range; a chosen id; trigger; options with effects and AI."""
    from vic2toolmod.generators.event_decision import EventOption, EventSpec, plan_event

    ws = make(tmp_path)
    spec = EventSpec(
        "New.txt",
        "Title",
        "Desc",
        [
            EventOption(
                "Yes",
                "prestige = 5\nadd_country_modifier = {\n    name = x\n    duration = 365\n}",
                "2",
            ),
            "No",
        ],
        triggered_only=False,
        months=6,
        id_range=(5000, 5099),
        trigger="tag = ENG\nwar = no",
    )
    plan = plan_event(ws, spec)
    text = by_rel(plan.changes)["events/New.txt"]
    assert text.startswith("### Events 5000-5099 used")
    doc = parse_text(text)
    ev = doc.find("country_event").value
    assert ev.find("id").value.text == "5000"
    assert [a.key_text for a in ev.find("trigger").value.assignments()] == ["tag", "war"]
    first = next(ev.assignments("option")).value
    assert (
        first.find("prestige").value.text == "5"
        and first.find("ai_chance").value.find("factor").value.text == "2"
    )
    assert "\t\tadd_country_modifier = {\r\n\t\t\tname = x" in text
    assert doc.diagnostics == []
    plan = plan_event(ws, EventSpec("New2.txt", "T", "D", event_id=777))
    assert "id = 777" in by_rel(plan.changes)["events/New2.txt"]
    with pytest.raises(ValueError, match="the code has errors"):
        plan_event(ws, EventSpec("New3.txt", "T", "D", triggered_only=False, trigger="a = {"))
    with pytest.raises(ValueError, match="not a number"):
        plan_event(ws, EventSpec("New3.txt", "T", "D", [EventOption("A", "", "x")]))


def test_ideology_code_blocks_and_rich_decision(tmp_path):
    """T031: reform wishes and pop support as code; T033: decision blocks from code."""
    from vic2toolmod.generators.event_decision import DecisionSpec, plan_decision

    ws = make(tmp_path)
    plan = plan_ideology(
        ws,
        IdeologySpec(
            "agrarian",
            "Agrarian",
            None,
            group="liberal_group",
            color=(1, 2, 3),
            reform_code={
                "add_political_reform": "base = 1\nmodifier = {\n\tfactor = -1\n"
                "\tNOT = { ruling_party_ideology = agrarian }\n}"
            },
            support_code={"": "factor = 1\nmodifier = { factor = 2 literacy = 0.3 }"},
        ),
    )
    files = by_rel(plan.changes)
    new = (
        parse_text(files["common/ideologies.txt"])
        .find("liberal_group")
        .value.find("agrarian")
        .value
    )
    apr = new.find("add_political_reform").value
    assert apr.find("base").value.text == "1" and apr.find("modifier").value.find("NOT") is not None
    farm = parse_text(files["poptypes/farmers.txt"]).find("ideologies").value.find("agrarian").value
    assert farm.find("modifier").value.find("literacy").value.text == "0.3"
    with pytest.raises(ValueError, match="code has errors"):
        plan_ideology(
            ws,
            IdeologySpec(
                "x",
                "X",
                None,
                group="liberal_group",
                color=(1, 1, 1),
                reform_code={"add_social_reform": "base = {"},
            ),
        )

    d = DecisionSpec(
        "New.txt",
        "build_it",
        "Build",
        "D",
        potential="tag = ENG",
        allow="money = 100",
        effect="prestige = 5\nadd_country_modifier = { name = x duration = 365 }",
        ai_will_do="factor = 1\nmodifier = { factor = 0 war = yes }",
    )
    text = by_rel(plan_decision(ws, d).changes)["decisions/New.txt"]
    dec = parse_text(text).find("political_decisions").value.find("build_it").value
    assert dec.find("potential").value.find("tag").value.text == "ENG"
    assert dec.find("ai_will_do").value.find("modifier") is not None
    assert parse_text(text).diagnostics == []


def test_scratch_ideology_leaves_pop_support_to_the_editor(tmp_path):
    """T031 (17:37): without support values the pop files are not touched; the notes say so."""
    ws = make(tmp_path)
    plan = plan_ideology(
        ws, IdeologySpec("x_ide", "X", None, group="liberal_group", color=(1, 2, 3))
    )
    files = by_rel(plan.changes)
    assert not any(rel.startswith("poptypes/") for rel in files)
    assert any("pop support: add x_ide" in n for n in plan.notes)
    new = parse_text(files["common/ideologies.txt"]).find("liberal_group").value.find("x_ide").value
    assert new.find("add_political_reform").value.find("base").value.text == "0"
