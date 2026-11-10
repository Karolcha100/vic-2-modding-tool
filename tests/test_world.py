"""The world at a start date from the history, triggers checked against it (K75 B)."""

import pytest

from vic2toolmod.analysis.world import Scope, World, parse_date
from vic2toolmod.script import parse_text
from vic2toolmod.workspace import Workspace


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("latin-1"))


def make(tmp_path):
    g = tmp_path / "game"
    write(
        g / "common/countries.txt", 'PRU = "countries/Prussia.txt"\nSAX = "countries/Saxony.txt"\n'
    )
    write(
        g / "common/countries/Prussia.txt",
        'party = { name = "PRU_cons" ideology = conservative }\n',
    )
    write(g / "common/countries/Saxony.txt", "color = { 1 2 3 }\n")
    write(g / "common/cultures.txt", "germanic = { north_german = { } south_german = { } }\n")
    write(g / "technologies/army.txt", "flintlock_rifles = { }\nbreech_loaded_rifles = { }\n")
    write(
        g / "common/issues.txt",
        "political_reforms = { slavery = { yes_slavery = { } no_slavery = { } } }\n",
    )
    write(
        g / "history/countries/PRU - Prussia.txt",
        "capital = 549\nprimary_culture = north_german\nculture = south_german\n"
        "government = absolute_monarchy\ncivilized = yes\nprestige = 30\n"
        "schools = army_tech_school\n"
        "slavery = no_slavery\nruling_party = PRU_cons\nflintlock_rifles = 1\n"
        "set_country_flag = existing_country\n"
        "upper_house = { conservative = 60 liberal = 40 }\n"
        "1840.1.1 = { set_country_flag = later government = democracy }\n",
    )
    write(
        g / "history/countries/SAX - Saxony.txt", "capital = 550\nprimary_culture = south_german\n"
    )
    write(
        g / "history/provinces/germany/549 - Berlin.txt",
        "owner = PRU\ncontroller = PRU\nadd_core = PRU\n",
    )
    write(
        g / "history/provinces/germany/550 - Dresden.txt",
        "owner = SAX\ncontroller = SAX\nadd_core = SAX\nadd_core = PRU\ntrade_goods = coal\n"
        "1837.1.1 = { owner = PRU }\n",
    )
    write(
        g / "history/diplomacy/Alliances.txt",
        "vassal = { first = PRU second = SAX start_date = 1800.1.1 end_date = 1850.1.1 }\n",
    )
    write(g / "history/wars/w.txt", "1835.1.1 = { add_attacker = PRU add_defender = SAX }\n")
    write(g / "map/continent.txt", "europe = { provinces = { 549 550 } }\n")
    write(g / "map/region.txt", "GER_1 = { 549 550 }\n")
    write(g / "map/definition.csv", "province;r;g;b;x;x\n549;1;2;3;x;x\n550;4;5;6;x;x\n")
    (tmp_path / "mod").mkdir()
    return Workspace.open(g, tmp_path / "mod")


def check(world, text, tag="PRU"):
    block = parse_text("t = { " + text + " }").items[0].value
    return world.check(block, Scope("country", tag, tag, 0))


def test_reads_the_history_at_a_date(tmp_path):
    ws = make(tmp_path)
    w = World.read(ws)
    pru = w.countries["PRU"]
    assert pru.values["government"] == "absolute_monarchy" and "later" not in pru.flags
    assert pru.party_ideology == "conservative" and pru.cultures == {"south_german"}
    assert w.provinces[550].owner == "SAX" and w.provinces[550].cores == {"SAX", "PRU"}
    assert ("vassal", "PRU", "SAX") in w.relations and w.at_war("PRU") == {"SAX"}
    later = World.read(ws, "1841.1.1")
    assert later.countries["PRU"].values["government"] == "democracy"
    assert later.provinces[550].owner == "PRU" and "later" in later.countries["PRU"].flags
    with pytest.raises(ValueError, match="bad date"):
        parse_date("1836")


def test_triggers(tmp_path):
    w = World.read(make(tmp_path))
    yes = [
        "tag = PRU",
        "exists = yes",
        "owns = 549",
        "is_core = 550",
        "government = absolute_monarchy",
        "civilized = yes",
        "prestige = 20",
        "has_country_flag = existing_country",
        "ruling_party_ideology = conservative",
        "accepted_culture = south_german",
        "is_culture_group = germanic",
        "flintlock_rifles = 1",
        "slavery = no_slavery",
        "tech_school = army_tech_school",
        "continent = europe",
        "war = yes",
        "war_with = SAX",
        "is_our_vassal = SAX",
        "capital_scope = { province_id = 549 continent = europe }",
        "any_owned_province = { owned_by = THIS }",
        "SAX = { vassal_of = PRU is_vassal = yes }",
        "550 = { owner = { tag = SAX } region = GER_1 trade_goods = coal }",
        "upper_house = { ideology = conservative value = 0.5 }",
        "OR = { tag = ENG prestige = 10 }",
        "NOT = { has_country_flag = later }",
        "NOT = { in_sphere = ENG }",  # no spheres at the start of the game
    ]
    for t in yes:
        assert check(w, t).value is True, t
    assert check(w, "breech_loaded_rifles = 1").value is False
    v = check(w, "tag = PRU money = 1000")
    assert v.value is None and "money: not known from history" in v.reasons
    assert check(w, "tag = SAX money = 1000").value is False  # decided without the unknown part
    assert check(w, "ai = no").value is None
    w.player = "PRU"
    assert check(w, "ai = no").value is True and check(w, "ai = yes", "SAX").value is True


def test_api(tmp_path):
    from vic2toolmod.server.app import ApiError, Engine

    ws = make(tmp_path)
    write(
        tmp_path / "mod/decisions/d.txt",
        "political_decisions = { d = {\n"
        "potential = { tag = PRU war = yes }\nallow = { money = 5 } } }\n",
    )
    ws.project._files = None
    engine = Engine(ws)
    text = ws.document("decisions/d.txt").text
    offset = text.index("tag = PRU")
    r = engine.trigger_world({"rel": "decisions/d.txt", "offset": offset, "tag": "PRU"})
    assert (
        r["value"] is True and r["result"]["value"] is True and set(r["answers"].values()) == {True}
    )
    countries = engine.trigger_countries({"rel": "decisions/d.txt", "offset": offset})
    assert countries == {"true": ["PRU"], "unknown": [], "false": 1}
    allow = text.index("money")
    r = engine.trigger_world({"rel": "decisions/d.txt", "offset": allow, "tag": "PRU"})
    assert r["value"] is None and r["answers"] == {}
    with pytest.raises(ApiError, match="no history"):
        engine.trigger_world({"rel": "decisions/d.txt", "offset": offset, "tag": "XXX"})


def test_province_map(tmp_path):
    """K75 A / @A6: the province picture (north in the first stored row) and its data."""
    import struct

    from vic2toolmod.analysis.provmap import id_image, info, read_bmp

    ws = make(tmp_path)
    # 2 x 2: top row Berlin (549: 1 2 3), bottom row Dresden (550: 4 5 6); BGR, rows padded to 4
    rows = [bytes((3, 2, 1, 3, 2, 1)) + b"\0\0", bytes((6, 5, 4, 6, 5, 4)) + b"\0\0"]
    header = b"BM" + struct.pack("<IHHI", 54 + 16, 0, 0, 54)
    header += struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 24, 0, 16, 0, 0, 0, 0)
    (tmp_path / "game/map/provinces.bmp").write_bytes(header + b"".join(rows))
    assert read_bmp((tmp_path / "game/map/provinces.bmp").read_bytes()) == (
        2,
        2,
        bytes((1, 2, 3, 1, 2, 3, 4, 5, 6, 4, 5, 6)),
    )
    im = id_image(ws, 2)
    assert (im.width, im.height) == (1, 1) and im.png.startswith(b"\x89PNG")
    write(tmp_path / "game/common/countries/Prussia.txt", "color = { 10 20 30 }\n")
    d = info(ws, World.read(ws))
    assert d["provinces"][549] == {
        "rgb": [1, 2, 3],
        "name": "x",
        "owner": "PRU",
        "cores": ["PRU"],
        "land": True,
    }
    assert d["colors"]["PRU"] == [10, 20, 30]
