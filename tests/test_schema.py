import textwrap

import pytest

from vic2toolmod.schema import SchemaError, Validator, default_schema, file_type_for, load_schema
from vic2toolmod.schema.loader import parse_type
from vic2toolmod.schema.model import Context
from vic2toolmod.script import parse_text


def check(text, rule="events_file", scope=None, names=None):
    doc = parse_text(textwrap.dedent(text))
    diags = Validator(default_schema(), names).validate(doc, rule, scope)
    return [(d.code, d.message) for d in diags]


def codes(text, **kw):
    return [c for c, _ in check(text, **kw)]


def test_default_schema_loads_and_is_big_enough():
    s = default_schema()
    assert len(s.commands) > 400
    assert len(s.modifiers) > 150
    assert len(s.file_types) > 30
    assert s.command(Context.TRIGGER, "NOT")
    assert s.command(Context.EFFECT, "add_country_modifier")


def test_parse_type():
    t = parse_type("int[0..3]")
    assert (t.name, t.minimum, t.maximum) == ("int", 0, 3)
    assert str(parse_type("enum:strata")) == "enum:strata"
    with pytest.raises(ValueError):
        parse_type("int[")


def test_loader_reports_all_problems(tmp_path):
    (tmp_path / "commands").mkdir()
    (tmp_path / "files").mkdir()
    (tmp_path / "commands" / "x.yaml").write_text(
        "trigger:\n  a: {scopes: [planet], value: enum:missing}\n  b: {value: {rule: nope}}\n"
    )
    (tmp_path / "files" / "f.yaml").write_text("file_types:\n  t: {paths: [x], rule: missing}\n")
    with pytest.raises(SchemaError) as info:
        load_schema(tmp_path)
    text = "\n".join(info.value.problems)
    assert "bad scope 'planet'" in text
    assert "unknown enum 'missing'" in text
    assert "unknown rule 'nope'" in text
    assert "unknown rule 'missing'" in text


def test_file_types():
    s = default_schema()
    assert file_type_for("events/My Events.txt", s).name == "events"
    assert file_type_for("Decisions/x.txt", s).name == "decisions"
    assert file_type_for("history/provinces/spain/479 - Burgos.txt", s).name == "province_history"
    assert file_type_for("common/countries/Prussia.txt", s).name == "country_definition"
    assert file_type_for("readme.txt", s) is None


GOOD_EVENT = """
country_event = {
    id = 1
    title = "T"
    desc = "D"
    trigger = { tag = USA NOT = { has_country_flag = x } any_pop = { militancy = 5 } }
    mean_time_to_happen = { months = 12 modifier = { factor = 0.5 war = yes } }
    option = {
        name = "A"
        add_country_modifier = { name = m duration = 365 }
        any_owned = { limit = { is_core = THIS } add_core = THIS }
        ENG = { prestige = 5 }
        random_list = { 50 = { badboy = 1 } 50 = { } }
        ai_chance = { factor = 1 }
    }
}
"""


def test_good_event_has_no_problems():
    assert check(GOOD_EVENT) == []


def test_unknown_keys_are_warnings():
    assert codes("country_event = { id = 1 trigger = { has_countryflag = x } }") == [
        "schema.unknown-key"
    ]
    assert codes("country_event = { id = 1 colour = red }") == ["schema.unknown-key"]


def test_effect_in_trigger_is_wrong_context():
    assert codes("country_event = { id = 1 trigger = { add_core = THIS } }") == [
        "schema.wrong-context"
    ]


def test_wrong_values():
    found = check("country_event = { id = x trigger = { war = maybe } option = { badboy = abc } }")
    assert [c for c, _ in found] == ["schema.wrong-value"] * 3


def test_missing_required_field():
    assert codes("country_event = { title = x }") == ["schema.missing-field"]


def test_duplicate_key():
    assert codes("country_event = { id = 1 id = 2 }") == ["schema.duplicate-key"]


def test_wrong_operator():
    assert codes("country_event = { id = 1 trigger = { year > 1850 } }") == [
        "schema.wrong-operator"
    ]


def test_scope_tracking():
    # has_country_flag is a country trigger; inside any_pop the scope is pop
    found = check("country_event = { id = 1 trigger = { any_pop = { has_country_flag = x } } }")
    assert [c for c, _ in found] == ["schema.wrong-scope"]
    # owner switches back to country
    assert check("province_event = { id = 1 trigger = { owner = { has_country_flag = x } } }") == []


def test_any_core_scope_depends_on_where_it_is_used():
    text = "country_event = { id = 1 trigger = { any_core = { owned_by = THIS } } }"
    assert check(text) == []


def test_dynamic_keys_need_names():
    text = "country_event = { id = 1 trigger = { aristocrats = { militancy = 5 } } }"
    assert codes(text) == ["schema.unknown-key"]

    def names(registry, name):
        return name == "aristocrats" if registry == "pop_type" else None

    assert check(text, names=names) == []


def test_unknown_names_are_reported():
    def names(registry, name):
        return name == "liberal" if registry == "ideology" else None

    text = "country_event = { id = 1 trigger = { ruling_party_ideology = libral } }"
    assert check(text, names=names) == [("ref.unknown-name", "unknown ideology 'libral'")]


def test_structural_rules_history():
    text = """
    capital = 1
    primary_culture = british
    1861.1.1 = { government = democracy }
    """
    assert check(text, rule="country_history", scope="country") == []
    assert codes("capital = london", rule="country_history") == ["schema.wrong-value"]


def test_keys_confirmed_by_the_game_program():
    # K78: names found in v2game.exe are known, with their values checked.
    assert (
        codes(
            "country_event = { id = 1 trigger = { any_pop = {"
            " pop_unemployment = { value = 0.1 type = THIS } } } }"
        )
        == []
    )
    assert codes(
        "country_event = { id = 1 trigger = { any_pop = {"
        " pop_unemployment = { value = x type = THIS } } } }"
    ) == ["schema.wrong-value"]
    assert (
        codes("x = { factory_maintenance = 0.05 random_party_votes = 0.1 }", rule="modifiers_file")
        == []
    )


def test_names_the_game_does_not_know_are_errors_with_a_hint():
    found = check("country_event = { id = 1 trigger = { is_subject = no } }")
    assert [c for c, _ in found] == ["schema.not-in-game"]
    assert "is_vassal" in found[0][1]
