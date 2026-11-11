"""Creator of a new ideology (K70 D).

A new ideology needs more than its entry in ``common/ideologies.txt``:

* **pop support** - every ``poptypes/<pop>.txt`` has an ``ideologies`` block
  with a weight per ideology; without one, no pop ever supports it;
* **governments** - ``common/governments.txt`` lists, per government, which
  ideologies may rule (``liberal = yes``);
* **localisation** - the ideology's name.

`plan_ideology` copies all of these from an existing ideology (the template),
so the new one starts with the same behaviour and can be tuned afterwards -
or, without a template (T031), writes them from the given values: reform
preferences (``base`` of add / remove political / social reform), support in
each pop type by strata, the governments that allow it. The ideology can go
into a new group (``new_group``).
Parties for the countries come from the party generator (K58).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from vic2toolmod.changes import FileChange
from vic2toolmod.edit import Items, TextEdit, Value, apply_edits, clone_after, insert, set_value
from vic2toolmod.project.localisation import set_entries
from vic2toolmod.script.cst import Assignment, Block, Document
from vic2toolmod.workspace import Workspace

_NAME = re.compile(r"[a-z][a-z0-9_]*")


@dataclass
class IdeologySpec:
    """A new ideology.

    Attributes:
        name: Key (``christian_democrat``).
        english: English name.
        template: Existing ideology to copy (weights, reform preferences, …).
        group: Ideology group to put it in (default: the template's group).
        color: RGB colour (default: the template's).
        date: Date from which it can appear (``None`` = as the template).
    """

    name: str
    english: str
    template: str | None
    group: str | None = None
    color: tuple[int, int, int] | None = None
    date: str | None = None
    #: A new ideology group (T031): created at the end of the file; its English name.
    new_group: str | None = None
    new_group_english: str = ""
    #: Without a template (T031):
    uncivilized: bool = True
    can_reduce_militancy: bool = False
    #: ``base`` of add_political_reform, remove_political_reform, add_social_reform, …
    reform_weights: dict[str, float] = field(default_factory=dict)
    #: The same blocks as script code (``base = 1`` and ``modifier = { … }``), T031;
    #: a block given here wins over `reform_weights`.
    reform_code: dict[str, str] = field(default_factory=dict)
    #: Support in the pop types: strata (``rich`` / ``middle`` / ``poor``) -> factor.
    support: dict[str, float] = field(default_factory=dict)
    #: The support block as code (``factor = 1`` and ``modifier = { … }``) by strata.
    support_code: dict[str, str] = field(default_factory=dict)
    #: Governments that allow its parties to rule.
    governments: list[str] = field(default_factory=list)


@dataclass
class IdeologyPlan:
    """Planned file changes and remarks."""

    changes: list[FileChange]
    notes: list[str]


def _find_ideology(doc: Document, name: str) -> tuple[Assignment, Assignment] | None:
    for group in doc.items:
        if isinstance(group, Assignment) and isinstance(group.value, Block):
            for ide in group.value.items:
                if isinstance(ide, Assignment) and ide.key_text.lower() == name.lower():
                    return group, ide
    return None


def plan_ideology(ws: Workspace, spec: IdeologySpec) -> IdeologyPlan:
    """Plan a new ideology copied from a template (nothing is written).

    Raises:
        ValueError: On a bad or existing name or an unknown template / group.
    """
    if ws.project.mod_dir is None:
        raise ValueError("a mod folder is needed")
    if not _NAME.fullmatch(spec.name):
        raise ValueError(f"bad name {spec.name!r} (use a-z, 0-9 and _)")
    regs = ws.registries()
    if regs.has("ideology", spec.name):
        raise ValueError(f"ideology {spec.name!r} already exists")
    if spec.new_group is not None:
        if not _NAME.fullmatch(spec.new_group):
            raise ValueError(f"bad group name {spec.new_group!r} (use a-z, 0-9 and _)")
        if ws.document("common/ideologies.txt").find(spec.new_group) is not None:
            raise ValueError(f"group {spec.new_group!r} already exists")
    if not spec.template:
        return _from_scratch(ws, spec)
    rel = "common/ideologies.txt"
    doc = ws.document(rel)
    found = _find_ideology(doc, spec.template)
    if found is None:
        raise ValueError(f"no ideology {spec.template!r}")
    group, template = found
    assert isinstance(template.value, Block)
    notes: list[str] = []

    # 1. ideologies.txt: a copy of the template, in the chosen group.
    body = template.to_text().strip()[len(template.key.text) :]
    target_group = group
    if spec.new_group:
        target_group = None  # type: ignore[assignment]
    elif spec.group and spec.group.lower() != group.key_text.lower():
        other = doc.find(spec.group)
        if other is None or not isinstance(other.value, Block):
            raise ValueError(f"no ideology group {spec.group!r}")
        target_group = other
    if target_group is None:  # a new group at the end of the file
        nl = "\r\n" if "\r\n" in doc.text else "\n"
        sep = "" if doc.text.endswith(("\n", "\r")) else nl
        edit = TextEdit(
            len(doc.text),
            len(doc.text),
            f"{sep}{nl}{spec.new_group} = {{{nl}\t{spec.name}{body}{nl}}}{nl}",
        )
    elif target_group is group:
        edit = clone_after(doc, template, spec.name)
    else:
        assert isinstance(target_group.value, Block)
        last = [i for i in target_group.value.items if isinstance(i, Assignment)][-1]
        indent = re.match(r"[ \t]*", doc.text[doc.text.rfind("\n", 0, last.start) + 1 :])
        nl = "\r\n" if "\r\n" in doc.text else "\n"
        end = doc.text.find("\n", last.end)
        at = len(doc.text) if end < 0 else end + 1
        edit = TextEdit(at, at, f"{indent.group() if indent else ''}{spec.name}{body}{nl}")
    text = apply_edits(doc.text, [edit])
    if spec.color or spec.date:
        from vic2toolmod.script.parser import parse_text

        doc2 = parse_text(text)
        found2 = _find_ideology(doc2, spec.name)
        assert found2 is not None
        new = found2[1]
        assert isinstance(new.value, Block)
        edits = []
        for key, value in (
            ("color", [str(c) for c in spec.color] if spec.color else None),
            ("date", spec.date),
        ):
            if value is None:
                continue
            existing = new.value.find(key)
            if existing is not None:
                edits.append(set_value(doc2, existing, value))
            else:
                edits.append(insert(doc2, new.value, [(key, value)], 0))
        text = apply_edits(text, edits)
    changes = [_change(ws, rel, doc.text, text)]

    # 2. pop support: copy the template's weight in every pop type.
    copied = 0
    for f in ws.project.glob("poptypes/*.txt"):
        pdoc = ws.document(f.rel)
        block = pdoc.find("ideologies")
        if block is None or not isinstance(block.value, Block):
            continue
        weight = block.value.find(spec.template)
        if weight is None:
            notes.append(f"{f.rel}: no weight for {spec.template}, nothing copied")
            continue
        changes.append(
            _change(
                ws, f.rel, pdoc.text, apply_edits(pdoc.text, [clone_after(pdoc, weight, spec.name)])
            )
        )
        copied += 1

    # 3. governments that allow the template allow the new ideology too.
    grel = "common/governments.txt"
    if ws.file(grel) is not None:
        gdoc = ws.document(grel)
        gedits = []
        for gov in gdoc.items:
            if isinstance(gov, Assignment) and isinstance(gov.value, Block):
                allowed = gov.value.find(spec.template)
                if allowed is not None:
                    gedits.append(clone_after(gdoc, allowed, spec.name))
        if gedits:
            changes.append(_change(ws, grel, gdoc.text, apply_edits(gdoc.text, gedits)))

    # 4. localisation.
    changes += set_entries(ws.project, _names(spec))
    notes.append(f"pop support copied from {spec.template} in {copied} pop types")
    notes.append("parties: use the party generator for the countries that should have one")
    return IdeologyPlan(changes, notes)


def _names(spec: IdeologySpec) -> list[tuple[str, str, dict[str, str]]]:
    out: list[tuple[str, str, dict[str, str]]] = [(spec.name, spec.english, {})]
    if spec.new_group:
        out.append((spec.new_group, spec.new_group_english or spec.new_group, {}))
    return out


def _from_scratch(ws: Workspace, spec: IdeologySpec) -> IdeologyPlan:
    """A new ideology from the given values (T031), without copying another."""
    if spec.color is None:
        raise ValueError("a new ideology without a template needs a colour")
    rel = "common/ideologies.txt"
    doc = ws.document(rel)
    regs = ws.registries()
    for gov in spec.governments:
        if not regs.has("government", gov):
            raise ValueError(f"unknown government {gov!r}")
    items: list[tuple[str, Value]] = [("color", [str(c) for c in spec.color])]
    if spec.date:
        items.append(("date", spec.date))
    if not spec.uncivilized:
        items.append(("uncivilized", "no"))
    if spec.can_reduce_militancy:
        items.append(("can_reduce_militancy", "yes"))
    for key in (
        "add_political_reform",
        "remove_political_reform",
        "add_social_reform",
        "remove_social_reform",
    ):
        if spec.reform_code.get(key, "").strip():
            items.append((key, _code_items(spec.reform_code[key], key)))
            continue
        base: Items = [("base", _num(spec.reform_weights.get(key, 0)))]
        items.append((key, base))
    if spec.new_group:
        group_items: Items = [(spec.name, items)]
        edit = insert(doc, doc, [(spec.new_group, group_items)])
    else:
        target = doc.find(spec.group or "")
        if target is None or not isinstance(target.value, Block):
            raise ValueError(f"no ideology group {spec.group!r}: choose one or make a new one")
        edit = insert(doc, target.value, [(spec.name, items)])
    changes = [_change(ws, rel, doc.text, apply_edits(doc.text, [edit]))]
    notes: list[str] = []

    # pop support: a factor per pop type by its strata
    count = 0
    for f in ws.project.glob("poptypes/*.txt"):
        pdoc = ws.document(f.rel)
        block = pdoc.find("ideologies")
        if block is None or not isinstance(block.value, Block):
            continue
        strata = pdoc.find("strata")
        level = strata.value.to_text().strip().lower() if strata and strata.value else ""
        code = spec.support_code.get(level, spec.support_code.get("", ""))
        if code.strip():
            pop_items: Items = _code_items(code, f"support of {level or 'pops'}")
        else:
            factor = spec.support.get(level, spec.support.get("", 1.0))
            pop_items = [("factor", _num(factor))]
        pedit = insert(pdoc, block.value, [(spec.name, pop_items)])
        changes.append(_change(ws, f.rel, pdoc.text, apply_edits(pdoc.text, [pedit])))
        count += 1
    notes.append(f"pop support written in {count} pop types (factor by strata)")

    # governments that allow it
    if spec.governments:
        grel = "common/governments.txt"
        gdoc = ws.document(grel)
        wanted = {g.lower() for g in spec.governments}
        gedits: list[TextEdit] = []
        for node in gdoc.items:
            if (
                isinstance(node, Assignment)
                and isinstance(node.value, Block)
                and node.key_text.lower() in wanted
            ):
                gedits.append(insert(gdoc, node.value, [(spec.name, "yes")], 0))
        changes.append(_change(ws, grel, gdoc.text, apply_edits(gdoc.text, gedits)))
    else:
        notes.append("no government allows it yet: its parties can be in parliament but not rule")
    changes += set_entries(ws.project, _names(spec))
    notes.append("parties: use the party generator for the countries that should have one")
    return IdeologyPlan(changes, notes)


def _code_items(code: str, what: str) -> Items:
    """Script code as items for `insert` (blocks stay blocks; ``a < 5`` is not supported)."""
    from vic2toolmod.script.cst import Scalar
    from vic2toolmod.script.parser import parse_text

    doc = parse_text(code)
    if doc.has_errors:
        raise ValueError(f"{what}: the code has errors (check the braces)")

    def conv(nodes: list) -> Items:  # type: ignore[type-arg]
        out: list[tuple[str, Value]] = []
        for n in nodes:
            if isinstance(n, Assignment) and n.value is not None:
                if n.operator.text != "=":
                    raise ValueError(f"{what}: only '=' is supported here ({n.key_text})")
                if isinstance(n.value, Block):
                    out.append((n.key_text, conv(n.value.items)))
                elif isinstance(n.value, Scalar):
                    out.append((n.key_text, n.value.value))
        return out

    return conv(doc.items)


def _num(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _change(ws: Workspace, rel: str, old: str, new: str) -> FileChange:
    f = ws.file(rel)
    assert f is not None and ws.project.mod_dir is not None
    return FileChange(f.rel, ws.project.mod_dir / f.rel, old, new, ws.encoding(rel))
