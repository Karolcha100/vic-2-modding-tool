"""Creators of a new event (K70 A) and a new decision (K70 B).

Events get a free id (the file's declared range first, K29) and the usual
localisation keys of the game: ``EVTNAME<id>``, ``EVTDESC<id>`` and
``EVTOPTA<id>``, ``EVTOPTB<id>`` … for the options. Decisions go into a
``political_decisions`` block with ``<name>_title`` / ``<name>_desc`` keys.
The new content is inserted at the end of an existing file or written as a
new file. T033: a new file can claim an id range (its ``### Events N-M used``
header), the event can have a chosen id, its trigger and each option's effects
and ``ai_chance`` factor are written from the code given.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from typing import Any

from vic2toolmod.changes import FileChange
from vic2toolmod.edit import apply_edits, insert, render_items
from vic2toolmod.project.events import next_free_id, used_ids
from vic2toolmod.project.localisation import set_entries
from vic2toolmod.script.cst import Block
from vic2toolmod.script.parser import parse_text
from vic2toolmod.workspace import Workspace

_NAME = re.compile(r"[a-z][a-z0-9_]*")
_FILE = re.compile(r"[A-Za-z0-9_\- ]+\.txt")


@dataclass
class EventOption:
    """One option of a new event (T033).

    Attributes:
        name: English name.
        effects: Script code of its effects (may be empty).
        ai_factor: ``ai_chance = { factor = … }`` (empty = none).
    """

    name: str
    effects: str = ""
    ai_factor: str = ""


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
        event_id: A chosen id (``None`` = a free one).
        id_range: The ids a new file claims (``### Events N-M used`` header).
        trigger: Script code of the trigger (when not triggered only).
    """

    file: str
    title: str
    description: str
    options: list[str | EventOption] = field(default_factory=lambda: ["OK"])
    kind: str = "country_event"
    triggered_only: bool = True
    months: int = 12
    picture: str = ""
    event_id: int | None = None
    id_range: tuple[int, int] | None = None
    trigger: str = ""


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
    options = [o if isinstance(o, EventOption) else EventOption(o) for o in spec.options]
    for code, what in [(spec.trigger, "the trigger")] + [
        (o.effects, f"option {o.name!r}") for o in options
    ]:
        if code.strip() and parse_text(code).has_errors:
            raise ValueError(f"{what}: the code has errors (check the braces)")
    for o in options:
        if o.ai_factor.strip() and not re.fullmatch(r"-?\d+(\.\d+)?", o.ai_factor.strip()):
            raise ValueError(f"option {o.name!r}: ai factor {o.ai_factor!r} is not a number")
    notes: list[str] = []
    used = used_ids(ws.registries())
    header = ""
    if spec.id_range is not None:
        lo, hi = spec.id_range
        if old is not None:
            raise ValueError(
                "an id range is set only for a new file (an existing file has its header)"
            )
        if not 0 < lo <= hi:
            raise ValueError(f"bad id range {lo}-{hi}")
        clash = sorted(i for i in used if lo <= i <= hi)
        if clash:
            notes.append(f"ids {clash[0]}…{clash[-1]} of the range are already used ({len(clash)})")
        header = f"### Events {lo}-{hi} used"
    if spec.event_id is not None:
        if spec.event_id in used:
            raise ValueError(f"event id {spec.event_id} is already used")
        eid = spec.event_id
    else:
        eid = next_free_id(ws.registries(), old if old is not None else header or None)
    nl = "\r\n" if old is None or "\r\n" in old else "\n"
    lines = [
        f"{spec.kind} = {{",
        f"\tid = {eid}",
        f'\ttitle = "EVTNAME{eid}"',
        f'\tdesc = "EVTDESC{eid}"',
    ]
    if spec.picture:
        lines.append(f'\tpicture = "{spec.picture}"')
    if spec.triggered_only:
        lines.append("\tis_triggered_only = yes")
    else:
        lines += ["\ttrigger = {", *_indent(spec.trigger, 2), "\t}"]
        lines += [f"\tmean_time_to_happen = {{ months = {spec.months} }}"]
    for n, o in enumerate(options):
        lines += ["\toption = {", f'\t\tname = "EVTOPT{string.ascii_uppercase[n]}{eid}"']
        lines += _indent(o.effects, 2)
        if o.ai_factor.strip():
            lines.append(f"\t\tai_chance = {{ factor = {o.ai_factor.strip()} }}")
        lines.append("\t}")
    lines.append("}")
    block = nl.join(lines) + nl
    if old is None:
        new = (header + nl + nl if header else "") + block
    else:
        sep = "" if not old or old.endswith(("\n", "\r")) else nl
        new = old + sep + nl + block
    changes = [_write(ws, rel, old, new)]
    loc: list[tuple[str, str, dict[str, str]]] = [
        (f"EVTNAME{eid}", spec.title, {}),
        (f"EVTDESC{eid}", spec.description, {}),
    ]
    loc += [(f"EVTOPT{string.ascii_uppercase[n]}{eid}", o.name, {}) for n, o in enumerate(options)]
    changes += set_entries(ws.project, loc)
    return CreatePlan(changes, [f"event id {eid}", *notes])


def _indent(code: str, depth: int) -> list[str]:
    """Lines of script code, re-indented with tabs at ``depth`` (empty lines dropped)."""
    lines = [line.rstrip() for line in code.replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines:
        return []
    cut = min(len(line) - len(line.lstrip()) for line in lines)
    return ["\t" * depth + line[cut:].replace("    ", "\t") for line in lines]


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
