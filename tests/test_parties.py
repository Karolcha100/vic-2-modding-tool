from pathlib import Path

from vic2toolmod.changes import diff, write_changes
from vic2toolmod.generators.parties import CountryFilter, PartySpec, plan_parties
from vic2toolmod.script import parse_text
from vic2toolmod.workspace import Workspace

PARTY = """party = {{
\tname = "{tag}_{ideo}"
\tstart_date = 1830.1.1
\tend_date = 2000.1.1
\tideology = {ideo}
\teconomic_policy = laissez_faire
\ttrade_policy = free_trade
\treligious_policy = pluralism
\tcitizenship_policy = limited_citizenship
\twar_policy = anti_military
}}
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("latin-1").replace(b"\n", b"\r\n"))


def make(tmp_path):
    g = tmp_path / "game"
    write(
        g / "common/countries.txt",
        'PRU = "countries/Prussia.txt"\nENG = "countries/UK.txt"\nREB = "countries/Rebels.txt"\n',
    )
    write(
        g / "common/countries/Prussia.txt",
        "color = { 1 2 3 }\n"
        + PARTY.format(tag="PRU", ideo="liberal")
        + "\n# names\nunit_names = { }\n",
    )
    write(
        g / "common/countries/UK.txt",
        "color = { 1 2 3 }\n"
        + PARTY.format(tag="ENG", ideo="liberal")
        + PARTY.format(tag="ENG", ideo="socialist"),
    )
    write(g / "common/countries/Rebels.txt", "color = { 1 2 3 }\n")
    write(
        g / "common/issues.txt",
        "party_issues = { economic_policy = { } trade_policy = { } "
        "religious_policy = { } citizenship_policy = { } war_policy = { } }\n",
    )
    write(
        g / "common/cultures.txt",
        "germanic = { north_german = { } }\nbritish_g = { british = { } }\n",
    )
    write(
        g / "history/countries/PRU - Prussia.txt",
        "primary_culture = north_german\ncivilized = yes\n",
    )
    write(g / "history/countries/ENG - UK.txt", "primary_culture = british\ncivilized = yes\n")
    write(g / "localisation/a.csv", "PRU_ADJ;Prussian;;;;;;;;;;;;;x\n")
    return Workspace.open(g, tmp_path / "mod")


def test_plan_and_write(tmp_path):
    ws = make(tmp_path)
    spec = PartySpec(
        "socialist",
        copy_from=("liberal",),
        policies={"economic_policy": "planned_economy"},
        loc_text="{adj} Socialists",
    )
    plan = plan_parties(ws, spec, CountryFilter())
    assert plan.created == ["PRU"]
    assert plan.skipped == {"ENG": "already has a socialist party", "REB": "has no parties"}
    prussia, loc = plan.changes
    assert (
        prussia.rel == "common/countries/Prussia.txt"
        and prussia.path.parent.parent.parent.name == "mod"
    )
    new = prussia.new_text
    assert '\tname = "PRU_socialist"\r\n' in new and "economic_policy = planned_economy" in new
    assert new.index("PRU_socialist") < new.index("# names")  # inserted after the last party
    assert parse_text(new).diagnostics == []
    assert (
        loc.new_text
        == "PRU_socialist;"
        + ";".join(["Prussian Socialists"] * 3)
        + ";;Prussian Socialists;;;;;;;;;x\r\n"
    )
    assert "+++ b/common/countries/Prussia.txt" in diff(plan.changes)
    assert write_changes(plan.changes, backup=False) is None
    assert (tmp_path / "mod/common/countries/Prussia.txt").read_bytes().count(b"\r\n") > 10


def test_filters_and_missing_policies(tmp_path):
    ws = make(tmp_path)
    plan = plan_parties(
        ws,
        PartySpec("fascist", copy_from=("liberal",)),
        CountryFilter(culture_groups={"british_g"}),
    )
    assert plan.created == ["ENG"]
    plan = plan_parties(ws, PartySpec("fascist"), CountryFilter(tags={"PRU"}))
    assert plan.created == [] and plan.skipped["PRU"].startswith("no value for economic_policy")
