"""Creator of a new ideology (K70 D).

A new ideology needs more than its entry in ``common/ideologies.txt``:

* **pop support** - every ``poptypes/<pop>.txt`` has an ``ideologies`` block
  with a weight per ideology; without one, no pop ever supports it;
* **governments** - ``common/governments.txt`` lists, per government, which
  ideologies may rule (``liberal = yes``);
* **localisation** - the ideology's name.

`plan_ideology` copies all of these from an existing ideology (the template),
so the new one starts with the same behaviour and can be tuned afterwards.
Parties for the countries come from the party generator (K58).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from vic2toolmod.changes import FileChange
from vic2toolmod.edit import TextEdit, apply_edits, clone_after, insert, set_value
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
    template: str
    group: str | None = None
    color: tuple[int, int, int] | None = None
    date: str | None = None


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
    if spec.group and spec.group.lower() != group.key_text.lower():
        other = doc.find(spec.group)
        if other is None or not isinstance(other.value, Block):
            raise ValueError(f"no ideology group {spec.group!r}")
        target_group = other
    if target_group is group:
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
    changes += set_entries(ws.project, [(spec.name, spec.english, {})])
    notes.append(f"pop support copied from {spec.template} in {copied} pop types")
    notes.append("parties: use the party generator for the countries that should have one")
    return IdeologyPlan(changes, notes)


def _change(ws: Workspace, rel: str, old: str, new: str) -> FileChange:
    f = ws.file(rel)
    assert f is not None and ws.project.mod_dir is not None
    return FileChange(f.rel, ws.project.mod_dir / f.rel, old, new, ws.encoding(rel))
