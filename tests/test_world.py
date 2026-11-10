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
    assert check(w, "invention = flintlock_rifles").value is True
    assert check(w, "invention = machine_guns").value is False
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
    berlin = d["provinces"][549]
    assert {k: berlin[k] for k in ("rgb", "name", "owner", "cores", "land", "continent")} == {
        "rgb": [1, 2, 3],
        "name": "x",
        "owner": "PRU",
        "cores": ["PRU"],
        "land": True,
        "continent": "europe",
    }
    assert d["colors"]["PRU"] == [10, 20, 30]


def test_pops_and_powers(tmp_path):
    """B2: pops of history/pops (the latest folder up to the date) and the powers."""
    ws = make(tmp_path)
    write(
        tmp_path / "game/history/pops/1836.1.1/Germany.txt",
        "549 = { farmers = { culture = north_german religion = protestant\n"
        "size = 3000 militancy = 2 }\n"
        "clergymen = { culture = jewish religion = jewish size = 1000 } }\n"
        "550 = { farmers = { culture = south_german religion = catholic size = 500 } }\n",
    )
    write(tmp_path / "game/history/pops/1861.1.1/Germany.txt", "549 = { farmers = { size = 1 } }\n")
    w = World.read(ws)
    assert w.pops_folder == "1836.1.1" and len(w.pops[549]) == 2
    assert check(w, "total_pops = 4000").value is True
    assert check(w, "total_pops = 4001").value is False
    assert check(w, "has_pop_culture = jewish").value is True
    assert check(w, "average_militancy = 1.5").value is True  # 2 * 3000 / 4000
    assert check(w, "capital_scope = { culture = north_german religion = protestant }").value
    assert check(w, "any_pop = { culture = jewish type = clergymen }").value is True
    assert check(w, "any_pop = { militancy = 3 }").value is False
    assert check(w, "550 = { culture = south_german total_pops = 500 }").value is True
    assert check(w, "is_greater_power = yes").value is None
    w.great, w.secondary = ["PRU"], ["SAX"]
    assert check(w, "is_greater_power = yes").value is True
    assert check(w, "is_secondary_power = yes").value is False
    assert check(w, "any_greater_power = { tag = PRU }").value is True
    assert w.guess_powers() == (["PRU"], [])  # SAX is not civilised in this history
    assert World.read(ws, "1870.1.1").pops_folder == "1861.1.1"


def test_neighbours(tmp_path):
    """K97 B: provinces that touch on the map; neighbour triggers."""
    import struct

    from vic2toolmod.analysis.provmap import adjacency

    ws = make(tmp_path)
    rows = [bytes((3, 2, 1, 3, 2, 1)) + b"\0\0", bytes((6, 5, 4, 6, 5, 4)) + b"\0\0"]
    header = b"BM" + struct.pack("<IHHI", 54 + 16, 0, 0, 54)
    header += struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 24, 0, 16, 0, 0, 0, 0)
    (tmp_path / "game/map/provinces.bmp").write_bytes(header + b"".join(rows))
    assert adjacency(ws) == {549: {550}, 550: {549}}
    w = World.read(ws)
    assert check(w, "neighbour = SAX").value is None  # no map given yet
    w.neighbours = adjacency(ws)
    assert check(w, "neighbour = SAX").value is True
    assert check(w, "any_neighbor_country = { tag = SAX }").value is True
    assert check(w, "549 = { any_neighbor_province = { province_id = 550 } }").value is True
    assert check(w, "any_neighbor_province = { owned_by = SAX }").value is True
    assert check(w, "is_coastal = no").value is True
    write(tmp_path / "game/map/adjacencies.csv", "From;To;Type\n549;550;impassable\n")
    ws.project._files = None  # a new file: scan the folders again
    assert adjacency(ws) == {549: set(), 550: set()}


def test_map_endpoints(tmp_path):
    """K97 A: where a trigger holds on the map; one province's details."""
    from vic2toolmod.server.app import ApiError, Engine

    engine = Engine(make(tmp_path))
    r = engine.map_trigger({"text": "is_core = PRU", "scope": "province"})
    assert r["results"] == {549: True, 550: True} and r["true"] == 2
    r = engine.map_trigger({"text": "tag = PRU", "scope": "owner"})
    assert r["results"] == {549: True, 550: False}
    r = engine.map_trigger({"text": "money = 5", "scope": "owner"})
    assert r["unknown"] == 2
    with pytest.raises(ApiError, match="the trigger"):
        engine.map_trigger({"text": "a = { b"})
    d = engine.map_province(550, "1836.1.1")
    assert d["file"] == "history/provinces/germany/550 - Dresden.txt"
    assert (
        d["owner"] == "SAX"
        and d["cores"] == ["PRU", "SAX"]
        and d["values"]["trade_goods"] == "coal"
    )
    info = engine.map_info("1836.1.1")
    assert info["provinces"][550]["trade_goods"] == "coal" and "culture_colors" in info


SAVE = b"""date="1850.6.1"
player="PRU"
flags=
{
	crimean_war=yes
}
549=
{
	name="Berlin"
	owner="PRU"
	controller="PRU"
	core="PRU"
	railroad=
	{
		2 0.000
	}
	modifier=
	{
		modifier=nitrates
		date="1.1.1"
	}
	farmers=
	{
		id=1
		size=5000
		north_german=protestant
		mil=3.5
		con=1.0
	}
}
550=
{
	owner="SAX"
	core="SAX"
}
3001=
{
	name="North Sea"
}
REB=
{
}
PRU=
{
	capital=549
	technology=
	{
		flintlock_rifles={1 0.000}
	}
	ruling_party=1
	primary_culture="north_german"
	money=12345.6
	civilized=yes
	modifier=
	{
		modifier=good_harvest
		date="1851.1.1"
	}
	SAX=
	{
		value=150
		level=5
	}
}
SAX=
{
	capital=550
}
diplomacy=
{
	alliance=
	{
		first="PRU"
		second="SAX"
		start_date="1840.1.1"
	}
}
great_nations=
{
0 }
"""


def test_save_game(tmp_path):
    """K98 A: the world from a save game."""
    from vic2toolmod.analysis.savegame import parse_save, read_save

    ws = make(tmp_path)
    tree = parse_save(b'a=1 b={ 1 2 } c="x y"')
    assert tree == [("a", "1"), ("b", [(None, "1"), (None, "2")]), ("c", "x y")]
    w = read_save(ws, SAVE, "test.v2")
    assert w.source == "test.v2" and w.date == (1850, 6, 1) and w.player == "PRU"
    assert w.great == ["PRU"]  # index 0 of common/countries.txt here (PRU, SAX)
    pru = w.countries["PRU"]
    assert pru.party_ideology == "conservative" and pru.modifiers == {"good_harvest"}
    assert pru.relations == {"SAX": 150} and pru.sphere == {"SAX"}
    assert w.provinces[549].values["railroad"] == "2" and w.pops[549][0].militancy == 3.5
    assert 3001 not in w.provinces  # sea
    for t in (
        "money = 10000",
        "has_country_modifier = good_harvest",
        "is_sphere_leader_of = SAX",
        "SAX = { in_sphere = PRU part_of_sphere = yes sphere_owner = { tag = PRU } }",
        "relation = { who = SAX value = 100 }",
        "alliance_with = SAX",
        "has_global_flag = crimean_war",
        "flintlock_rifles = 1",
        "is_greater_power = yes",
        "capital_scope = { has_province_modifier = nitrates average_militancy = 3 }",
    ):
        assert check(w, t).value is True, t
    assert check(w, "money = 20000").value is False
    assert check(w, "truce_with = SAX").value is None  # not read from saves yet
