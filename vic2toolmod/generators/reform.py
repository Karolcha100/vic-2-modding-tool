"""Creator of a new reform (K70 C): issue + options, localisation, reform window box.

A reform (issue) lives in ``common/issues.txt`` under its category::

    political_reforms = {
        press_rights = {
            next_step_only = yes
            censored_press = { ... modifiers ... }
            free_press = { ... }
        }
    }

The game shows the issue under the localisation key of its name, each option
under its own name, with ``<option>_desc`` as the description. For political
and social reforms the reform window needs a box named after the issue (see
`vic2toolmod.analysis.reform_window`). `plan_reform` prepares all three.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from vic2toolmod.analysis import reform_window
from vic2toolmod.changes import FileChange
from vic2toolmod.edit import apply_edits, insert
from vic2toolmod.project.localisation import set_entries
from vic2toolmod.script.cst import Block
from vic2toolmod.workspace import Workspace

_NAME = re.compile(r"[a-z][a-z0-9_]*")


@dataclass
class OptionSpec:
    """One option of the reform.

    Attributes:
        name: Key (lower case, ``a-z0-9_``).
        english: English name shown in the game.
        description: English description (``<name>_desc``), optional.
        modifiers: Modifier key -> value (``{"minimum_wage": "0.1"}``).
    """

    name: str
    english: str
    description: str = ""
    modifiers: dict[str, str] = field(default_factory=dict)


@dataclass
class ReformSpec:
    """A new reform.

    Attributes:
        category: ``political_reforms``, ``social_reforms``, ``economic_reforms``,
            ``military_reforms`` or ``party_issues``.
        name: Key of the issue.
        english: English name.
        options: Options in order (the first one is the default).
        next_step_only: Options can only be changed one step at a time.
        administrative: Counts as an administrative reform.
        window_position: Where its box goes in the reform window (``None`` =
            below the category's boxes).
    """

    category: str
    name: str
    english: str
    options: list[OptionSpec]
    next_step_only: bool = True
    administrative: bool = False
    window_position: tuple[int, int] | None = None


@dataclass
class ReformPlan:
    """Planned file changes and remarks."""

    changes: list[FileChange]
    notes: list[str]


def plan_reform(ws: Workspace, spec: ReformSpec) -> ReformPlan:
    """Plan a new reform (nothing is written).

    Raises:
        ValueError: On bad names, existing names or an unknown category.
    """
    if ws.project.mod_dir is None:
        raise ValueError("a mod folder is needed")
    regs = ws.registries()
    names = [spec.name, *(o.name for o in spec.options)]
    for n in names:
        if not _NAME.fullmatch(n):
            raise ValueError(f"bad name {n!r} (use a-z, 0-9 and _)")
        if regs.has("issue", n) or regs.has("issue_option", n):
            raise ValueError(f"{n!r} already exists")
    if len(set(names)) != len(names):
        raise ValueError("names must be different")
    if len(spec.options) < 2:
        raise ValueError("a reform needs at least two options")
    rel = "common/issues.txt"
    doc = ws.document(rel)
    category = doc.find(spec.category)
    if category is None or not isinstance(category.value, Block):
        raise ValueError(f"no category {spec.category!r} in {rel}")
    items: list[tuple[str, Any]] = []
    if spec.next_step_only:
        items.append(("next_step_only", "yes"))
    if spec.administrative:
        items.append(("administrative", "yes"))
    for o in spec.options:
        items.append((o.name, list(o.modifiers.items())))
    edit = insert(doc, category.value, [(spec.name, items)])
    issues_text = apply_edits(doc.text, [edit])
    f = ws.file(rel)
    assert f is not None
    changes = [
        FileChange(f.rel, ws.project.mod_dir / f.rel, doc.text, issues_text, ws.encoding(rel))
    ]

    loc: list[tuple[str, str, dict[str, str]]] = [(spec.name, spec.english, {})]
    for o in spec.options:
        loc.append((o.name, o.english, {}))
        if o.description:
            loc.append((f"{o.name}_desc", o.description, {}))
    changes += set_entries(ws.project, loc)

    notes: list[str] = []
    if spec.category in reform_window.SHOWN and ws.file(reform_window.GUI_FILE) is not None:
        ws.set_text(rel, issues_text)  # the window sees the new issue as missing
        try:
            layout = reform_window.read_layout(ws)
            pos = spec.window_position or _below(layout, spec.category)
            changes.append(reform_window.plan_layout(ws, {spec.name: pos}))
            if not (0 <= pos[0] < layout.width and 0 <= pos[1] < layout.height):
                notes.append(
                    f"the box at {pos} is outside the window - move it in the reform window view"
                )
        finally:
            ws.revert(rel)
    return ReformPlan(changes, notes)


def _below(layout: reform_window.Layout, category: str) -> tuple[int, int]:
    """A free spot under the lowest box of the category (or the next column)."""
    boxes = [b for b in layout.boxes if b.category == category and not b.outside]
    if not boxes:
        return 20, 60
    lowest = max(boxes, key=lambda b: b.y)
    y = lowest.y + 75
    if y + 60 <= layout.height:
        return lowest.x, y
    return max(b.x for b in boxes) + 150, min(b.y for b in boxes)


__all__ = ["OptionSpec", "ReformPlan", "ReformSpec", "plan_reform"]
