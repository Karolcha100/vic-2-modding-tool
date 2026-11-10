import pytest

from vic2toolmod.generators.country import CountrySpec, plan_country, write_copies
from vic2toolmod.script import parse_text
from vic2toolmod.workspace import Workspace


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("latin-1"))


def make(tmp_path):
    g = tmp_path / "game"
    write(
        g / "common/countries.txt",
        'REB = "countries/rebels.txt"\nENG\t= "countries/United Kingdom.txt"\n\n'
        'dynamic_tags = yes # dynamic\nD01 = "countries/D01.txt"\n',
    )
    write(
        g / "common/countries/United Kingdom.txt",
        "color = { 1 2 3 }\ngraphical_culture = BritishGC\n\nparty = {\n"
        '\tname = "ENG_conservative"\n\tideology = conservative\n}\n'
        'party = {\n\tname = "liberal_party"\n\tideology = liberal\n}\n',
    )
    write(
        g / "history/countries/ENG - United Kingdom.txt",
        "capital = 300\nprimary_culture = british\nculture = scottish\nreligion = protestant\n"
        'government = hms_government\ncivilized = yes\noob = "ENG_oob.txt"\n'
        "ruling_party = ENG_conservative\nupper_house = {\n\tliberal = 100\n}\n"
        "foreign_investment = { USA = 10 }\n1861.1.1 = {\n\tdecision = x\n}\n",
    )
    write(g / "common/cultures.txt", "british_group = {\n\tbritish = { }\n\tboer = { }\n}\n")
    write(g / "common/religion.txt", "christian = {\n\tprotestant = { }\n}\n")
    write(g / "common/governments.txt", "hms_government = { }\ndemocracy = { }\n")
    write(g / "map/definition.csv", "province;red;green;blue;x;x\n300;1;2;3;x;x\n2087;4;5;6;x;x\n")
    write(g / "localisation/text.csv", "ENG_conservative;Tories;;;;;;;;;;;;;x\n")
    write(g / "gfx/flags/ENG.tga", "flag")
    write(g / "gfx/flags/ENG_fascist.tga", "f")
    (tmp_path / "mod").mkdir()
    return Workspace.open(g, tmp_path / "mod")


def test_new_country(tmp_path):
    ws = make(tmp_path)
    spec = CountrySpec(
        "BOE",
        "Boer Republic",
        "Boer",
        "ENG",
        (10, 20, 30),
        capital=2087,
        primary_culture="boer",
        cultures=[],
        government="democracy",
        civilized=False,
    )
    plan = plan_country(ws, spec)
    files = {c.rel: c.new_text for c in plan.changes}
    assert files["common/countries.txt"].split("\n")[:5] == [
        'REB = "countries/rebels.txt"',
        'ENG\t= "countries/United Kingdom.txt"',
        'BOE\t= "countries/Boer Republic.txt"',
        "",
        "dynamic_tags = yes # dynamic",
    ]
    country = parse_text(files["common/countries/Boer Republic.txt"])
    assert country.find("color").value.to_text().strip() == "{ 10 20 30 }"
    names = [p.value.find("name").value.to_text().strip() for p in country.assignments("party")]
    assert names == ['"BOE_conservative"', '"liberal_party"']
    hist = parse_text(files["history/countries/BOE - Boer Republic.txt"])
    got = {a.key_text: a.value.to_text().strip() for a in hist.assignments()}
    assert got == {
        "capital": "2087",
        "primary_culture": "boer",
        "religion": "protestant",
        "government": "democracy",
        "civilized": "no",
        "ruling_party": "BOE_conservative",
        "upper_house": "{\n\tliberal = 100\n}",
    }
    loc = files["localisation/00_vic2toolmod.csv"]
    assert (
        "BOE;Boer Republic;" in loc and "BOE_ADJ;Boer;" in loc and "BOE_conservative;Tories;" in loc
    )
    assert [d.name for _, d in plan.copies] == ["BOE.tga", "BOE_fascist.tga"]
    written = write_copies(plan.copies)
    assert written[0].read_bytes() == b"flag" and write_copies(plan.copies) == []


def test_country_checks(tmp_path):
    ws = make(tmp_path)
    ok = dict(name="X", adjective="X", template="ENG", color=(1, 1, 1))
    with pytest.raises(ValueError, match="already exists"):
        plan_country(ws, CountrySpec("ENG", **ok))
    with pytest.raises(ValueError, match="bad tag"):
        plan_country(ws, CountrySpec("1AB", **ok))
    with pytest.raises(ValueError, match="unknown culture"):
        plan_country(ws, CountrySpec("BOE", primary_culture="martian", **ok))
    with pytest.raises(ValueError, match="unknown province"):
        plan_country(ws, CountrySpec("BOE", capital=5, **ok))
    with pytest.raises(ValueError, match="template country"):
        plan_country(ws, CountrySpec("BOE", **{**ok, "template": "USA"}))
    plan = plan_country(ws, CountrySpec("BOE", **ok))  # all from the template
    hist = plan.changes[2].new_text
    assert "culture = scottish" in hist and "capital = 300" in hist and "oob" not in hist


def test_new_country_with_provinces(tmp_path):
    """K76 = C: cores in the provinces; with ``exists`` also owner and controller."""
    ws = make(tmp_path)
    write(
        tmp_path / "game/history/provinces/africa/2087 - Pretoria.txt",
        "owner = ENG\ncontroller = ENG\nadd_core = ENG\ntrade_goods = cattle\n"
        "1861.1.1 = { owner = ZUL }\n",
    )
    write(tmp_path / "game/history/provinces/africa/300 - London.txt", "trade_goods = coal\n")
    spec = CountrySpec("BOE", "Boer Republic", "Boer", "ENG", (1, 2, 3), capital=2087)
    spec.provinces = [2087, 300]
    plan = plan_country(ws, spec)
    files = {c.rel: c.new_text for c in plan.changes}
    pretoria = files["history/provinces/africa/2087 - Pretoria.txt"]
    assert "add_core = ENG\nadd_core = BOE\n" in pretoria and "owner = ENG" in pretoria
    assert files["history/provinces/africa/300 - London.txt"].startswith("add_core = BOE\n")
    assert any("owns no provinces at the start" in n for n in plan.notes)

    spec.exists = True
    plan = plan_country(ws, spec)
    files = {c.rel: c.new_text for c in plan.changes}
    pretoria = files["history/provinces/africa/2087 - Pretoria.txt"]
    assert pretoria.startswith("owner = BOE\ncontroller = BOE\nadd_core = ENG\nadd_core = BOE\n")
    london = files["history/provinces/africa/300 - London.txt"]
    assert "owner = BOE" in london and "controller = BOE" in london and "add_core = BOE" in london
    assert any("taken from ENG: 2087" in n for n in plan.notes)
    assert any("change the owner later in: 2087" in n for n in plan.notes)

    with pytest.raises(ValueError, match="unknown province"):
        plan_country(ws, CountrySpec("BOF", "B", "B", "ENG", (1, 2, 3), provinces=[9999]))
    with pytest.raises(ValueError, match="needs provinces"):
        plan_country(ws, CountrySpec("BOF", "B", "B", "ENG", (1, 2, 3), exists=True))
