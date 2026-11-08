"""Event chains (K6 C): which event, decision or on_action fires which event.

Sources of an edge:

* ``country_event = ID`` / ``province_event = ID`` (or ``= { id = ID days = N }``)
  in an event's ``immediate`` or ``option`` blocks, in a decision's ``effect``,
  and anywhere else in effect blocks (issues, CBs, rebels, ...);
* ``common/on_actions.txt``: ``on_x = { weight = ID }``.

`event_graph` returns JSON-ready data for a graph view: nodes are events
(with title key, file, line, whether they are triggered-only) plus decisions
and on_actions that fire events; edges carry the option they come from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vic2toolmod.script.cst import Assignment, Block, Document, Node, Scalar
from vic2toolmod.workspace import Workspace

_FIRE = {"country_event", "province_event"}


@dataclass(frozen=True)
class EventCall:
    """One "fires event" link.

    Attributes:
        source: Node id of the caller: ``event:123``, ``decision:name``,
            ``on_action:on_x`` or ``file:path``.
        target: Event id that is fired.
        via: Where in the caller (option name, ``immediate``, ``effect``, weight).
        file: Relative path.
        line: 1-based line of the call.
    """

    source: str
    target: str
    via: str
    file: str
    line: int


def _scalar(block: Block, key: str) -> str | None:
    a = block.find(key)
    return a.value.value if a is not None and isinstance(a.value, Scalar) else None


def _calls_in(node: Node, doc: Document) -> list[tuple[str, int]]:
    """``(event id, line)`` of every event fired somewhere inside a node."""
    out = []
    for n in node.walk():
        if not isinstance(n, Assignment) or n.key_text.lower() not in _FIRE or n.value is None:
            continue
        if isinstance(n.value, Scalar):
            out.append((n.value.value, doc.position(n.start)[0]))
        elif isinstance(n.value, Block) and (target := _scalar(n.value, "id")):
            out.append((target, doc.position(n.start)[0]))
    return out


def event_calls(ws: Workspace) -> tuple[list[EventCall], dict[str, dict[str, Any]]]:
    """All event calls in the project and information about every event.

    Returns:
        The calls, and ``event id -> {title, file, line, kind, triggered_only}``.
    """
    calls: list[EventCall] = []
    events: dict[str, dict[str, Any]] = {}
    for f in ws.project.glob("events/*.txt"):
        doc = ws.document(f.rel)
        for ev in doc.items:
            if not (isinstance(ev, Assignment) and isinstance(ev.value, Block)):
                continue
            eid = _scalar(ev.value, "id")
            if eid is None:
                continue
            events.setdefault(
                eid,
                {
                    "title": _scalar(ev.value, "title"),
                    "file": f.rel,
                    "line": doc.position(ev.start)[0],
                    "kind": ev.key_text.lower(),
                    "triggered_only": (_scalar(ev.value, "is_triggered_only") or "").lower()
                    == "yes",
                },
            )
            for part in ev.value.items:
                if not (isinstance(part, Assignment) and isinstance(part.value, Block)):
                    continue
                key = part.key_text.lower()
                if key not in ("immediate", "option"):
                    continue
                via = (_scalar(part.value, "name") or "option") if key == "option" else "immediate"
                for target, line in _calls_in(part.value, doc):
                    calls.append(EventCall(f"event:{eid}", target, via, f.rel, line))
    for f in ws.project.glob("decisions/*.txt"):
        doc = ws.document(f.rel)
        for group in doc.items:
            if not (isinstance(group, Assignment) and isinstance(group.value, Block)):
                continue
            for d in group.value.assignments():
                if isinstance(d.value, Block):
                    effect = d.value.find("effect")
                    if effect is not None and effect.value is not None:
                        for target, line in _calls_in(effect.value, doc):
                            calls.append(
                                EventCall(f"decision:{d.key_text}", target, "effect", f.rel, line)
                            )
    on_actions = ws.project.file("common/on_actions.txt")
    if on_actions is not None:
        doc = ws.document(on_actions.rel)
        for action in doc.items:
            if isinstance(action, Assignment) and isinstance(action.value, Block):
                for w in action.value.assignments():
                    if isinstance(w.value, Scalar):
                        calls.append(
                            EventCall(
                                f"on_action:{action.key_text}",
                                w.value.value,
                                f"weight {w.key_text}",
                                on_actions.rel,
                                doc.position(w.start)[0],
                            )
                        )
    for f in ws.project.files().values():
        rel = f.rel.lower()
        if (
            not rel.startswith("common/")
            or not rel.endswith(".txt")
            or rel == "common/on_actions.txt"
        ):
            continue
        doc = ws.document(f.rel)
        for target, line in _calls_in(doc, doc):
            calls.append(EventCall(f"file:{f.rel}", target, "effect", f.rel, line))
    return calls, events


def event_graph(ws: Workspace) -> dict[str, Any]:
    """Nodes and edges for a graph view of event chains.

    Each event node has ``title`` (localised English text when available),
    ``missing`` (fired but not defined) and ``orphan`` (triggered-only but
    nothing fires it).
    """
    calls, events = event_calls(ws)
    loc = ws.registries().localisation
    fired = {c.target for c in calls}
    nodes: dict[str, dict[str, Any]] = {}
    for eid, info in events.items():
        key = info["title"]
        entry = loc.get(key) if loc and key else None
        nodes[f"event:{eid}"] = {
            "id": f"event:{eid}",
            "type": "event",
            "event_id": eid,
            "title": entry.text() if entry else key,
            "file": info["file"],
            "line": info["line"],
            "triggered_only": info["triggered_only"],
            "orphan": info["triggered_only"] and eid not in fired,
        }
    for c in calls:
        target = f"event:{c.target}"
        if target not in nodes:
            nodes[target] = {"id": target, "type": "event", "event_id": c.target, "missing": True}
        if c.source not in nodes:
            kind = c.source.split(":", 1)[0]
            nodes[c.source] = {"id": c.source, "type": kind, "file": c.file}
    edges = [
        {
            "source": c.source,
            "target": f"event:{c.target}",
            "via": c.via,
            "file": c.file,
            "line": c.line,
        }
        for c in calls
    ]
    return {"nodes": list(nodes.values()), "edges": edges}
