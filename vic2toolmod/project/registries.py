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


@dataclass(frozen=True, slots=True)
class Sprite:
    """A ``spriteType`` of ``interface/*.gfx``.

    Attributes:
        name: Original spelling (``GFX_crime_strip``).
        texture: Texture file as written in the ``.gfx`` file (with backslashes).
        frames: ``noOfFrames`` (1 when absent): frames side by side.
        file: Defining file.
        line: Line of the definition.
    """

    name: str
    texture: str
    frames: int
    file: str
    line: int


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
    sprites: dict[str, Sprite] = field(default_factory=dict)
    """Sprites of ``interface/*.gfx`` by lower-case name (first definition wins)."""

    def frames(self, sprite: str) -> int | None:
        """Number of frames of a sprite (``None`` if the sprite is not defined)."""
        s = self.sprites.get(sprite.lower())
        return s.frames if s else None

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


@dataclass
class Contribution:
    """Names one step of the index takes from one file (or from the file list).

    Attributes:
        adds: ``(registry, name, file, line)`` in file order.
        tested: ``(registry, name, file, line)`` of tested flags.
        registries: Registries the step creates even when empty.
    """

    adds: list[tuple[str, str, str, int]] = field(default_factory=list)
    tested: list[tuple[str, str, str, int]] = field(default_factory=list)
    registries: tuple[str, ...] = ()
    sprites: list[Sprite] = field(default_factory=list)

    def add(self, registry: str, name: str, file: str, line: int = 0) -> None:
        """Record a definition."""
        self.adds.append((registry, name, file, line))

    def names(self) -> list[tuple[str, str]]:
        """What the contribution defines, without positions (to spot real changes)."""
        return (
            [(r, n.lower()) for r, n, _, _ in self.adds]
            + [("?" + r, n.lower()) for r, n, _, _ in self.tested]
            + [("#sprite", f"{s.name.lower()}|{s.texture}|{s.frames}") for s in self.sprites]
        )


def _blocks(items: Sequence[Node]) -> Iterator[Assignment]:
    for i in items:
        if isinstance(i, Assignment) and isinstance(i.value, Block):
            yield i


_FileStep = Callable[[Contribution, ProjectFile, Document], None]


def _top(registry: str, blocks_only: bool = True, skip: frozenset[str] = frozenset()) -> _FileStep:
    """Every top-level key of a file."""

    def step(c: Contribution, f: ProjectFile, doc: Document) -> None:
        for item in doc.items:
            if not isinstance(item, Assignment):
                continue
            if blocks_only and not isinstance(item.value, Block):
                continue
            if item.key_text.lower() in skip:
                continue
            c.add(registry, item.key_text, f.rel, doc.position(item.start)[0])

    return step


def _two_level(group_registry: str | None, registry: str) -> _FileStep:
    """``group = { name = { ... } }``: groups and the block-valued names inside them."""

    def step(c: Contribution, f: ProjectFile, doc: Document) -> None:
        for group in _blocks(doc.items):
            if group_registry:
                c.add(group_registry, group.key_text, f.rel, doc.position(group.start)[0])
            assert isinstance(group.value, Block)
            for item in _blocks(group.value.items):
                c.add(registry, item.key_text, f.rel, doc.position(item.start)[0])

    return step


def _countries(c: Contribution, f: ProjectFile, doc: Document) -> None:
    for item in doc.items:
        if isinstance(item, Assignment) and item.key_text.lower() != "dynamic_tags":
            c.add("country", item.key_text, f.rel, doc.position(item.start)[0])


def _issues(c: Contribution, f: ProjectFile, doc: Document) -> None:
    for category in _blocks(doc.items):
        c.add("issue_category", category.key_text, f.rel, doc.position(category.start)[0])
        assert isinstance(category.value, Block)
        for issue in _blocks(category.value.items):
            c.add("issue", issue.key_text, f.rel, doc.position(issue.start)[0])
            assert isinstance(issue.value, Block)
            for option in _blocks(issue.value.items):
                c.add("issue_option", option.key_text, f.rel, doc.position(option.start)[0])


def _events(c: Contribution, f: ProjectFile, doc: Document) -> None:
    for ev in _blocks(doc.items):
        assert isinstance(ev.value, Block)
        id_ = ev.value.find("id")
        if id_ is not None and id_.value is not None and not isinstance(id_.value, Block):
            c.add("event", id_.value.value, f.rel, doc.position(id_.start)[0])


def _decisions(c: Contribution, f: ProjectFile, doc: Document) -> None:
    for group in _blocks(doc.items):
        assert isinstance(group.value, Block)
        for d in _blocks(group.value.items):
            c.add("decision", d.key_text, f.rel, doc.position(d.start)[0])


def _terrain(c: Contribution, f: ProjectFile, doc: Document) -> None:
    for item in _blocks(doc.items):
        assert isinstance(item.value, Block)
        if item.key_text.lower() == "categories":
            for t in _blocks(item.value.items):
                c.add("terrain", t.key_text, f.rel, doc.position(t.start)[0])


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
_FLAG_KEYS = frozenset({*FLAG_SETTERS, *FLAG_TESTERS, "set_variable", "change_variable"})
_FLAG_REGISTRIES = ("country_flag", "global_flag", "province_flag", "variable")


def _flags(c: Contribution, f: ProjectFile, doc: Document) -> None:
    """Flags and variables are defined by being set (K28); tests are recorded as uses."""
    for node in doc.walk():
        if not isinstance(node, Assignment) or node.value is None:
            continue
        key = node.key_text.lower()
        if key not in _FLAG_KEYS:
            continue
        if key in FLAG_SETTERS and not isinstance(node.value, Block):
            c.add(FLAG_SETTERS[key], node.value.value, f.rel, doc.position(node.start)[0])
        elif key in ("set_variable", "change_variable") and isinstance(node.value, Block):
            which = node.value.find("which")
            if which is not None and which.value is not None and not isinstance(which.value, Block):
                c.add("variable", which.value.value, f.rel, doc.position(node.start)[0])
        elif key in FLAG_TESTERS and not isinstance(node.value, Block):
            c.tested.append(
                (FLAG_TESTERS[key], node.value.value, f.rel, doc.position(node.start)[0])
            )


def _sprites(c: Contribution, f: ProjectFile, doc: Document) -> None:
    """Sprites: ``spriteType = { name = "GFX_x" texturefile = … noOfFrames = 9 }``.

    Any kind of sprite type counts (``spriteType``, ``textSpriteType``,
    ``corneredTileSpriteType`` …).
    """
    for node in doc.walk():
        if not (
            isinstance(node, Assignment)
            and isinstance(node.value, Block)
            and node.key_text.lower().endswith("spritetype")
        ):
            continue
        values: dict[str, str] = {}
        for a in node.value.assignments():
            if a.value is not None and not isinstance(a.value, Block):
                values[a.key_text.lower()] = a.value.value
        name = values.get("name")
        if not name:
            continue
        try:
            frames = max(1, int(values.get("noofframes", "1")))
        except ValueError:
            frames = 1
        c.sprites.append(
            Sprite(
                name,
                values.get("texturefile", ""),
                frames,
                f.rel,
                doc.position(node.start)[0],
            )
        )


_ListStep = Callable[[Project], Contribution]


def _pop_types(project: Project) -> Contribution:
    c = Contribution()
    for f in project.glob("poptypes/*.txt"):
        c.add("pop_type", PurePosixPath(f.rel).stem, f.rel, 1)
    return c


def _provinces(project: Project) -> Contribution:
    c = Contribution()
    definition = project.file("map/definition.csv")
    if definition is not None:
        text = definition.path.read_bytes().decode("latin-1")
        for n, line in enumerate(text.splitlines(), 1):
            first = line.split(";", 1)[0].strip()
            if first.isdigit() and first != "0":
                c.add("province", first, definition.rel, n)
    for f in project.glob("history/provinces/*/*.txt"):
        m = re.match(r"\s*(\d+)", PurePosixPath(f.rel).name)
        if m:
            c.add("province", m[1], f.rel, 1)
    return c


_FLAG_PATTERNS = (
    "events/*.txt",
    "decisions/*.txt",
    "history/*/*.txt",
    "common/*.txt",
    "history/*/*/*.txt",
)
_MODIFIER_FILES = (
    "common/event_modifiers.txt",
    "common/static_modifiers.txt",
    "common/triggered_modifiers.txt",
    "common/nationalvalues.txt",
    "common/crime.txt",
)


@dataclass(frozen=True)
class _Step:
    """One step of the index.

    ``each`` runs on every file matching ``pattern``; ``whole`` (with
    ``pattern`` = ``None``) runs on the file list.
    """

    pattern: str | None
    each: _FileStep | None = None
    whole: _ListStep | None = None
    creates: tuple[str, ...] = ()
    """Registries that exist even when nothing is found."""


def _s(pattern: str, each: _FileStep, creates: tuple[str, ...] = ()) -> _Step:
    return _Step(pattern, each, None, creates)


#: The index, in order (the first definition of a name wins). Localisation is
#: read last (`RegistryIndex` keeps it apart: it is not script).
STEPS: list[_Step] = [
    _s("common/countries.txt", _countries),
    _s("common/cultures.txt", _two_level("culture_group", "culture")),
    _s("common/religion.txt", _two_level("religion_group", "religion")),
    _s("common/ideologies.txt", _two_level("ideology_group", "ideology")),
    _s("common/goods.txt", _two_level("goods_group", "goods")),
    _s("common/traits.txt", _two_level("trait_type", "trait")),
    _s("common/issues.txt", _issues),
    _s("common/governments.txt", _top("government")),
    _s("common/buildings.txt", _top("building")),
    _s("units/*.txt", _top("unit")),
    _s("technologies/*.txt", _top("technology")),
    _s("inventions/*.txt", _top("invention")),
    *(_s(pattern, _top("modifier")) for pattern in _MODIFIER_FILES),
    _s("common/nationalvalues.txt", _top("national_value")),
    _s("common/cb_types.txt", _top("cb_type", skip=frozenset({"peace_order"}))),
    _s("common/rebel_types.txt", _top("rebel_type")),
    _s("common/national_focus.txt", _two_level("focus_group", "national_focus")),
    _s("map/region.txt", _top("region")),
    _s("map/continent.txt", _top("continent")),
    _Step(None, whole=_pop_types),
    _Step(None, whole=_provinces),
    _s("events/*.txt", _events),
    _s("decisions/*.txt", _decisions),
    _s("map/terrain.txt", _terrain),
    *(_s(pattern, _flags, _FLAG_REGISTRIES) for pattern in _FLAG_PATTERNS),
    _s("common/production_types.txt", _top("production_type")),
    _s("interface/*.gfx", _sprites),
]


class RegistryIndex:
    """Registries kept up to date file by file.

    Each step's contribution is remembered per file, with the document it was
    taken from. `build` takes only the changed files again and merges the
    contributions, so a change of one file costs that file, not the project.
    ``version`` grows whenever the set of defined names changes (not when only
    positions move): results that depend on names alone stay valid while it is
    the same.
    """

    def __init__(self, project: Project) -> None:
        self.project = project
        self.version = 0
        self._files: dict[tuple[int, str], tuple[Document, Contribution]] = {}
        self._lists: dict[int, Contribution] | None = None
        self._loc: Localisation | None = None
        self._registries: Registries | None = None

    def build(
        self, document: Callable[[str], Document], dirty: set[str] | None = None
    ) -> Registries:
        """Registries after changes.

        Args:
            document: Parsed document of a relative path (cached by the caller).
            dirty: Lower-case paths whose text may have changed; ``None`` = any
                file, the file list and the localisation (everything is
                compared with what the index has).
        """
        changed = self._registries is None
        if dirty is None or self._lists is None:
            lists = {
                i: step.whole(self.project)
                for i, step in enumerate(STEPS)
                if step.whole is not None
            }
            if self._lists is None or any(
                lists[i].names() != self._lists[i].names() for i in lists
            ):
                changed = True
            self._lists = lists
            loc = load_localisation(self.project)
            if self._loc is None or loc.entries.keys() != self._loc.entries.keys():
                changed = True
            self._loc = loc
        seen: set[tuple[int, str]] = set()
        for i, step in enumerate(STEPS):
            if step.pattern is None or step.each is None:
                continue
            for f in self.project.glob(step.pattern):
                low = f.rel.lower()
                key = (i, low)
                seen.add(key)
                old = self._files.get(key)
                if old is not None and dirty is not None and low not in dirty:
                    continue
                doc = document(f.rel)
                if old is not None and old[0] is doc:
                    continue
                c = Contribution(registries=step.creates)
                step.each(c, f, doc)
                if old is None or old[1].names() != c.names():
                    changed = True
                self._files[key] = (doc, c)
        if len(seen) != len(self._files):
            changed = True
            self._files = {k: v for k, v in self._files.items() if k in seen}
        if changed:
            self.version += 1
        self._registries = self._merge()
        return self._registries

    def _merge(self) -> Registries:
        reg = Registries()
        assert self._lists is not None
        by_step: dict[int, list[tuple[str, Contribution]]] = {}
        for (i, low), (_, c) in self._files.items():
            by_step.setdefault(i, []).append((low, c))
        for i, step in enumerate(STEPS):
            if step.whole is not None:
                contributions = [self._lists[i]]
            else:
                contributions = [c for _, c in sorted(by_step.get(i, []), key=lambda x: x[0])]
            for c in contributions:
                for registry in c.registries:
                    reg.names.setdefault(registry, {})
                for registry, name, file, line in c.adds:
                    reg.add(registry, name, file, line)
                for registry, name, file, line in c.tested:
                    reg.tested.setdefault(registry, {}).setdefault(
                        name.lower(), Definition(name, file, line)
                    )
                for sprite in c.sprites:
                    reg.sprites.setdefault(sprite.name.lower(), sprite)
        for registry in _FLAG_REGISTRIES:
            reg.names.setdefault(registry, {})
        loc = self._loc
        reg.localisation = loc
        if loc is not None:
            reg.names["localisation"] = {
                k: Definition(e.key, e.file, e.line) for k, e in loc.entries.items()
            }
        return reg


def build_registries(project: Project, cache: _DocCache | None = None) -> Registries:
    """Extract every registry from a project.

    Args:
        project: The game + mod.
        cache: Optional ``rel -> Document`` cache shared with other passes.
    """
    docs = {} if cache is None else cache

    def document(rel: str) -> Document:
        doc = docs.get(rel)
        if doc is None:
            f = project.file(rel)
            assert f is not None
            doc, _ = parse_file(f.path)
            docs[rel] = doc
        return doc

    return RegistryIndex(project).build(document)
