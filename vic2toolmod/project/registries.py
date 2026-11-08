"""Registries of names defined by the game and the mod (tags, cultures, …).

Each registry maps a lower-case name to its `Definition` (original spelling,
file, line). The extractors follow the layout of the vanilla 3.04 files; see
``docs/index.md`` for the list.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from vic2toolmod.project.layout import Project, ProjectFile
from vic2toolmod.project.localisation import Localisation, load_localisation
from vic2toolmod.script.cst import Assignment, Block, Document, Node
from vic2toolmod.script.parser import parse_file


@dataclass(frozen=True, slots=True)
class Definition:
    """Where a name is defined.

    Attributes:
        name: Original spelling.
        file: Relative path of the defining file.
        line: Line number (1-based), 0 if unknown.
    """

    name: str
    file: str
    line: int = 0


@dataclass
class Registries:
    """All registries of a project.

    Attributes:
        names: Registry name -> lower-case name -> definition.
        tested: Flags tested somewhere (``has_country_flag = x``), first use.
        localisation: The project's localisation (keys are also in ``names``).
        duplicates: Registry name -> later definitions of names already defined
            (only meaningful for registries where duplicates are mistakes,
            such as event ids).
    """

    names: dict[str, dict[str, Definition]] = field(default_factory=dict)
    duplicates: dict[str, list[Definition]] = field(default_factory=dict)
    tested: dict[str, dict[str, Definition]] = field(default_factory=dict)
    localisation: Localisation | None = None

    def add(self, registry: str, name: str, file: str, line: int = 0) -> None:
        """Register a name (the first definition wins, later ones go to `duplicates`)."""
        reg = self.names.setdefault(registry, {})
        low = name.lower()
        if low in reg:
            self.duplicates.setdefault(registry, []).append(Definition(name, file, line))
        else:
            reg[low] = Definition(name, file, line)

    def has(self, registry: str, name: str) -> bool | None:
        """Whether ``name`` exists; ``None`` if the registry is not known at all."""
        reg = self.names.get(registry)
        if reg is None:
            return None
        return name.lower() in reg

    def get(self, registry: str, name: str) -> Definition | None:
        """Definition of a name, if any."""
        return self.names.get(registry, {}).get(name.lower())

    def __contains__(self, registry: str) -> bool:
        return registry in self.names


_DocCache = dict[str, Document]


def _docs(
    project: Project, pattern: str, cache: _DocCache
) -> Iterator[tuple[ProjectFile, Document]]:
    for f in project.glob(pattern):
        doc = cache.get(f.rel)
        if doc is None:
            doc, _ = parse_file(f.path)
            cache[f.rel] = doc
        yield f, doc


def _blocks(items: Sequence[Node]) -> Iterator[Assignment]:
    for i in items:
        if isinstance(i, Assignment) and isinstance(i.value, Block):
            yield i


def _top(
    reg: Registries,
    registry: str,
    project: Project,
    pattern: str,
    cache: _DocCache,
    blocks_only: bool = True,
    skip: frozenset[str] = frozenset(),
) -> None:
    """Every top-level key of matching files."""
    for f, doc in _docs(project, pattern, cache):
        for item in doc.items:
            if not isinstance(item, Assignment):
                continue
            if blocks_only and not isinstance(item.value, Block):
                continue
            if item.key_text.lower() in skip:
                continue
            reg.add(registry, item.key_text, f.rel, doc.position(item.start)[0])


def _two_level(
    reg: Registries,
    group_registry: str | None,
    registry: str,
    project: Project,
    pattern: str,
    cache: _DocCache,
) -> None:
    """``group = { name = { ... } }``: groups and the block-valued names inside them."""
    for f, doc in _docs(project, pattern, cache):
        for group in _blocks(doc.items):
            if group_registry:
                reg.add(group_registry, group.key_text, f.rel, doc.position(group.start)[0])
            assert isinstance(group.value, Block)
            for item in _blocks(group.value.items):
                reg.add(registry, item.key_text, f.rel, doc.position(item.start)[0])


def _countries(reg: Registries, project: Project, cache: _DocCache) -> None:
    for f, doc in _docs(project, "common/countries.txt", cache):
        for item in doc.items:
            if isinstance(item, Assignment) and item.key_text.lower() != "dynamic_tags":
                reg.add("country", item.key_text, f.rel, doc.position(item.start)[0])


def _issues(reg: Registries, project: Project, cache: _DocCache) -> None:
    for f, doc in _docs(project, "common/issues.txt", cache):
        for category in _blocks(doc.items):
            reg.add("issue_category", category.key_text, f.rel, doc.position(category.start)[0])
            assert isinstance(category.value, Block)
            for issue in _blocks(category.value.items):
                reg.add("issue", issue.key_text, f.rel, doc.position(issue.start)[0])
                assert isinstance(issue.value, Block)
                for option in _blocks(issue.value.items):
                    reg.add("issue_option", option.key_text, f.rel, doc.position(option.start)[0])


def _pop_types(reg: Registries, project: Project, cache: _DocCache) -> None:
    for f in project.glob("poptypes/*.txt"):
        reg.add("pop_type", PurePosixPath(f.rel).stem, f.rel, 1)


def _provinces(reg: Registries, project: Project, cache: _DocCache) -> None:
    definition = project.file("map/definition.csv")
    if definition is not None:
        text = definition.path.read_bytes().decode("latin-1")
        for n, line in enumerate(text.splitlines(), 1):
            first = line.split(";", 1)[0].strip()
            if first.isdigit() and first != "0":
                reg.add("province", first, definition.rel, n)
    for f in project.glob("history/provinces/*/*.txt"):
        m = re.match(r"\s*(\d+)", PurePosixPath(f.rel).name)
        if m:
            reg.add("province", m[1], f.rel, 1)


def _events(reg: Registries, project: Project, cache: _DocCache) -> None:
    for f, doc in _docs(project, "events/*.txt", cache):
        for ev in _blocks(doc.items):
            assert isinstance(ev.value, Block)
            id_ = ev.value.find("id")
            if id_ is not None and id_.value is not None and not isinstance(id_.value, Block):
                reg.add("event", id_.value.value, f.rel, doc.position(id_.start)[0])


def _decisions(reg: Registries, project: Project, cache: _DocCache) -> None:
    for f, doc in _docs(project, "decisions/*.txt", cache):
        for group in _blocks(doc.items):
            assert isinstance(group.value, Block)
            for d in _blocks(group.value.items):
                reg.add("decision", d.key_text, f.rel, doc.position(d.start)[0])


def _terrain(reg: Registries, project: Project, cache: _DocCache) -> None:
    for f, doc in _docs(project, "map/terrain.txt", cache):
        for item in _blocks(doc.items):
            assert isinstance(item.value, Block)
            if item.key_text.lower() == "categories":
                for t in _blocks(item.value.items):
                    reg.add("terrain", t.key_text, f.rel, doc.position(t.start)[0])


def _modifiers(reg: Registries, project: Project, cache: _DocCache) -> None:
    for pattern in (
        "common/event_modifiers.txt",
        "common/static_modifiers.txt",
        "common/triggered_modifiers.txt",
        "common/nationalvalues.txt",
        "common/crime.txt",
    ):
        _top(reg, "modifier", project, pattern, cache)


#: Effects that create a flag / variable and triggers that test it.
FLAG_SETTERS = {
    "set_country_flag": "country_flag",
    "set_global_flag": "global_flag",
    "set_province_flag": "province_flag",
}
FLAG_TESTERS = {
    "has_country_flag": "country_flag",
    "has_global_flag": "global_flag",
    "has_province_flag": "province_flag",
}


def _flags(reg: Registries, project: Project, cache: _DocCache) -> None:
    """Flags and variables are defined by being set (K28); tests are recorded as uses."""
    for pattern in (
        "events/*.txt",
        "decisions/*.txt",
        "history/*/*.txt",
        "common/*.txt",
        "history/*/*/*.txt",
    ):
        for f, doc in _docs(project, pattern, cache):
            for node in doc.walk():
                if not isinstance(node, Assignment) or node.value is None:
                    continue
                key = node.key_text.lower()
                if key in FLAG_SETTERS and not isinstance(node.value, Block):
                    reg.add(FLAG_SETTERS[key], node.value.value, f.rel, doc.position(node.start)[0])
                elif key in ("set_variable", "change_variable") and isinstance(node.value, Block):
                    which = node.value.find("which")
                    if (
                        which is not None
                        and which.value is not None
                        and not isinstance(which.value, Block)
                    ):
                        reg.add("variable", which.value.value, f.rel, doc.position(node.start)[0])
                elif key in FLAG_TESTERS and not isinstance(node.value, Block):
                    reg.tested.setdefault(FLAG_TESTERS[key], {}).setdefault(
                        node.value.value.lower(),
                        Definition(node.value.value, f.rel, doc.position(node.start)[0]),
                    )
    for registry in ("country_flag", "global_flag", "province_flag", "variable"):
        reg.names.setdefault(registry, {})


def _localisation(reg: Registries, project: Project, cache: _DocCache) -> None:
    loc = load_localisation(project)
    reg.localisation = loc
    reg.names["localisation"] = {
        k: Definition(e.key, e.file, e.line) for k, e in loc.entries.items()
    }


_Extractor = Callable[[Registries, Project, _DocCache], None]

EXTRACTORS: dict[str, _Extractor] = {
    "country": _countries,
    "culture": lambda r, p, c: _two_level(
        r, "culture_group", "culture", p, "common/cultures.txt", c
    ),
    "religion": lambda r, p, c: _two_level(
        r, "religion_group", "religion", p, "common/religion.txt", c
    ),
    "ideology": lambda r, p, c: _two_level(
        r, "ideology_group", "ideology", p, "common/ideologies.txt", c
    ),
    "goods": lambda r, p, c: _two_level(r, "goods_group", "goods", p, "common/goods.txt", c),
    "trait": lambda r, p, c: _two_level(r, "trait_type", "trait", p, "common/traits.txt", c),
    "issue": _issues,
    "government": lambda r, p, c: _top(r, "government", p, "common/governments.txt", c),
    "building": lambda r, p, c: _top(r, "building", p, "common/buildings.txt", c),
    "unit": lambda r, p, c: _top(r, "unit", p, "units/*.txt", c),
    "technology": lambda r, p, c: _top(r, "technology", p, "technologies/*.txt", c),
    "invention": lambda r, p, c: _top(r, "invention", p, "inventions/*.txt", c),
    "modifier": _modifiers,
    "national_value": lambda r, p, c: _top(r, "national_value", p, "common/nationalvalues.txt", c),
    "cb_type": lambda r, p, c: _top(
        r, "cb_type", p, "common/cb_types.txt", c, skip=frozenset({"peace_order"})
    ),
    "rebel_type": lambda r, p, c: _top(r, "rebel_type", p, "common/rebel_types.txt", c),
    "national_focus": lambda r, p, c: _two_level(
        r, "focus_group", "national_focus", p, "common/national_focus.txt", c
    ),
    "region": lambda r, p, c: _top(r, "region", p, "map/region.txt", c),
    "continent": lambda r, p, c: _top(r, "continent", p, "map/continent.txt", c),
    "pop_type": _pop_types,
    "province": _provinces,
    "event": _events,
    "decision": _decisions,
    "terrain": _terrain,
    "flags": _flags,
    "localisation": _localisation,
    "production_type": lambda r, p, c: _top(
        r, "production_type", p, "common/production_types.txt", c
    ),
}


def build_registries(project: Project, cache: _DocCache | None = None) -> Registries:
    """Extract every registry from a project.

    Args:
        project: The game + mod.
        cache: Optional ``rel -> Document`` cache shared with other passes.
    """
    reg = Registries()
    cache = {} if cache is None else cache
    for extractor in EXTRACTORS.values():
        extractor(reg, project, cache)
    return reg
