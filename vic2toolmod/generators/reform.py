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
from vic2toolmod.script.cst import Assignment, Block
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
            the first free spot of the category's grid, `free_spot`).
        in_window: Give it a box in the reform window at all (political / social).
        country_default: Option every country starts with (written into
            ``history/countries``; ``None`` = the game's default, the first option).
        country_options: Tag -> option for countries that start with another one.
    """

    category: str
    name: str
    english: str
    options: list[OptionSpec]
    next_step_only: bool = True
    administrative: bool = False
    window_position: tuple[int, int] | None = None
    in_window: bool = True
    country_default: str | None = None
    country_options: dict[str, str] = field(default_factory=dict)


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
    changes += _country_history(ws, spec, notes)
    shown = spec.category in reform_window.SHOWN and ws.file(reform_window.GUI_FILE) is not None
    if spec.in_window and shown:
        ws.set_text(rel, issues_text)  # the window sees the new issue as missing
        try:
            layout = reform_window.read_layout(ws)
            pos = spec.window_position or free_spot(layout, spec.category)
            changes.append(reform_window.plan_layout(ws, {spec.name: pos}))
            notes.append(f"box in the reform window at {pos[0]}, {pos[1]}")
            if not (0 <= pos[0] < layout.width and 0 <= pos[1] < layout.height):
                notes.append(
                    f"the box at {pos} is outside the window - move it in the reform window view"
                )
        finally:
            ws.revert(rel)
    return ReformPlan(changes, notes)


def _country_history(ws: Workspace, spec: ReformSpec, notes: list[str]) -> list[FileChange]:
    """``<reform> = <option>`` in the countries' history (T030): a default and exceptions."""
    options = {o.name for o in spec.options}
    wanted = [spec.country_default, *spec.country_options.values()]
    for o in wanted:
        if o is not None and o not in options:
            raise ValueError(f"{o!r} is not an option of the reform")
    first = spec.options[0].name
    default = spec.country_default if spec.country_default not in (None, first) else None
    exceptions = {t.upper(): o for t, o in spec.country_options.items()}
    if default is None and not exceptions:
        return []
    assert ws.project.mod_dir is not None
    changes: list[FileChange] = []
    seen: set[str] = set()
    for low, f in sorted(ws.project.files().items()):
        if not (low.startswith("history/countries/") and low.endswith(".txt")):
            continue
        tag = low[len("history/countries/") :][:3].upper()
        seen.add(tag)
        option = exceptions.get(tag, default)
        if option is None:
            continue
        doc = ws.document(f.rel)
        dated = next(
            (
                n
                for n, i in enumerate(doc.items)
                if isinstance(i, Assignment) and re.fullmatch(r"\d+\.\d+\.\d+", i.key_text)
            ),
            None,
        )
        edit = insert(doc, doc, [(spec.name, option)], dated)
        new = apply_edits(doc.text, [edit])
        old = doc.text if f.origin == "mod" else None
        changes.append(FileChange(f.rel, ws.project.mod_dir / f.rel, old, new, ws.encoding(f.rel)))
    missing = sorted(set(exceptions) - seen)
    if missing:
        notes.append(f"no history file for {', '.join(missing)}: nothing written for them")
    notes.append(
        f"history/countries: {len(changes)} countries start with a chosen option"
        + (f" (the others with {first}, the game's default)" if default is None else "")
    )
    return changes


def free_spot(layout: reform_window.Layout, category: str) -> tuple[int, int]:
    """The first cell of the category's grid that no box covers (T030).

    The grid is the one the category's boxes form (their columns and the usual
    step between rows); cells are tried column by column inside the window,
    then in new columns to the right; ``_below`` when the category has no boxes.
    """
    boxes = [b for b in layout.boxes if b.category == category and not b.outside]
    if len(boxes) < 2:
        return _below(layout, category)
    xs = sorted({b.x for b in boxes})
    ys = sorted({b.y for b in boxes})
    steps = [b - a for a, b in zip(ys, ys[1:], strict=False) if b - a > 20]
    dy = sorted(steps)[len(steps) // 2] if steps else 75
    col_steps = [b - a for a, b in zip(xs, xs[1:], strict=False) if b - a > 40]
    dx = sorted(col_steps)[len(col_steps) // 2] if col_steps else 150
    w, h = 140, max(40, dy - 10)
    taken = [(b.x, b.y, b.x + (b.w or w), b.y + (b.h or h)) for b in layout.boxes if not b.outside]

    def free(x: int, y: int) -> bool:
        return all(x + w <= a or a2 <= x or y + h <= b or b2 <= y for a, b, a2, b2 in taken)

    columns = xs + [xs[-1] + dx * (i + 1) for i in range(8)]
    for x in columns:
        y = ys[0]
        while y + h <= layout.height:
            if x + w <= layout.width and free(x, y):
                return x, y
            y += dy
    return _below(layout, category)


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


__all__ = ["OptionSpec", "ReformPlan", "ReformSpec", "free_spot", "plan_reform"]
