from vic2toolmod.analysis.trigger_tester import TriggerTester
from vic2toolmod.schema import default_schema
from vic2toolmod.script import parse_text

EVENT = """
country_event = {
    id = 95260
    trigger = {
        tag = USA
        war = no
        NOT = { government = democracy }
        OR = { has_global_flag = a  literacy = 0.5 }
        any_pop = { militancy = 5 }
    }
    mean_time_to_happen = {
        months = 24
        modifier = { factor = 0.8 war = no }
        modifier = { factor = 0.5 num_of_revolts = 1 }
    }
}
"""


def setup():
    doc = parse_text(EVENT)
    ev = doc.find("country_event").value
    return TriggerTester(default_schema(), doc), ev


def test_facts():
    t, ev = setup()
    facts = t.facts(ev.find("trigger").value)
    assert [(f.id, f.key, f.value, f.compare, f.kind) for f in facts] == [
        ("0", "tag", "USA", "eq", "condition"),
        ("1", "war", "no", "eq", "condition"),
        ("2.0", "government", "democracy", "eq", "condition"),
        ("3.0", "has_global_flag", "a", "eq", "condition"),
        ("3.1", "literacy", "0.5", "gte", "condition"),
        ("4", "any_pop", "{ militancy = 5 }", "block", "scope"),
    ]
    assert facts[5].question.startswith("Does 'any_pop'")
    assert facts[0].line == 5


def test_evaluate():
    t, ev = setup()
    trig = ev.find("trigger").value
    answers = {
        "0": "usa",
        "1": "no",
        "2.0": "absolute_monarchy",
        "3.0": False,
        "3.1": "0.62",
        "4": True,
    }
    r = t.evaluate(trig, answers)
    assert (r.value, r.failed, r.unknown) == (True, [], [])
    r = t.evaluate(trig, {**answers, "2.0": "democracy"})
    assert (r.value, r.failed) == (False, ["2.0"])  # NOT failed because government = democracy
    r = t.evaluate(trig, {"0": "USA"})
    assert r.value is None and "1" in r.unknown
    r = t.evaluate(trig, {"0": "FRA"})
    assert r.value is False and r.failed == ["0"]


def test_weight():
    t, ev = setup()
    mtth = ev.find("mean_time_to_happen").value
    w = t.weight(mtth, {"0": {"0": "no"}, "1": {"0": "2"}})
    assert (w.base, w.value, w.applied, w.unknown) == (24, 24 * 0.8 * 0.5, [(0, 0.8), (1, 0.5)], [])
    w = t.weight(mtth, {"0": {"0": "yes"}})
    assert (w.value, w.unknown) == (24, [1])
