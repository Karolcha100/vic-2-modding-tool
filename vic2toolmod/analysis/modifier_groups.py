"""Groups of modifiers that differ only in one number (T008).

Victoria 2 scripts often build a curve out of many modifiers::

    modifier = { factor = 1.1  num_of_cities = 20 }
    modifier = { factor = 1.1  num_of_cities = 30 }
    modifier = { factor = 1.1  num_of_cities = 50 }

Such a *group* is a set of ``modifier`` blocks of one parent block
(``mean_time_to_happen``, ``ai_chance``, a pop weight, ``group`` …) with one
``factor`` each and the same conditions except one number - the *variable*
(``num_of_cities``), written ``key = N`` or ``NOT = { key = N }``.

Together the modifiers are a step function of the variable: every modifier
whose condition holds applies its factor. How the factors join (`combine`,
with the reason in `combine_note`, T008) follows the rules that Project Alice,
the open-source reimplementation of Victoria 2, found by studying the game
(its ``docs/rules.md`` and source); the values in vanilla agree (negative
factors only where factors add, ``factor = 0`` only where they multiply):

- **added**: ``promote_to`` in ``poptypes/*.txt``, the chances of
  ``common/pop_types.txt`` (promotion, demotion, migration, colonial migration,
  emigration, assimilation, conversion), the reform weights of
  ``common/ideologies.txt`` (``add_political_reform`` …) and the ``chance`` of
  inventions;
- **multiplied**: everything else - ``issues``, ``ideologies``,
  ``migration_target`` and ``country_migration_target`` in ``poptypes/*.txt``,
  ``mean_time_to_happen``, ``ai_chance``, ``ai_will_do``, rebels
  (``spawn_chance``, ``movement_evaluation``, ``will_rise``).

`find_groups` lists the groups of a file, `scan` of the whole mod, and
`rewrite` replaces the steps of groups by new ``(value, factor)`` pairs: the
first modifier is the pattern for the new ones (its layout, comments and other
conditions stay), the others are removed.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field

from vic2toolmod.changes import FileChange
from vic2toolmod.edit import TextEdit, apply_edits, delete, newline_of
from vic2toolmod.schema.model import Context, Schema
from vic2toolmod.script.cst import Assignment, Block, Document, Scalar
from vic2toolmod.textio import decode
from vic2toolmod.workspace import Workspace

_NUM = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)")
#: Parent blocks whose modifiers add up instead of multiplying.
_ADDITIVE_PARENTS = re.compile(r"(add|remove)_(political|social|economic|military)_reform")
_ALICE = "Project Alice rules.md (open-source reimplementation of Victoria 2)"
_POP_MULTIPLIED = ("issues", "ideologies", "migration_target", "country_migration_target")


def combine_of(rel: str, path: list[str]) -> tuple[str, str]:
    """How the factors of a block join: ``("add" | "multiply", reason)``."""
    low = rel.lower()
    keys = [p.split(" ")[0].lower() for p in path]
    if low.startswith("poptypes/"):
        if keys and keys[0] in _POP_MULTIPLIED:
            return "multiply", f"{keys[0]} weights are a product: {_ALICE}"
        return "add", f"promotion weights are a sum: {_ALICE}; vanilla uses negative factors"
    if low == "common/pop_types.txt":
        return "add", f"pop action chances are a sum: {_ALICE}; vanilla uses negative factors"
    if any(_ADDITIVE_PARENTS.fullmatch(k) for k in keys):
        return "add", f"reform weights of ideologies are a sum: {_ALICE}"
    if low.startswith("inventions/") and "chance" in keys:
        return "add", f"the invention chance is a sum (percent a month): {_ALICE}"
    return "multiply", f"factors multiply (mean_time_to_happen, ai_chance, rebels …): {_ALICE}"


_BASE_KEYS = ("factor", "base", "months", "days", "years")


@dataclass
class Step:
    """One modifier of a group.

    Attributes:
        value: The variable's number as written (``"20"``, ``"0.5"``).
        factor: The factor as written.
        line: Line of the ``modifier`` (from 1).
        start: Offset where the modifier starts.
        end: Offset where it ends.
    """

    value: str
    factor: str
    line: int
    start: int
    end: int


@dataclass
class Group:
    """Modifiers of one block that differ only in one number.

    Attributes:
        id: ``<parent offset>:<key>:<hash of the conditions>`` - stable while the file
            does not change.
        rel: File.
        line: Line of the parent block.
        path: Keys from the top of the file to the parent block, with the id of an
            event / decision when there is one (``["country_event 1234",
            "mean_time_to_happen"]``).
        key: The variable (``num_of_cities``).
        negated: Written ``NOT = { key = N }`` (the condition holds below N).
        compare: How the trigger compares (``gte``: at least N; ``lte``: at most N).
        context: The other conditions of the modifiers (the same in all of them).
        combine: ``multiply`` or ``add`` (how factors work in this block).
        combine_note: Why (the source of the rule).
        base: The parent's own value (``factor``, ``months`` …) or ``None``.
        base_key: Its key.
        steps: The modifiers in file order.
    """

    id: str
    rel: str
    line: int
    path: list[str]
    key: str
    negated: bool
    compare: str
    context: list[str]
    combine: str
    combine_note: str
    base: str | None
    base_key: str | None
    steps: list[Step] = field(default_factory=list)

    @property
    def signature(self) -> str:
        """Groups with the same signature in *different files* are copies (T014).

        The same place (the keys from the top of the file, without event ids:
        ``promote_to/soldiers``, ``emigration_chance/group``), the same variable,
        conditions and steps. Copies are only looked for between files: two
        groups in one file are two different things (e.g. migration and
        emigration of ``common/pop_types.txt``). The GUI offers copies only in
        ``poptypes/`` and ``common/`` (in events the same steps are a coincidence).
        """
        parts = [
            "/".join(p.split(" ")[0] for p in self.path),
            self.key,
            str(self.negated),
            *self.context,
            *(f"{s.value}:{s.factor}" for s in self.steps),
        ]
        return "|".join(parts).lower()


@dataclass
class _Candidate:
    node: Assignment
    var: Assignment
    var_value: Scalar
    factor: Scalar
    negated: bool
    context: list[str]


def _flat(text: str) -> str:
    return " ".join(text.split())


def _number(node: Assignment | None) -> Scalar | None:
    if node is not None and isinstance(node.value, Scalar) and _NUM.fullmatch(node.value.value):
        return node.value
    return None


def _candidates(modifier: Assignment) -> list[_Candidate]:
    """Every way of reading a modifier as ``factor`` + one numeric condition."""
    assert isinstance(modifier.value, Block)
    items = modifier.value.items
    factors = [i for i in items if isinstance(i, Assignment) and i.key_text.lower() == "factor"]
    if len(factors) != 1 or (factor := _number(factors[0])) is None:
        return []
    rest = [i for i in items if i is not factors[0]]
    out = []
    for item in rest:
        if not isinstance(item, Assignment):
            continue
        var, negated = item, False
        if item.key_text.lower() == "not" and isinstance(item.value, Block):
            inner = item.value.items
            if len(inner) != 1 or not isinstance(inner[0], Assignment):
                continue
            var, negated = inner[0], True
        value = _number(var)
        if value is None or var.key_text.lower() in _BASE_KEYS:
            continue
        context = sorted(_flat(i.to_text()) for i in rest if i is not item)
        out.append(_Candidate(modifier, var, value, factor, negated, context))
    return out


def _label(node: Assignment) -> str:
    """``country_event 1234`` for blocks with an id / name, else the key."""
    key = node.key_text
    if isinstance(node.value, Block):
        for name in ("id", "name"):
            found = node.value.find(name)
            if found is not None and isinstance(found.value, Scalar):
                return f"{key} {found.value.value}"
    return key


def _parents(doc: Document) -> list[tuple[Assignment, list[str]]]:
    out: list[tuple[Assignment, list[str]]] = []

    def walk(items: list, path: list[str]) -> None:  # type: ignore[type-arg]
        for item in items:
            if isinstance(item, Assignment) and isinstance(item.value, Block):
                here = [*path, _label(item)]
                out.append((item, here))
                walk(item.value.items, here)

    walk(doc.items, [])
    return out


def find_groups(doc: Document, rel: str, schema: Schema | None = None) -> list[Group]:
    """The modifier groups of a file (at least two modifiers with two different numbers)."""
    groups: list[Group] = []
    for parent, path in _parents(doc):
        assert isinstance(parent.value, Block)
        modifiers = [
            i
            for i in parent.value.items
            if isinstance(i, Assignment)
            and i.key_text.lower() == "modifier"
            and isinstance(i.value, Block)
        ]
        if len(modifiers) < 2:
            continue
        buckets: dict[tuple[str, bool, tuple[str, ...]], list[_Candidate]] = defaultdict(list)
        for m in modifiers:
            for c in _candidates(m):
                buckets[(c.var.key_text.lower(), c.negated, tuple(c.context))].append(c)
        # a modifier belongs to its largest group only
        used: set[int] = set()
        for (key, negated, context), members in sorted(
            buckets.items(), key=lambda kv: (-len(kv[1]), kv[1][0].node.start)
        ):
            members = [c for c in members if id(c.node) not in used]
            if len(members) < 2 or len({c.var_value.value for c in members}) < 2:
                continue
            used.update(id(c.node) for c in members)
            base_key, base = _base(parent)
            compare = "gte"
            if schema is not None:
                commands = schema.commands.get((Context.TRIGGER, key)) or []
                if commands and commands[0].compare == "lte":
                    compare = "lte"
            digest = hashlib.sha1("|".join(context).encode()).hexdigest()[:8]
            combine, note = combine_of(rel, path)
            groups.append(
                Group(
                    id=f"{parent.start}:{key}:{'n' if negated else ''}{digest}",
                    rel=rel,
                    line=doc.position(parent.start)[0],
                    path=path,
                    key=members[0].var.key_text,
                    negated=negated,
                    compare=compare,
                    context=list(context),
                    combine=combine,
                    combine_note=note,
                    base=base,
                    base_key=base_key,
                    steps=[
                        Step(
                            c.var_value.value,
                            c.factor.value,
                            doc.position(c.node.start)[0],
                            c.node.start,
                            c.node.end,
                        )
                        for c in sorted(members, key=lambda c: c.node.start)
                    ],
                )
            )
    return sorted(groups, key=lambda g: g.steps[0].start)


def _base(parent: Assignment) -> tuple[str | None, str | None]:
    assert isinstance(parent.value, Block)
    for key in _BASE_KEYS:
        value = _number(parent.value.find(key))
        if value is not None:
            return key, value.value
    return None, None


def scan(ws: Workspace, only_mod: bool = True) -> list[Group]:
    """Groups in every script file (``.txt``) of the mod (or of the game with it)."""
    out: list[Group] = []
    for f in ws.script_files(only_mod):
        if f.rel.lower().endswith(".txt"):
            out += find_groups(ws.document(f.rel), f.rel, ws.schema)
    return out


def _check_number(text: str, what: str) -> str:
    t = text.strip()
    if not _NUM.fullmatch(t):
        raise ValueError(f"{what} {text!r} is not a number")
    return t


def rewrite_edits(doc: Document, group: Group, steps: list[tuple[str, str]]) -> list[TextEdit]:
    """Text edits that give a group new steps (``(value, factor)`` in the wanted order).

    The first modifier of the group is the pattern of the new ones; an empty
    ``steps`` removes the whole group.
    """
    text = doc.text
    clean = [(_check_number(v, "value"), _check_number(f, "factor")) for v, f in steps]
    nodes = [_node_at(doc, s.start) for s in group.steps]
    edits = [delete(doc, n) for n in nodes[1:]]
    if not clean:
        return [delete(doc, nodes[0]), *edits]
    first = nodes[0]
    cand = next(
        c
        for c in _candidates(first)
        if c.var.key_text.lower() == group.key.lower() and c.negated == group.negated
    )
    pattern = text[first.start : first.end]
    places = sorted(
        [
            (cand.var_value.start - first.start, cand.var_value.end - first.start, 0),
            (cand.factor.start - first.start, cand.factor.end - first.start, 1),
        ],
        reverse=True,
    )
    line_start = max(text.rfind("\n", 0, first.start), text.rfind("\r", 0, first.start)) + 1
    indent = text[line_start : first.start]
    sep = newline_of(text) + indent if not indent.strip() else " "
    pieces = []
    for value, factor in clean:
        piece = pattern
        for a, b, which in places:
            piece = piece[:a] + (factor if which else value) + piece[b:]
        pieces.append(piece)
    edits.insert(0, TextEdit(first.start, first.end, sep.join(pieces)))
    return edits


def _node_at(doc: Document, start: int) -> Assignment:
    for node in doc.walk():
        if isinstance(node, Assignment) and node.start == start:
            return node
    raise ValueError("the file changed: reload the groups")


def rewrite(ws: Workspace, plans: list[tuple[str, str, list[tuple[str, str]]]]) -> list[FileChange]:
    """File changes for ``(rel, group id, new steps)``; several groups per file are fine.

    Raises:
        ValueError: For a group that is no longer in the file, a bad number or
            overlapping groups.
    """
    mod = ws.project.mod_dir
    if mod is None:
        raise ValueError("the game's own files are read-only: open a mod to change files")
    by_file: dict[str, list[tuple[str, list[tuple[str, str]]]]] = defaultdict(list)
    for rel, gid, steps in plans:
        by_file[rel].append((gid, steps))
    changes = []
    for rel, wanted in by_file.items():
        f = ws.file(rel)
        if f is None:
            raise ValueError(f"no file {rel!r}")
        doc = ws.document(f.rel)
        target = mod / f.rel
        if target.exists():
            disk, _ = decode(target.read_bytes())
            if ws.has_unsaved(f.rel, disk):
                raise ValueError(
                    f"{f.rel} has unsaved changes in the editor: save or revert it first"
                )
        groups = {g.id: g for g in find_groups(doc, f.rel, ws.schema)}
        edits: list[TextEdit] = []
        for gid, steps in wanted:
            if gid not in groups:
                raise ValueError(f"{rel}: the group {gid} is gone (the file changed?)")
            edits += rewrite_edits(doc, groups[gid], steps)
        new = apply_edits(doc.text, edits)
        if new != doc.text:
            old = doc.text if target.exists() else None
            changes.append(FileChange(f.rel, target, old, new, ws.encoding(f.rel)))
    return changes
