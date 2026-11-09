"""Creators of a new event (K70 A) and a new decision (K70 B).

Events get a free id (the file's declared range first, K29) and the usual
localisation keys of the game: ``EVTNAME<id>``, ``EVTDESC<id>`` and
``EVTOPTA<id>``, ``EVTOPTB<id>`` … for the options. Decisions go into a
``political_decisions`` block with ``<name>_title`` / ``<name>_desc`` keys.
The new content is inserted at the end of an existing file or written as a
new file; the trigger and effects stay empty for the author (or the block view).
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from typing import Any

from vic2toolmod.changes import FileChange
from vic2toolmod.edit import apply_edits, insert, render_items
from vic2toolmod.project.events import next_free_id
from vic2toolmod.project.localisation import set_entries
from vic2toolmod.script.cst import Block
from vic2toolmod.workspace import Workspace

_NAME = re.compile(r"[a-z][a-z0-9_]*")
_FILE = re.compile(r"[A-Za-z0-9_\- ]+\.txt")


@dataclass
class EventSpec:
    """A new event.

    Attributes:
        file: File name in ``events/`` (existing or new, e.g. ``MyEvents.txt``).
        title: English title.
        description: English description.
        options: English names of the options (at least one).
        kind: ``country_event`` or ``province_event``.
        triggered_only: Fired only by other events / decisions (no MTTH).
        months: Mean time to happen in months (when not triggered only).
        picture: Event picture name.
    """

    file: str
    title: str
    description: str
    options: list[str] = field(default_factory=lambda: ["OK"])
    kind: str = "country_event"
    triggered_only: bool = True
    months: int = 12
    picture: str = ""


@dataclass
class DecisionSpec:
    """A new decision.

    Attributes:
        file: File name in ``decisions/``.
        name: Key (``form_germany``).
        title: English title.
        description: English description.
    """

    file: str
    name: str
    title: str
    description: str


@dataclass
class CreatePlan:
    """Planned file changes and remarks."""

    changes: list[FileChange]
    notes: list[str]


def _target(ws: Workspace, folder: str, name: str) -> tuple[str, str | None]:
    if not _FILE.fullmatch(name):
        raise ValueError(f"bad file name {name!r}")
    rel = f"{folder}/{name}"
    f = ws.file(rel)
    return (f.rel if f else rel), (ws.document(f.rel).text if f else None)


def _write(ws: Workspace, rel: str, old: str | None, new: str) -> FileChange:
    assert ws.project.mod_dir is not None
    enc = ws.encoding(rel) if old is not None else None
    from vic2toolmod.textio import Encoding

    return FileChange(rel, ws.project.mod_dir / rel, old, new, enc or Encoding.CP1252)


def plan_event(ws: Workspace, spec: EventSpec) -> CreatePlan:
    """Plan a new event (nothing is written)."""
    if ws.project.mod_dir is None:
        raise ValueError("a mod folder is needed")
    if spec.kind not in ("country_event", "province_event"):
        raise ValueError("kind must be country_event or province_event")
    if not spec.options:
        raise ValueError("an event needs at least one option")
    if len(spec.options) > len(string.ascii_uppercase):
        raise ValueError("too many options")
    rel, old = _target(ws, "events", spec.file)
    eid = next_free_id(ws.registries(), old)
    items: list[tuple[str, Any]] = [
        ("id", str(eid)),
        ("title", f'"EVTNAME{eid}"'),
        ("desc", f'"EVTDESC{eid}"'),
    ]
    if spec.picture:
        items.append(("picture", f'"{spec.picture}"'))
    if spec.triggered_only:
        items.append(("is_triggered_only", "yes"))
    else:
        items.append(("trigger", []))
        items.append(("mean_time_to_happen", [("months", str(spec.months))]))
    for n, _ in enumerate(spec.options):
        items.append(("option", [("name", f'"EVTOPT{string.ascii_uppercase[n]}{eid}"')]))
    new = _append(ws, rel, old, [(spec.kind, items)])
    changes = [_write(ws, rel, old, new)]
    loc: list[tuple[str, str, dict[str, str]]] = [
        (f"EVTNAME{eid}", spec.title, {}),
        (f"EVTDESC{eid}", spec.description, {}),
    ]
    loc += [(f"EVTOPT{string.ascii_uppercase[n]}{eid}", o, {}) for n, o in enumerate(spec.options)]
    changes += set_entries(ws.project, loc)
    return CreatePlan(changes, [f"event id {eid}"])


def plan_decision(ws: Workspace, spec: DecisionSpec) -> CreatePlan:
    """Plan a new decision (nothing is written)."""
    if ws.project.mod_dir is None:
        raise ValueError("a mod folder is needed")
    if not _NAME.fullmatch(spec.name):
        raise ValueError(f"bad name {spec.name!r} (use a-z, 0-9 and _)")
    if ws.registries().has("decision", spec.name):
        raise ValueError(f"decision {spec.name!r} already exists")
    rel, old = _target(ws, "decisions", spec.file)
    body: list[tuple[str, Any]] = [
        ("potential", []),
        ("allow", []),
        ("effect", []),
        ("ai_will_do", [("factor", "1")]),
    ]
    if old is not None:
        doc = ws.document(rel)
        group = doc.find("political_decisions")
        if group is not None and isinstance(group.value, Block):
            new = apply_edits(doc.text, [insert(doc, group.value, [(spec.name, body)])])
        else:
            new = _append(ws, rel, old, [("political_decisions", [(spec.name, body)])])
    else:
        new = _append(ws, rel, None, [("political_decisions", [(spec.name, body)])])
    changes = [_write(ws, rel, old, new)]
    changes += set_entries(
        ws.project,
        [(f"{spec.name}_title", spec.title, {}), (f"{spec.name}_desc", spec.description, {})],
    )
    return CreatePlan(changes, [])


def _append(ws: Workspace, rel: str, old: str | None, items: list[tuple[str, Any]]) -> str:
    if old is None:
        return render_items(items, "\t", 0, "\r\n")
    doc = ws.document(rel)
    return apply_edits(doc.text, [insert(doc, doc, items)])
