"""The world at a start date, read from the mod's history, and triggers checked against it (K75 B).

The trigger tester (`trigger_tester`, K53) asks the user for every fact. This
module answers what the history files say at a date (the game's start,
``1836.1.1``, by default):

- countries (``history/countries``): capital, cultures, religion, government,
  civilisation, prestige, literacy, plurality, national value, ruling party
  (and its ideology from ``common/countries``), upper house, technologies,
  reform settings, country / global flags, decisions taken - with the dated
  blocks up to the date applied in order;
- provinces (``history/provinces``): owner, controller, cores, trade goods,
  life rating, terrain, buildings;
- ``history/diplomacy``: alliances, vassals, substates, unions active at the
  date; ``history/wars``: wars going on at the date;
- ``map/continent.txt``, ``map/region.txt``, ``common/cultures.txt``.

`World.check` evaluates a trigger block in a country or province scope and
gives ``True`` / ``False`` / ``None`` (not known from history: pops, money,
relations, spheres of the game in progress …) with the reasons. Answers for
the tester's facts come from `World.answers`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from vic2toolmod.script.cst import Assignment, Block, Document, Node, Scalar
from vic2toolmod.workspace import Workspace

Date = tuple[int, int, int]
_DATE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_PROVINCE_FILE = re.compile(r"history/provinces/[^/]+/(\d+)(?!\d)")
_TAG = re.compile(r"[a-z][a-z0-9]{2}")


def parse_date(text: str) -> Date:
    """``"1836.1.1"`` -> ``(1836, 1, 1)``."""
    m = _DATE.fullmatch(text.strip())
    if not m:
        raise ValueError(f"bad date {text!r} (year.month.day, e.g. 1836.1.1)")
    return int(m[1]), int(m[2]), int(m[3])


def _scalar(node: Assignment) -> str:
    v = node.value
    if isinstance(v, Scalar):
        return v.value.strip('"')
    return ""


def _dated(doc: Document, date: Date) -> list[Assignment]:
    """Top-level items, then the items of dated blocks up to ``date`` in date order."""
    plain: list[Assignment] = []
    dated: list[tuple[Date, int, list[Assignment]]] = []
    for n, item in enumerate(doc.items):
        if not isinstance(item, Assignment):
            continue
        m = _DATE.fullmatch(item.key_text)
        if m:
            d = (int(m[1]), int(m[2]), int(m[3]))
            if d <= date and isinstance(item.value, Block):
                inner = [i for i in item.value.items if isinstance(i, Assignment)]
                dated.append((d, n, inner))
        else:
            plain.append(item)
    for _, _, inner in sorted(dated, key=lambda x: (x[0], x[1])):
        plain += inner
    return plain


@dataclass
class Country:
    """A country at the date (everything as lower-case text)."""

    tag: str
    values: dict[str, str] = field(default_factory=dict)  # capital, government, reforms, techs …
    cultures: set[str] = field(default_factory=set)  # accepted
    flags: set[str] = field(default_factory=set)
    decisions: set[str] = field(default_factory=set)
    upper_house: dict[str, float] = field(default_factory=dict)
    party_ideology: str = ""


@dataclass
class Province:
    """A province at the date."""

    id: int
    owner: str = ""
    controller: str = ""
    cores: set[str] = field(default_factory=set)
    values: dict[str, str] = field(default_factory=dict)  # trade_goods, life_rating, terrain …


@dataclass
class World:
    """The state the history files give at one date."""

    date: Date
    countries: dict[str, Country] = field(default_factory=dict)
    provinces: dict[int, Province] = field(default_factory=dict)
    global_flags: set[str] = field(default_factory=set)
    #: (kind, first, second): alliance / vassal / substate / union (first = overlord)
    relations: set[tuple[str, str, str]] = field(default_factory=set)
    wars: list[tuple[set[str], set[str]]] = field(default_factory=list)
    continent: dict[int, str] = field(default_factory=dict)
    regions: dict[str, set[int]] = field(default_factory=dict)
    culture_group: dict[str, str] = field(default_factory=dict)
    technologies: set[str] = field(default_factory=set)
    inventions: set[str] = field(default_factory=set)
    issues: set[str] = field(default_factory=set)
    #: The player's country (``ai = no`` for it, ``yes`` for the others); "" = unknown.
    player: str = ""

    # -- reading ---------------------------------------------------------------------
    @classmethod
    def read(cls, ws: Workspace, date: str = "1836.1.1") -> World:
        """Read the history of the open mod (with the game's files under it)."""
        w = cls(parse_date(date))
        regs = ws.registries()
        w.technologies = set(regs.names.get("technology", {}))
        w.inventions = set(regs.names.get("invention", {}))
        w.issues = set(regs.names.get("issue", {}))
        files = sorted(ws.project.files().items())
        parties: dict[str, str] = {}
        for low, f in files:
            if low.startswith("common/countries/") and low.endswith(".txt"):
                for p in ws.document(f.rel).assignments("party"):
                    if isinstance(p.value, Block):
                        name, ideo = p.value.find("name"), p.value.find("ideology")
                        if name is not None and ideo is not None:
                            parties[_scalar(name).lower()] = _scalar(ideo).lower()
        for low, f in files:
            if low.startswith("history/countries/") and low.endswith(".txt"):
                tag = low[len("history/countries/") :][:3]
                if _TAG.fullmatch(tag):
                    w._country(tag.upper(), ws.document(f.rel), parties)
            elif m := _PROVINCE_FILE.match(low):
                w._province(int(m[1]), ws.document(f.rel))
            elif low.startswith("history/diplomacy/") and low.endswith(".txt"):
                w._diplomacy(ws.document(f.rel))
            elif low.startswith("history/wars/") and low.endswith(".txt"):
                w._war(ws.document(f.rel))
        cont = ws.file("map/continent.txt")
        if cont is not None:
            for c in ws.document(cont.rel).items:
                if isinstance(c, Assignment) and isinstance(c.value, Block):
                    ps = c.value.find("provinces")
                    if ps is not None and isinstance(ps.value, Block):
                        for v in ps.value.items:
                            if isinstance(v, Scalar) and v.value.isdigit():
                                w.continent[int(v.value)] = c.key_text.lower()
        reg = ws.file("map/region.txt")
        if reg is not None:
            for r in ws.document(reg.rel).items:
                if isinstance(r, Assignment) and isinstance(r.value, Block):
                    w.regions[r.key_text.lower()] = {
                        int(v.value)
                        for v in r.value.items
                        if isinstance(v, Scalar) and v.value.isdigit()
                    }
        cul = ws.file("common/cultures.txt")
        if cul is not None:
            for g in ws.document(cul.rel).items:
                if isinstance(g, Assignment) and isinstance(g.value, Block):
                    for c in g.value.items:
                        if isinstance(c, Assignment) and isinstance(c.value, Block):
                            w.culture_group[c.key_text.lower()] = g.key_text.lower()
        return w

    def _country(self, tag: str, doc: Document, parties: dict[str, str]) -> None:
        c = Country(tag)
        for item in _dated(doc, self.date):
            key = item.key_text.lower()
            value = _scalar(item).lower()
            if key == "culture":
                c.cultures.add(value)
            elif key == "remove_accepted_culture":
                c.cultures.discard(value)
            elif key == "set_country_flag":
                c.flags.add(value)
            elif key == "clr_country_flag":
                c.flags.discard(value)
            elif key == "set_global_flag":
                self.global_flags.add(value)
            elif key == "clr_global_flag":
                self.global_flags.discard(value)
            elif key == "decision":
                c.decisions.add(value)
            elif key == "upper_house" and isinstance(item.value, Block):
                c.upper_house = {
                    i.key_text.lower(): float(_scalar(i) or 0)
                    for i in item.value.items
                    if isinstance(i, Assignment) and _scalar(i).replace(".", "", 1).isdigit()
                }
            elif value:
                c.values[key] = value
        c.party_ideology = parties.get(c.values.get("ruling_party", ""), "")
        self.countries[tag] = c

    def _province(self, pid: int, doc: Document) -> None:
        p = Province(pid)
        for item in _dated(doc, self.date):
            key = item.key_text.lower()
            value = _scalar(item)
            if key == "owner":
                p.owner = value.upper()
            elif key == "controller":
                p.controller = value.upper()
            elif key == "add_core":
                p.cores.add(value.upper())
            elif key == "remove_core":
                p.cores.discard(value.upper())
            elif value:
                p.values[key] = value.lower()
        self.provinces[pid] = p

    def _diplomacy(self, doc: Document) -> None:
        for item in doc.items:
            if not isinstance(item, Assignment) or not isinstance(item.value, Block):
                continue
            kind = item.key_text.lower()
            fields = {i.key_text.lower(): _scalar(i) for i in item.value.assignments()}
            first, second = fields.get("first", "").upper(), fields.get("second", "").upper()
            try:
                start = parse_date(fields.get("start_date", "1.1.1"))
                end = parse_date(fields.get("end_date", "9999.1.1"))
            except ValueError:
                continue
            if first and second and start <= self.date < end:
                self.relations.add((kind, first, second))

    def _war(self, doc: Document) -> None:
        attackers: set[str] = set()
        defenders: set[str] = set()
        for item in _dated(doc, self.date):
            key, value = item.key_text.lower(), _scalar(item).upper()
            if key == "add_attacker":
                attackers.add(value)
            elif key == "add_defender":
                defenders.add(value)
            elif key == "rem_attacker":
                attackers.discard(value)
            elif key == "rem_defender":
                defenders.discard(value)
        if attackers and defenders:
            self.wars.append((attackers, defenders))

    # -- facts -----------------------------------------------------------------------
    def owned(self, tag: str) -> list[Province]:
        """Provinces the country owns."""
        return [p for p in self.provinces.values() if p.owner == tag]

    def at_war(self, tag: str) -> set[str]:
        """Countries ``tag`` is at war with."""
        out: set[str] = set()
        for a, d in self.wars:
            if tag in a:
                out |= d
            if tag in d:
                out |= a
        return out

    def overlord(self, tag: str) -> str:
        """The country's overlord (vassal or substate), or ""."""
        for kind, first, second in self.relations:
            if kind in ("vassal", "substate") and second == tag:
                return first
        return ""

    # -- evaluation --------------------------------------------------------------------
    def check(self, block: Block | list[Node], scope: Scope) -> Verdict:
        """A trigger block (AND of its items) in a scope."""
        items = block.items if isinstance(block, Block) else block
        return _all([self.item(i, scope) for i in items if isinstance(i, Assignment)])

    def item(self, node: Assignment, scope: Scope) -> Verdict:
        """One trigger (or logic / scope block) in a scope."""
        key = node.key_text.lower()
        v = node.value
        if isinstance(v, Block):
            if key == "and":
                return self.check(v, scope)
            if key == "or":
                return _any([self.item(i, scope) for i in v.assignments()])
            if key == "not":
                return _not(_any([self.item(i, scope) for i in v.assignments()]))
            return self._scope_block(key, v, scope, node)
        if not isinstance(v, Scalar):
            return Verdict(None, [f"{key}: no value"])
        value = v.value.strip('"')
        if scope.kind == "country":
            return self._country_trigger(key, value, scope)
        return self._province_trigger(key, value, scope)

    def _ref(self, value: str, scope: Scope) -> str:
        """A tag written in a trigger: THIS / ROOT / FROM resolved where known."""
        low = value.lower()
        if low in ("this", "root"):
            return scope.root
        if low == "from":
            return ""
        return value.upper()

    def _country_trigger(self, key: str, value: str, scope: Scope) -> Verdict:
        tag = scope.tag
        c = self.countries.get(tag)
        low = value.lower()
        yes = low == "yes"

        def is_(b: bool, why: str = "") -> Verdict:
            return Verdict(b, [] if b else [why or f"{key} = {value}"])

        if key == "tag":
            return is_(tag == self._ref(value, scope))
        if key == "exists":
            other = tag if low in ("yes", "no") else self._ref(value, scope)
            there = bool(self.owned(other))
            return is_(
                there == (low != "no"),
                f"exists = {value} ({other} owns {len(self.owned(other))} provinces)",
            )
        if c is None:
            return Verdict(None, [f"{tag} has no history file"])
        if key == "ai":
            if not self.player:
                return Verdict(None, ["ai: choose the player's country"])
            return is_((tag != self.player) == yes)
        if key == "year":
            return is_(self.date[0] >= int(float(value)))
        if key == "month":
            return is_(self.date[1] >= int(float(value)))
        if key == "has_country_flag":
            return is_(low in c.flags)
        if key == "has_global_flag":
            return is_(low in self.global_flags)
        if key in ("government", "religion", "primary_culture", "nationalvalue"):
            return is_(c.values.get(key, "") == low, f"{key} is {c.values.get(key, '?')}")
        if key == "civilized":
            return is_((c.values.get("civilized", "no") == "yes") == yes)
        if key in ("prestige", "literacy", "plurality"):
            return is_(
                float(c.values.get(key, 0) or 0) >= float(value), f"{key} is {c.values.get(key, 0)}"
            )
        if key == "capital":
            return is_(c.values.get("capital", "") == value)
        if key == "continent":  # of the capital
            cap = c.values.get("capital", "")
            here = self.continent.get(int(cap), "") if cap.isdigit() else ""
            return is_(here == low, f"the capital is in {here or '?'}")
        if key == "tech_school":
            return is_(
                c.values.get("schools", "") == low, f"school is {c.values.get('schools', '?')}"
            )
        if key == "ruling_party_ideology":
            return is_(
                c.party_ideology == low, f"ruling party ideology is {c.party_ideology or '?'}"
            )
        if key in ("accepted_culture", "culture"):
            return is_(
                low in c.cultures or (key == "culture" and c.values.get("primary_culture") == low)
            )
        if key == "is_culture_group":
            group = self.culture_group.get(c.values.get("primary_culture", ""), "")
            same = self.countries.get(value.upper())  # a tag: that country's culture group
            if same is not None:
                low = self.culture_group.get(same.values.get("primary_culture", ""), "")
            return is_(group == low, f"culture group is {group or '?'}")
        if key == "owns":
            p = self.provinces.get(int(value)) if value.isdigit() else None
            return is_(
                p is not None and p.owner == tag, f"owns = {value} (owner {p.owner if p else '?'})"
            )
        if key == "controls":
            p = self.provinces.get(int(value)) if value.isdigit() else None
            return is_(p is not None and (p.controller or p.owner) == tag)
        if key == "is_core":
            p = self.provinces.get(int(value)) if value.isdigit() else None
            return is_(p is not None and tag in p.cores)
        if key == "num_of_cities":
            return is_(
                len(self.owned(tag)) >= int(float(value)), f"{len(self.owned(tag))} provinces"
            )
        if key in ("vassal_of", "substate_of"):
            kind = "substate" if key == "substate_of" else "vassal"
            other = self._ref(value, scope)
            return is_(
                (kind, other, tag) in self.relations
                or (key == "vassal_of" and ("substate", other, tag) in self.relations)
            )
        if key == "is_vassal":
            return is_(bool(self.overlord(tag)) == yes)
        if key == "is_our_vassal":
            other = self._ref(value, scope)
            return is_(any((k, tag, other) in self.relations for k in ("vassal", "substate")))
        if key == "is_substate":
            return is_(any(k == "substate" and s == tag for k, _, s in self.relations) == yes)
        if key == "alliance_with":
            other = self._ref(value, scope)
            return is_(
                ("alliance", tag, other) in self.relations
                or ("alliance", other, tag) in self.relations
            )
        if key == "war":
            return is_(bool(self.at_war(tag)) == yes)
        if key == "war_with":
            return is_(self._ref(value, scope) in self.at_war(tag))
        if key in ("truce_with", "in_sphere", "is_sphere_leader_of", "part_of_sphere"):
            # at the start of a game there are no truces and no spheres yet
            if self.date == (1836, 1, 1):
                return is_(False, f"{key}: none at the start of the game")
            return Verdict(None, [f"{key}: not in the history files"])
        if key in self.technologies or key in self.inventions:
            return is_(c.values.get(key, "0") not in ("0", "", "no"), f"{key}: not researched")
        if key in self.issues:
            return is_(c.values.get(key, "") == low, f"{key} is {c.values.get(key, '?')}")
        if key == "upper_house" or key == "has_country_modifier":
            return Verdict(None, [f"{key}: not decided from history"])
        return Verdict(None, [f"{key}: not known from history"])

    def _province_trigger(self, key: str, value: str, scope: Scope) -> Verdict:
        p = self.provinces.get(scope.province)
        if p is None:
            return Verdict(None, [f"province {scope.province} has no history file"])
        low = value.lower()

        def is_(b: bool, why: str = "") -> Verdict:
            return Verdict(b, [] if b else [why or f"{key} = {value} (province {p.id})"])

        if key == "province_id":
            return is_(str(p.id) == value)
        if key == "owned_by":
            return is_(p.owner == self._ref(value, scope), f"owned by {p.owner or 'nobody'}")
        if key == "controlled_by":
            return is_((p.controller or p.owner) == self._ref(value, scope))
        if key == "is_core":
            return is_(self._ref(value, scope) in p.cores)
        if key == "empty":
            return is_((not p.owner) == (low == "yes"))
        if key == "continent":
            return is_(
                self.continent.get(p.id, "") == low, f"continent is {self.continent.get(p.id, '?')}"
            )
        if key == "region":
            return is_(p.id in self.regions.get(low, set()))
        if key in ("trade_goods", "terrain"):
            return is_(p.values.get(key, "") == low)
        if key == "life_rating":
            return is_(float(p.values.get(key, 0) or 0) >= float(value))
        if key == "is_capital":
            owner = self.countries.get(p.owner)
            return is_(
                (owner is not None and owner.values.get("capital") == str(p.id)) == (low == "yes")
            )
        if key in ("tag", "exists", "has_country_flag", "government", "civilized", "ai", "year"):
            if not p.owner:
                return Verdict(False, [f"province {p.id} has no owner"])
            return self._country_trigger(key, value, Scope("country", scope.root, p.owner, 0))
        return Verdict(None, [f"{key}: not known from history"])

    def _scope_block(self, key: str, block: Block, scope: Scope, node: Assignment) -> Verdict:
        root = scope.root
        if key.isdigit():
            return self.check(block, Scope("province", root, "", int(key)))
        if _TAG.fullmatch(key) and key.upper() in self.countries:
            return self.check(block, Scope("country", root, key.upper(), 0))
        if scope.kind == "province":
            p = self.provinces.get(scope.province)
            if key in ("owner", "controller"):
                who = (p.owner if key == "owner" else (p.controller or p.owner)) if p else ""
                if not who:
                    return Verdict(False, [f"{key}: province {scope.province} has none"])
                return self.check(block, Scope("country", root, who, 0))
            return Verdict(None, [f"{key} = {{ }}: not known from history"])
        tag = scope.tag
        c = self.countries.get(tag)
        if key == "capital_scope":
            cap = c.values.get("capital", "") if c else ""
            if not cap.isdigit():
                return Verdict(None, [f"{tag} has no capital in history"])
            return self.check(block, Scope("province", root, "", int(cap)))
        if key in ("any_owned_province", "all_core", "any_core"):
            if key == "any_owned_province":
                ps = self.owned(tag)
            else:
                ps = [p for p in self.provinces.values() if tag in p.cores]
            verdicts = [self.check(block, Scope("province", root, "", p.id)) for p in ps]
            if key == "all_core":
                return _all(verdicts) if verdicts else Verdict(True)
            return _any(verdicts) if verdicts else Verdict(False, [f"{key}: {tag} has none"])
        if key == "overlord":
            lord = self.overlord(tag)
            if not lord:
                return Verdict(False, [f"{tag} has no overlord"])
            return self.check(block, Scope("country", root, lord, 0))
        if key in ("any_country", "any_greater_power", "any_neighbor_country", "war_countries"):
            if key == "any_country":
                verdicts = [
                    self.check(block, Scope("country", root, t, 0))
                    for t in self.countries
                    if self.owned(t)
                ]
                return _any(verdicts)
            if key == "war_countries":
                verdicts = [
                    self.check(block, Scope("country", root, t, 0)) for t in self.at_war(tag)
                ]
                return (
                    _any(verdicts) if verdicts else Verdict(False, [f"{tag} is at war with nobody"])
                )
        if key == "upper_house" and c is not None and c.upper_house:
            fields = {i.key_text.lower(): _scalar(i).lower() for i in block.assignments()}
            ideo, share = fields.get("ideology", ""), fields.get("value", "")
            total = sum(c.upper_house.values()) or 1
            if ideo and share:
                have = c.upper_house.get(ideo, 0) / total
                return Verdict(
                    have >= float(share),
                    [] if have >= float(share) else [f"upper house {ideo} is {have:.2f}"],
                )
        return Verdict(None, [f"{key} = {{ }}: not known from history"])

    def answers(self, tester: Any, block: Block, tag: str) -> dict[str, bool]:
        """Answers for the facts of `trigger_tester.TriggerTester` (only those known)."""
        scope = Scope("country", tag, tag, 0)
        out: dict[str, bool] = {}
        for fact in tester.facts(block):
            node = _node_by_id(block, fact.id)
            if node is not None:
                v = self.item(node, scope).value
                if v is not None:
                    out[fact.id] = v
        return out


@dataclass(frozen=True)
class Scope:
    """Where a trigger is checked: a country (tag) or a province; ``root`` is THIS."""

    kind: str  # "country" | "province"
    root: str
    tag: str
    province: int


@dataclass
class Verdict:
    """True / False / None (not known) and why (false or unknown parts)."""

    value: bool | None
    reasons: list[str] = field(default_factory=list)


def _all(vs: list[Verdict]) -> Verdict:
    if any(v.value is False for v in vs):
        return Verdict(False, [r for v in vs if v.value is False for r in v.reasons])
    if any(v.value is None for v in vs):
        return Verdict(None, [r for v in vs if v.value is None for r in v.reasons])
    return Verdict(True)


def _any(vs: list[Verdict]) -> Verdict:
    if any(v.value is True for v in vs):
        return Verdict(True)
    if any(v.value is None for v in vs):
        return Verdict(None, [r for v in vs if v.value is None for r in v.reasons])
    return Verdict(False, [r for v in vs for r in v.reasons][:5])


def _not(v: Verdict) -> Verdict:
    if v.value is None:
        return v
    return Verdict(not v.value, [] if v.value is False else ["NOT: a condition inside is true"])


def _node_by_id(block: Block, fid: str) -> Assignment | None:
    """The item a tester fact id (``"3.0.1"``) points at."""
    items: list[Node] = block.items
    node: Assignment | None = None
    for part in fid.split("."):
        n = int(part)
        if n >= len(items) or not isinstance(items[n], Assignment):
            return None
        node = items[n]  # type: ignore[assignment]
        assert node is not None
        items = node.value.items if isinstance(node.value, Block) else []
    return node
