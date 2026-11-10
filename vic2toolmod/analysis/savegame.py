"""The world from a save game (``.v2``) for the trigger tester and the map (K98 A).

A save is one big text file (RPM-sized games: 30–45 MB) in the script syntax
without spaces. The lossless parser of the editor would be slow on it, so
`parse_save` is a small reader of its own: one regular expression splits the
tokens (C speed), and the tree is lists of ``(key, value)`` pairs (repeated
keys stay repeated). A 43 MB save takes about 3 s.

`read_save` fills a `world.World` with what the save says, at the save's date:

- the date, the player's country, global flags, great powers (``great_nations``,
  indices into the countries in file order);
- countries: capital, government, cultures, religion, civilisation, prestige,
  money, infamy (``badboy``), plurality, national value, school, reform
  settings, technologies and inventions, flags, modifiers, upper house,
  ruling party (a number in the list of every party of
  ``common/countries/*.txt`` in ``common/countries.txt`` order, from 1) and its
  ideology, relations and their spheres (``level = 5``);
- provinces: owner, controller, cores, life rating, trade goods, buildings,
  modifiers and pops (type, culture, religion, size, militancy, consciousness);
- alliances, vassals, substates, unions, and the wars going on.

Continents, regions and culture groups come from the mod's files as with the
history. Secondary powers are not in a save: give them yourself.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from vic2toolmod.analysis.world import Country, Pop, Province, World, parse_date
from vic2toolmod.script.cst import Block, Scalar
from vic2toolmod.workspace import Workspace

Tree = list[tuple[str | None, Any]]
_TOKEN = re.compile(rb'"[^"]*"|[{}=]|[^\s{}="]+')
_TAG = re.compile(r"[A-Z][A-Z0-9]{2}")


def parse_save(data: bytes) -> Tree:
    """The save as nested lists of ``(key, value)``; a value is text or another list.

    Bare values in a list (``{ 1 2 3 }``) have the key None.
    """
    toks = _TOKEN.findall(data)
    n = len(toks)
    pos = 0

    def text(t: bytes) -> str:
        return t.decode("latin-1").strip('"')

    def block() -> Tree:
        nonlocal pos
        out: Tree = []
        while pos < n:
            t = toks[pos]
            if t == b"}":
                pos += 1
                return out
            if pos + 1 < n and toks[pos + 1] == b"=":
                key = text(t)
                pos += 2
                if pos < n and toks[pos] == b"{":
                    pos += 1
                    out.append((key, block()))
                elif pos < n:
                    out.append((key, text(toks[pos])))
                    pos += 1
            elif t == b"{":
                pos += 1
                out.append((None, block()))
            else:
                out.append((None, text(t)))
                pos += 1
        return out

    return block()


def _get(tree: Tree, key: str) -> Any:
    return next((v for k, v in tree if k == key), None)


def _all(tree: Tree, key: str) -> list[Any]:
    return [v for k, v in tree if k == key]


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def party_list(ws: Workspace) -> list[tuple[str, str, str]]:
    """Every party as ``(tag, name, ideology)`` in the game's order (a save's party numbers)."""
    out: list[tuple[str, str, str]] = []
    lf = ws.file("common/countries.txt")
    if lf is None:
        return out
    for entry in ws.document(lf.rel).assignments():
        if not isinstance(entry.value, Scalar):
            continue
        cf = ws.file("common/" + entry.value.value.strip('"'))
        if cf is None:
            continue
        for p in ws.document(cf.rel).assignments("party"):
            if isinstance(p.value, Block):
                name, ideo = p.value.find("name"), p.value.find("ideology")
                n = (
                    name.value.value.strip('"')
                    if name is not None and isinstance(name.value, Scalar)
                    else ""
                )
                i = (
                    ideo.value.value.lower()
                    if ideo is not None and isinstance(ideo.value, Scalar)
                    else ""
                )
                out.append((entry.key_text.upper(), n, i))
    return out


def read_save(ws: Workspace, data: bytes, name: str = "save") -> World:
    """A `World` from a save game's bytes (see the module's description)."""
    tree = parse_save(data)
    date = str(_get(tree, "date") or "1836.1.1")
    w = World(parse_date(date))
    w.source = name
    w.read_static(ws)
    w.player = str(_get(tree, "player") or "").upper()
    flags = _get(tree, "flags")
    if isinstance(flags, list):
        w.global_flags = {str(k).lower() for k, v in flags if k and v == "yes"}
    regs = ws.registries()
    pop_types = set(regs.names.get("pop_type", {}))
    parties = party_list(ws)
    for key, value in tree:
        if key is None or not isinstance(value, list):
            continue
        if key.isdigit():
            # land only: sea provinces have blocks too (no rgo, life rating or owner)
            if any(_get(value, k) is not None for k in ("owner", "rgo", "life_rating")):
                w.provinces[int(key)] = _province(w, int(key), value, pop_types)
        elif _TAG.fullmatch(key):
            w.countries[key] = _country(key, value, w.issues, parties)
        elif key == "diplomacy":
            for kind, entry in value:
                if kind in ("alliance", "vassal", "substate", "union") and isinstance(entry, list):
                    first, second = (
                        str(_get(entry, "first") or ""),
                        str(_get(entry, "second") or ""),
                    )
                    end = str(_get(entry, "end_date") or "9999.1.1")
                    try:
                        ends = parse_date(end)
                    except ValueError:
                        ends = (9999, 1, 1)
                    if first and second and ends > w.date:
                        w.relations.add((kind, first.upper(), second.upper()))
        elif key == "active_war":
            attackers = {str(v).upper() for v in _all(value, "attacker")}
            defenders = {str(v).upper() for v in _all(value, "defender")}
            if attackers and defenders:
                w.wars.append((attackers, defenders))
    nations = _get(tree, "great_nations")
    if isinstance(nations, list):
        # indices into common/countries.txt (from 0, REB first)
        tags: list[str] = []
        lf = ws.file("common/countries.txt")
        if lf is not None:
            tags = [e.key_text.upper() for e in ws.document(lf.rel).assignments()]
        idx = [int(v) for k, v in nations if k is None and str(v).isdigit()]
        w.great = [tags[i] for i in idx if 0 <= i < len(tags)]
    return w


def _province(w: World, pid: int, tree: Tree, pop_types: set[str]) -> Province:
    p = Province(pid)
    p.owner = str(_get(tree, "owner") or "").upper()
    p.controller = str(_get(tree, "controller") or "").upper()
    p.cores = {str(v).upper() for v in _all(tree, "core")}
    for key in ("life_rating", "colonial", "infrastructure"):
        v = _get(tree, key)
        if isinstance(v, str):
            p.values[key] = v.lower()
    rgo = _get(tree, "rgo")
    if isinstance(rgo, list) and isinstance(_get(rgo, "goods_type"), str):
        p.values["trade_goods"] = str(_get(rgo, "goods_type")).lower()
    for building in ("fort", "railroad", "naval_base"):
        b = _get(tree, building)
        if isinstance(b, list) and b and b[0][0] is None:
            p.values[building] = str(b[0][1])
    for m in _all(tree, "modifier"):
        if isinstance(m, list) and isinstance(_get(m, "modifier"), str):
            p.modifiers.add(str(_get(m, "modifier")).lower())
    pops: list[Pop] = []
    for kind, value in tree:
        if kind is None or not isinstance(value, list):
            continue
        # a pop: its type's name, or (types unknown) a block with an id and a size
        if kind.lower() not in pop_types and (
            _get(value, "id") is None or _get(value, "size") is None
        ):
            continue
        culture = religion = ""
        for k, v in value:
            if k and isinstance(v, str) and k.lower() in w.culture_group:
                culture, religion = k.lower(), v.lower()
        pops.append(
            Pop(
                kind.lower(),
                culture,
                religion,
                _num(_get(value, "size")),
                _num(_get(value, "mil")),
                _num(_get(value, "con")),
            )
        )
    if pops:
        w.pops[pid] = pops
    if pops or p.owner:
        w.pops_folder = w.pops_folder or "(save)"
    return p


def _country(
    tag: str, tree: Tree, issues: set[str], parties: list[tuple[str, str, str]]
) -> Country:
    c = Country(tag)
    for key in (
        "capital",
        "government",
        "primary_culture",
        "religion",
        "civilized",
        "prestige",
        "money",
        "badboy",
        "plurality",
        "nationalvalue",
        "schools",
        "literacy",
    ):
        v = _get(tree, key)
        if isinstance(v, str):
            c.values[key] = v.lower()
    for item, value in tree:
        if item and isinstance(value, str) and item.lower() in issues:
            c.values[item.lower()] = value.lower()
    tech = _get(tree, "technology")
    if isinstance(tech, list):
        for name, _ in tech:
            if name:
                c.values[name.lower()] = "1"
    culture = _get(tree, "culture")
    if isinstance(culture, list):
        c.cultures = {str(v).lower() for k, v in culture if k is None}
    flags = _get(tree, "flags")
    if isinstance(flags, list):
        c.flags = {str(k).lower() for k, v in flags if k and v == "yes"}
    for m in _all(tree, "modifier"):
        if isinstance(m, list) and isinstance(_get(m, "modifier"), str):
            c.modifiers.add(str(_get(m, "modifier")).lower())
    house = _get(tree, "upper_house")
    if isinstance(house, list):
        c.upper_house = {str(k).lower(): _num(v) for k, v in house if k}
    ruling = _get(tree, "ruling_party")
    if isinstance(ruling, str) and ruling.isdigit() and 0 < int(ruling) <= len(parties):
        party = parties[int(ruling) - 1]
        c.values["ruling_party"] = party[1].lower()
        c.party_ideology = party[2]
    for other, value in tree:
        if other and _TAG.fullmatch(other) and isinstance(value, list):
            rel = _get(value, "value")
            if isinstance(rel, str):
                c.relations[other] = int(_num(rel))
            if _get(value, "level") == "5":
                c.sphere.add(other)
    return c


def save_folders(ws: Workspace) -> list[Path]:
    """Folders that may hold save games.

    Victoria II's documents folder (also under Steam's Proton on Linux) with one
    folder per mod, and the game's tutorial.
    """
    roots = [
        Path.home() / "Documents" / "Paradox Interactive" / "Victoria II",
        Path.home() / "My Documents" / "Paradox Interactive" / "Victoria II",
    ]
    for steam in (Path.home() / ".local/share/Steam", Path.home() / ".steam/steam"):
        pfx = steam / "steamapps/compatdata/42960/pfx/drive_c/users/steamuser"
        roots.append(pfx / "Documents" / "Paradox Interactive" / "Victoria II")
        roots.append(pfx / "My Documents" / "Paradox Interactive" / "Victoria II")
    out: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        if (root / "save games").is_dir():
            out.append(root / "save games")
        out += sorted(p / "save games" for p in root.iterdir() if (p / "save games").is_dir())
    game = ws.project.game_dir
    if game is not None and (game / "tutorial").is_dir():
        out.append(game / "tutorial")
    seen: set[Path] = set()
    unique = []
    for p in out:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            unique.append(p)
    return unique


def read_save_file(ws: Workspace, path: Path) -> World:
    """`read_save` of a file."""
    return read_save(ws, path.read_bytes(), path.name)
