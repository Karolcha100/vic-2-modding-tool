"""Local HTTP server for the GUI: the engine as a JSON API.

Security (K45): the server listens on 127.0.0.1 only, and every API call
must carry the random token printed at start (header ``X-Token`` or query
``token=``), so other web pages open in the browser cannot use it. Request
bodies are JSON; nothing from the files is ever executed.

API (all under ``/api/``, JSON in and out):

==================  ======  ==================================================
``project``         GET     folders and the list of visible files
``file``            GET     ``rel`` -> text, encoding, diagnostics
``buffer``          POST    ``{rel, text}`` -> editor content; diagnostics
``revert``          POST    ``{rel}`` -> forget the editor content
``save``            POST    ``{rel, text}`` -> write into the mod (backup first)
``check``           GET     diagnostics of every mod file (``only_mod=0`` for all)
``complete``        GET     ``rel, offset`` -> completions
``hover``           GET     ``rel, offset`` -> hover text
``definition``      GET     ``rel, offset`` -> file and line
``references``      GET     ``rel, offset`` -> usages
``rename``          POST    ``{rel, offset, new_name}`` -> edits per file
``names``           GET     ``registry`` -> names defined in the project (sorted)
``changed``         GET     files changed on disk since the last call (K30)
``outline``         GET     ``rel`` -> the syntax tree for the side panel
``blocks``          GET     ``rel`` -> tree with schema information (block view, K32)
``edit``            POST    ``{rel, op, …}`` -> text edits for set / delete / insert
``parties/plan``    POST    party generator (K58): diff and summary
``parties/write``   POST    same, and write the files
``poptypes/graph``  GET     promotion graph (K59)
``events/graph``    GET     event chains (K6 C)
``vanilla/diff``    GET     mod files vs vanilla; ``rel`` -> diff of one file (K6 H)
``stats``           GET     pops at the start (K6 I)
``localisation``    POST    ``{key, english, other?, write?}`` -> plan / write a key (K35)
``reforms/window``  GET     reform window layout (K69); POST ``{positions, write?}`` -> diff
``create/reform``   POST    ``{spec, write?}`` -> new reform (K70 C): diff, notes
``create/ideology`` POST    ``{spec, write?}`` -> new ideology (K70 D): diff, notes
``create/event``    POST    ``{spec, write?}`` -> new event (K70 A)
``create/decision`` POST    ``{spec, write?}`` -> new decision (K70 B)
``localisation``    GET     ``q, limit`` -> keys whose key or English text contains ``q``
``git``             GET     the mod's git status (K37 = B); ``rel`` -> diff of one file
``picture``         GET     ``name`` -> event picture (``gfx/pictures/events``) as PNG
``trigger``         POST    ``{rel, offset, answers?}`` -> trigger facts and result (K53)
==================  ======  ==================================================

Static files of the built frontend are served from ``static/``.
"""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from vic2toolmod.changes import FileChange, diff, write_changes
from vic2toolmod.script.cst import Assignment, Block, Document, Node, Scalar
from vic2toolmod.script.diagnostics import Diagnostic
from vic2toolmod.services import LanguageService
from vic2toolmod.workspace import Workspace

STATIC = Path(__file__).parent / "static"
BUILD = Path(__file__).parent / "static_build"
"""The built frontend (``npm run build`` in ``frontend/``); not in the repository (K49)."""
_TYPES = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ttf": "font/ttf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


class ApiError(Exception):
    """A request the API refuses (status + message)."""

    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


def _diag(doc: Document, d: Diagnostic) -> dict[str, Any]:
    line, col = doc.position(d.start)
    end_line, end_col = doc.position(d.end)
    return {
        "severity": d.severity.value,
        "code": d.code,
        "message": d.message,
        "start": d.start,
        "end": d.end,
        "line": line,
        "column": col,
        "end_line": end_line,
        "end_column": end_col,
    }


class Engine:
    """The workspace and services behind the API (one lock for everything)."""

    def __init__(self, workspace: Workspace, templates_dir: Path | None = None) -> None:
        self.ws = workspace
        self.templates_dir = templates_dir
        """Own templates folder (default: next to the settings file)."""
        self.services = LanguageService(workspace)
        self.lock = threading.Lock()
        self._stamps = self._snapshot()

    # -- helpers -----------------------------------------------------------------
    def _snapshot(self) -> dict[str, tuple[int, int]]:
        out = {}
        for low, f in self.ws.project.files().items():
            try:
                st = f.path.stat()
            except OSError:
                continue
            out[low] = (st.st_size, st.st_mtime_ns)
        return out

    def _file_or_404(self, rel: str) -> str:
        if not rel or self.ws.file(rel) is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"no such file: {rel}")
        return rel

    def _report(self, rel: str) -> dict[str, Any]:
        report = self.ws.check_file(rel)
        return {
            "rel": report.file.rel,
            "file_type": report.file_type,
            "diagnostics": [_diag(report.document, d) for d in report.diagnostics],
        }

    # -- API -------------------------------------------------------------------------
    def project(self) -> dict[str, Any]:
        """Folders and visible files."""
        p = self.ws.project
        return {
            "game_dir": str(p.game_dir) if p.game_dir else None,
            "mod_dir": str(p.mod_dir) if p.mod_dir else None,
            "files": [{"rel": f.rel, "origin": f.origin} for _, f in sorted(p.files().items())],
        }

    def file(self, rel: str) -> dict[str, Any]:
        """Text, encoding and diagnostics of a file as it is on disk.

        Any editor content the server still holds for the file is dropped: the
        GUI keeps unsaved text itself, and a reloaded page must start from disk.
        """
        rel = self._file_or_404(rel)
        self.ws.revert(rel)
        doc = self.ws.document(rel)
        return {"text": doc.text, "encoding": self.ws.encoding(rel).value, **self._report(rel)}

    def buffer(self, rel: str, text: str) -> dict[str, Any]:
        """Use editor content for a file; returns its diagnostics."""
        self._file_or_404(rel)
        self.ws.set_text(rel, text)
        return self._report(rel)

    def revert(self, rel: str) -> dict[str, Any]:
        """Forget the editor content of a file."""
        self.ws.revert(self._file_or_404(rel))
        return {"ok": True}

    def save(self, rel: str, text: str) -> dict[str, Any]:
        """Write a file into the mod folder (backup of the old file first)."""
        f = self.ws.file(self._file_or_404(rel))
        assert f is not None
        if self.ws.project.mod_dir is None:
            raise ApiError(HTTPStatus.BAD_REQUEST, "no mod folder: nothing can be saved")
        target = self.ws.project.mod_dir / f.rel
        old = target.read_bytes().decode("latin-1") if target.exists() else None
        change = FileChange(f.rel, target, old, text, self.ws.encoding(rel))
        try:
            backup = write_changes([change])
        except ValueError as exc:  # EncodingError: text not writable as Windows-1252
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        self.ws.refresh()
        self._stamps = self._snapshot()
        return {"ok": True, "path": str(target), "backup": str(backup) if backup else None}

    def outline(self, rel: str) -> dict[str, Any]:
        """The syntax tree of a file: nested ``{kind, key, value, start, end, line, children}``."""
        doc = self.ws.document(self._file_or_404(rel))

        def node(n: Node) -> dict[str, Any]:
            out: dict[str, Any] = {"start": n.start, "end": n.end, "line": doc.position(n.start)[0]}
            if isinstance(n, Assignment):
                out.update(kind="assignment", key=n.key.text)
                if isinstance(n.value, Block):
                    out["children"] = [node(c) for c in n.value.items]
                elif n.value is not None:
                    out["value"] = n.value.to_text().strip()
            elif isinstance(n, Block):
                out.update(kind="block", children=[node(c) for c in n.items])
            elif isinstance(n, Scalar):
                out.update(kind="value", value=n.text)
            else:
                out.update(kind="error", value=n.to_text().strip())
            return out

        return {"items": [node(i) for i in doc.items]}

    def blocks(self, rel: str) -> dict[str, Any]:
        """The file as nested nodes with what the schema says about each (block view, K32)."""
        from vic2toolmod.services import _short

        doc, v = self.services._analyse(self._file_or_404(rel))
        loc = self.ws.registries().localisation

        def kind_of(info: Any) -> str:
            if info is None:
                return "unknown"
            if info.command is not None:
                return "scope" if info.command.push_scope else info.command.context.value
            return "dynamic" if info.context is not None else "field"

        def value_kind(spec: Any) -> tuple[str, str | None, list[str]]:
            from vic2toolmod.schema.model import OneOf, TypeSpec

            if isinstance(spec, OneOf):
                spec = next((o for o in spec.options if isinstance(o, TypeSpec)), spec.options[0])
            if not isinstance(spec, TypeSpec):
                return "block", None, []
            if spec.name == "bool":
                return "bool", None, ["yes", "no"]
            if spec.name in ("int", "float"):
                return "number", None, []
            if spec.name == "enum":
                return "enum", None, sorted(self.ws.schema.enums.get(spec.arg or "", ()))
            if spec.name == "ref":
                return "ref", spec.arg, []
            if spec.name == "localisation":
                return "loc", None, []
            if spec.name == "date":
                return "date", None, []
            return "text", None, []

        def node(n: Node) -> dict[str, Any]:
            out: dict[str, Any] = {"start": n.start, "end": n.end, "line": doc.position(n.start)[0]}
            if isinstance(n, Assignment):
                info = v.value_info.get(id(n))
                out.update(
                    kind="assignment",
                    key=n.key.text,
                    key_start=n.key.start,
                    key_end=n.key.end,
                    role=kind_of(info),
                    doc=info.doc if info else "",
                    spec=_short(info.spec) if info else "",
                )
                if isinstance(n.value, Block):
                    frame = v.block_info.get(id(n.value))
                    out.update(
                        block=True,
                        lbrace=n.value.lbrace.start,
                        rbrace=n.value.rbrace.start if n.value.rbrace else None,
                        scope=frame.scope if frame else None,
                        context=frame.context.value
                        if frame and frame.context
                        else (frame.rule.name if frame and frame.rule else None),
                        children=[node(c) for c in n.value.items],
                    )
                elif n.value is not None:
                    vk, registry, choices = value_kind(info.spec) if info else ("text", None, [])
                    out.update(
                        value=n.value.text,
                        value_start=n.value.start,
                        value_end=n.value.end,
                        value_kind=vk,
                        registry=registry,
                        choices=choices,
                    )
                    if vk == "loc" and loc is not None:
                        entry = loc.get(n.value.value)
                        out["loc_text"] = entry.text() if entry else None
            elif isinstance(n, Block):
                out.update(
                    kind="block",
                    lbrace=n.lbrace.start,
                    rbrace=n.rbrace.start if n.rbrace else None,
                    children=[node(c) for c in n.items],
                )
            elif isinstance(n, Scalar):
                out.update(kind="value", value=n.text)
            else:
                out.update(kind="error", value=n.to_text().strip())
            return out

        root = v.block_info.get(id(doc))
        return {
            "items": [node(i) for i in doc.items],
            "root_rule": root.rule.name if root and root.rule else None,
        }

    def edit(self, body: dict[str, Any]) -> dict[str, Any]:
        """Text edits for one block operation on the server's current text of a file.

        ``op``: ``set`` (``start``: node start, ``value``), ``delete`` (``start``),
        ``insert`` (``parent``: offset of the block's ``{`` or ``-1`` for the file,
        ``key``, ``value``: text or ``"{}"`` for an empty block).
        """
        from vic2toolmod import edit as ed

        rel = self._file_or_404(str(body["rel"]))
        doc = self.ws.document(rel)

        def at(start: int) -> Node:
            for n in doc.walk():
                if not isinstance(n, Document) and n.start == start:
                    return n
            raise ApiError(HTTPStatus.NOT_FOUND, f"no node at {start}")

        op = body["op"]
        if op == "set":
            n = at(int(body["start"]))
            if not isinstance(n, Assignment):
                raise ApiError(HTTPStatus.BAD_REQUEST, "not an assignment")
            edits = [ed.set_value(doc, n, str(body["value"]))]
        elif op == "delete":
            edits = [ed.delete(doc, at(int(body["start"])))]
        elif op == "insert":
            parent_offset = int(body["parent"])
            parent: Block | Document = doc
            if parent_offset >= 0:
                found = next(
                    (
                        n
                        for n in doc.walk()
                        if isinstance(n, Block) and n.lbrace.start == parent_offset
                    ),
                    None,
                )
                if found is None:
                    raise ApiError(HTTPStatus.NOT_FOUND, f"no block at {parent_offset}")
                parent = found
            key = str(body["key"])
            raw = str(body.get("value", "auto"))
            value: Any = self._default_value(rel, parent, key) if raw == "auto" else raw
            if value == "{}":
                value = []
            edits = [ed.insert(doc, parent, [(key, value)])]
        else:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"unknown op {op!r}")
        return {"edits": [asdict(e) for e in edits]}

    def _default_value(self, rel: str, parent: Block | Document, key: str) -> Any:
        """A sensible first value for a new key, from the schema (``[]`` = empty block)."""
        from vic2toolmod.schema.model import (
            BlockSpec,
            FieldsSpec,
            ListSpec,
            OneOf,
            RuleSpec,
            TypeSpec,
        )

        _, v = self.services._analyse(rel)
        frame = v.block_info.get(id(parent))
        spec: Any = None
        if frame is not None:
            fields = (
                frame.rule.fields if frame.rule else frame.fields.fields if frame.fields else {}
            )
            if key.lower() in fields:
                spec = fields[key.lower()].value
            elif frame.context is not None or (
                frame.rule and frame.rule.other in ("trigger", "effect")
            ):
                from vic2toolmod.schema.model import Context

                ctx = frame.context or Context(frame.rule.other)  # type: ignore[union-attr]
                alts = self.ws.schema.command(ctx, key)
                spec = alts[0].value if alts else None
        if isinstance(spec, OneOf):
            spec = spec.options[0]
        if spec is None or isinstance(spec, (BlockSpec, FieldsSpec, RuleSpec, ListSpec)):
            return [] if spec is not None else "x"
        assert isinstance(spec, TypeSpec)
        if spec.name == "bool":
            return "yes"
        if spec.name in ("int", "float"):
            return "0"
        if spec.name == "date":
            return "1836.1.1"
        if spec.name == "enum":
            values = sorted(self.ws.schema.enums.get(spec.arg or "", ()))
            return values[0] if values else "x"
        if spec.name == "ref":
            if spec.arg in ("country", "province"):
                return "THIS"
            names = self.ws.registries().names.get(spec.arg or "", {})
            return next(iter(sorted(d.name for d in names.values())), "x")
        if spec.name == "localisation":
            return '""'
        return "x"

    def check(self, only_mod: bool) -> dict[str, Any]:
        """Diagnostics of every file (only the mod's own files when ``only_mod``)."""
        reports = self.ws.check(only_mod=only_mod)
        return {
            "files": [
                {"rel": r.file.rel, "diagnostics": [_diag(r.document, d) for d in r.diagnostics]}
                for r in reports
                if r.diagnostics
            ]
        }

    def complete(self, rel: str, offset: int) -> dict[str, Any]:
        """Completions at an offset."""
        items = self.services.complete(self._file_or_404(rel), offset)
        return {"items": [asdict(c) for c in items[:500]], "total": len(items)}

    def hover(self, rel: str, offset: int) -> dict[str, Any]:
        """Hover text at an offset."""
        h = self.services.hover(self._file_or_404(rel), offset)
        return {"hover": asdict(h) if h else None}

    def definition(self, rel: str, offset: int) -> dict[str, Any]:
        """Definition of the name at an offset."""
        d = self.services.definition(self._file_or_404(rel), offset)
        return {"definition": asdict(d) if d else None}

    def references(self, rel: str, offset: int) -> dict[str, Any]:
        """Usages of the name at an offset."""
        return {
            "usages": [asdict(u) for u in self.services.references(self._file_or_404(rel), offset)]
        }

    def rename(self, rel: str, offset: int, new_name: str) -> dict[str, Any]:
        """Edits that rename the name at an offset everywhere."""
        edits = self.services.rename(self._file_or_404(rel), offset, new_name)
        return {"edits": {k: [asdict(e) for e in v] for k, v in edits.items()}}

    def names(self, registry: str) -> dict[str, Any]:
        """Names of a registry (``ideology``, ``issue``, ``country`` …), sorted."""
        defs = self.ws.registries().names.get(registry, {})
        return {"names": sorted(d.name for d in defs.values())}

    def changed(self) -> dict[str, Any]:
        """Files whose size / time changed (or appeared, vanished) since the last call."""
        self.ws.project._files = None
        now = self._snapshot()
        changed = sorted(
            k for k in now.keys() | self._stamps.keys() if now.get(k) != self._stamps.get(k)
        )
        if changed:
            self.ws.invalidate()
        self._stamps = now
        return {"changed": changed}

    def parties(self, body: dict[str, Any], write: bool) -> dict[str, Any]:
        """Plan (and with ``write`` write) new parties (K58)."""
        from vic2toolmod.generators.parties import CountryFilter, PartySpec, plan_parties

        spec = PartySpec(
            ideology=str(body["ideology"]),
            start_date=str(body.get("start_date", "1836.1.1")),
            end_date=str(body.get("end_date", "2000.1.1")),
            copy_from=tuple(body.get("copy_from", [])),
            policies={str(k): str(v) for k, v in body.get("policies", {}).items()},
            loc_text=body.get("loc_text"),
        )
        where = CountryFilter(
            tags={t.upper() for t in body["tags"]} if body.get("tags") else None,
            culture_groups={g.lower() for g in body["culture_groups"]}
            if body.get("culture_groups")
            else None,
            civilized=body.get("civilized"),
        )
        plan = plan_parties(self.ws, spec, where)
        result: dict[str, Any] = {
            "diff": diff(plan.changes),
            "created": plan.created,
            "skipped": plan.skipped,
        }
        if write and plan.changes:
            backup = write_changes(plan.changes)
            self.ws.refresh()
            result["backup"] = str(backup) if backup else None
        return result

    def events_graph(self) -> dict[str, Any]:
        """Event chains (K6 C)."""
        from vic2toolmod.analysis.events import event_graph

        return event_graph(self.ws)

    def vanilla(self, rel: str) -> dict[str, Any]:
        """Mod vs vanilla: list of files, or the diff of one (K6 H)."""
        from vic2toolmod.analysis.overview import compare_with_vanilla, vanilla_diff

        if rel:
            return {"diff": vanilla_diff(self.ws.project, rel)}
        return {"files": [asdict(d) for d in compare_with_vanilla(self.ws.project)]}

    def stats(self) -> dict[str, Any]:
        """Pops at the start (K6 I)."""
        from vic2toolmod.analysis.overview import pop_stats

        return asdict(pop_stats(self.ws))

    def localisation(self, body: dict[str, Any]) -> dict[str, Any]:
        """Plan (and with ``write`` write) one localisation key (K35)."""
        from vic2toolmod.project.localisation import set_entry

        change = set_entry(
            self.ws.project,
            str(body["key"]),
            str(body["english"]),
            other={str(k): str(v) for k, v in (body.get("other") or {}).items()},
        )
        result: dict[str, Any] = {"diff": diff([change])}
        if body.get("write"):
            write_changes([change])
            self.ws.refresh()
        return result

    def trigger(self, rel: str, offset: int, answers: dict[str, Any]) -> dict[str, Any]:
        """Facts of the trigger block around an offset and, with answers, the result (K53)."""
        from vic2toolmod.analysis.trigger_tester import TriggerTester
        from vic2toolmod.schema.model import Context

        doc, validator = self.services._analyse(self._file_or_404(rel))
        best: Block | None = None
        for node in doc.walk():
            if isinstance(node, Block) and node.lbrace.start < offset:
                close = node.rbrace.end if node.rbrace else len(doc.text)
                frame = validator.block_info.get(id(node))
                if offset <= close and frame is not None and frame.context is Context.TRIGGER:
                    best = node
        if best is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "no trigger block at this position")
        tester = TriggerTester(self.ws.schema, doc)
        facts = tester.facts(best)
        result = tester.evaluate(best, answers) if answers else None
        return {
            "start": best.lbrace.start,
            "facts": [asdict(f) | {"question": f.question} for f in facts],
            "result": asdict(result) if result else None,
        }

    def reform_window(self) -> dict[str, Any]:
        """Layout of the reform window and the issue categories (K69)."""
        from vic2toolmod.analysis.reform_window import issue_categories, read_layout

        return asdict(read_layout(self.ws)) | {"categories": issue_categories(self.ws)}

    def reform_window_plan(self, body: dict[str, Any]) -> dict[str, Any]:
        """Plan (and with ``write`` write) a new reform window layout."""
        from vic2toolmod.analysis.reform_window import plan_layout

        positions = {str(k): (int(v[0]), int(v[1])) for k, v in body["positions"].items()}
        change = plan_layout(self.ws, positions, add_missing=bool(body.get("add_missing", True)))
        result: dict[str, Any] = {"diff": diff([change])}
        if body.get("write"):
            backup = write_changes([change])
            self.ws.refresh()
            result["backup"] = str(backup) if backup else None
        return result

    def create(self, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        """Plan (and with ``write`` write) a new reform or ideology (K70 C, D)."""
        from vic2toolmod.generators.ideology import IdeologySpec, plan_ideology
        from vic2toolmod.generators.reform import OptionSpec, ReformSpec, plan_reform

        s = body["spec"]
        try:
            if kind == "reform":
                plan = plan_reform(
                    self.ws,
                    ReformSpec(
                        category=str(s["category"]),
                        name=str(s["name"]),
                        english=str(s["english"]),
                        options=[
                            OptionSpec(
                                str(o["name"]),
                                str(o["english"]),
                                str(o.get("description", "")),
                                {str(k): str(v) for k, v in (o.get("modifiers") or {}).items()},
                            )
                            for o in s["options"]
                        ],
                        next_step_only=bool(s.get("next_step_only", True)),
                        administrative=bool(s.get("administrative", False)),
                    ),
                )
                changes, notes = plan.changes, plan.notes
            elif kind == "event":
                from vic2toolmod.generators.event_decision import EventSpec, plan_event

                plan3 = plan_event(
                    self.ws,
                    EventSpec(
                        file=str(s["file"]),
                        title=str(s["title"]),
                        description=str(s["description"]),
                        options=[str(o) for o in s.get("options") or ["OK"]],
                        kind=str(s.get("kind", "country_event")),
                        triggered_only=bool(s.get("triggered_only", True)),
                        months=int(s.get("months", 12)),
                        picture=str(s.get("picture", "")),
                    ),
                )
                changes, notes = plan3.changes, plan3.notes
            elif kind == "decision":
                from vic2toolmod.generators.event_decision import DecisionSpec, plan_decision

                plan4 = plan_decision(
                    self.ws,
                    DecisionSpec(
                        file=str(s["file"]),
                        name=str(s["name"]),
                        title=str(s["title"]),
                        description=str(s["description"]),
                    ),
                )
                changes, notes = plan4.changes, plan4.notes
            else:
                color = s.get("color")
                plan2 = plan_ideology(
                    self.ws,
                    IdeologySpec(
                        name=str(s["name"]),
                        english=str(s["english"]),
                        template=str(s["template"]),
                        group=s.get("group") or None,
                        color=(int(color[0]), int(color[1]), int(color[2])) if color else None,
                        date=s.get("date") or None,
                    ),
                )
                changes, notes = plan2.changes, plan2.notes
        except ValueError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        result: dict[str, Any] = {
            "diff": diff(changes),
            "files": [c.rel for c in changes],
            "notes": notes,
        }
        if body.get("write"):
            backup = write_changes(changes)
            self.ws.refresh()
            result["backup"] = str(backup) if backup else None
        return result

    # -- templates (K39 = B) -------------------------------------------------------
    def templates(self) -> dict[str, Any]:
        """All templates with their fields."""
        from vic2toolmod.generators.templates import list_templates, user_dir

        return {
            "dir": str(self.templates_dir or user_dir()),
            "templates": [
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "folder": t.folder,
                    "builtin": t.builtin,
                    "body": t.body,
                    "loc": t.loc,
                    "fields": [
                        {"name": f.name, "type": f.type, "default": f.default} for f in t.fields
                    ],
                }
                for t in list_templates(self.templates_dir)
            ],
        }

    def template_values(self, tid: str, file: str) -> dict[str, Any]:
        """Starting values (free event ids for ``file``) and known names of a template."""
        from vic2toolmod.generators.templates import choices, defaults, get_template

        try:
            t = get_template(tid, self.templates_dir)
        except ValueError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, str(exc)) from exc
        return {"defaults": defaults(self.ws, t, file or None), "choices": choices(self.ws, t)}

    def template_fill(self, body: dict[str, Any]) -> dict[str, Any]:
        """Fill a template: the text, plus the file changes (written with ``write``)."""
        from vic2toolmod.generators.templates import fill, get_template

        try:
            t = get_template(str(body["id"]), self.templates_dir)
            values = {str(k): str(v) for k, v in (body.get("values") or {}).items()}
            filled = fill(self.ws, t, values, body.get("file") or None)
        except ValueError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        result: dict[str, Any] = {
            "text": filled.text,
            "diff": diff(filled.changes),
            "files": [c.rel for c in filled.changes],
            "notes": filled.notes,
        }
        if body.get("write") and filled.changes:
            backup = write_changes(filled.changes)
            self.ws.refresh()
            result["backup"] = str(backup) if backup else None
        return result

    def template_save(self, body: dict[str, Any]) -> dict[str, Any]:
        """Save one of the author's templates."""
        from vic2toolmod.generators.templates import save_template

        try:
            t = save_template(
                str(body["name"]),
                str(body["body"]),
                str(body.get("description", "")),
                str(body.get("folder", "")),
                [str(x) for x in body.get("loc") or [] if str(x).strip()],
                overwrite=bool(body.get("overwrite")),
                own=self.templates_dir,
            )
        except ValueError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        return {"id": t.id}

    def template_delete(self, tid: str) -> dict[str, Any]:
        """Delete one of the author's templates."""
        from vic2toolmod.generators.templates import delete_template

        try:
            delete_template(tid, self.templates_dir)
        except ValueError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        return {"deleted": tid}

    def localisation_search(self, q: str, limit: int) -> dict[str, Any]:
        """Localisation entries whose key or English text contains ``q`` (any case)."""
        loc = self.ws.registries().localisation
        if loc is None:
            return {"entries": [], "total": 0}
        low = q.lower()
        hits = [e for e in loc.entries.values() if low in e.key.lower() or low in e.text().lower()]
        return {
            "entries": [
                {"key": e.key, "english": e.text(), "file": e.file, "line": e.line}
                for e in hits[:limit]
            ],
            "total": len(hits),
        }

    def git(self, rel: str) -> dict[str, Any]:
        """Git status of the mod, or the diff of one file (K37 = B)."""
        from vic2toolmod import gitinfo

        mod = self.ws.project.mod_dir
        if mod is None:
            return {"repo": False}
        if rel:
            return {"diff": gitinfo.diff(mod, rel)}
        return asdict(gitinfo.status(mod))

    def picture(self, name: str) -> bytes:
        """An event picture as PNG (``gfx/pictures/events/<name>.tga``)."""
        from vic2toolmod.images import ImageError, tga_to_png

        f = self.ws.file(f"gfx/pictures/events/{name}.tga")
        if f is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"no picture {name!r}")
        try:
            return tga_to_png(f.path.read_bytes())
        except ImageError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    def poptypes_graph(self) -> dict[str, Any]:
        """Promotion graph of the pop types (K59)."""
        from vic2toolmod.analysis.poptypes import pop_weights, promotion_graph

        return promotion_graph(pop_weights(self.ws))


def make_handler(engine: Engine, token: str) -> type[BaseHTTPRequestHandler]:
    """Request handler class bound to an engine and a token."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "vic2toolmod"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - quiet
            return

        def _send(self, status: int, data: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status: int, obj: Any) -> None:
            self._send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

        def _authorised(self, query: dict[str, list[str]]) -> bool:
            given = self.headers.get("X-Token") or (query.get("token") or [""])[0]
            return secrets.compare_digest(given, token)

        def _handle(self, method: str) -> None:
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if not url.path.startswith("/api/"):
                if method == "GET":
                    return self._static(url.path)
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            if not self._authorised(query):
                return self._json(HTTPStatus.FORBIDDEN, {"error": "bad or missing token"})
            body: dict[str, Any] = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    return self._json(HTTPStatus.BAD_REQUEST, {"error": "body is not JSON"})

            def q(name: str, default: str = "") -> str:
                return (query.get(name) or [default])[0]

            route = (method, url.path[len("/api/") :])
            if route == ("GET", "picture"):
                try:
                    with engine.lock:
                        image = engine.picture(q("name"))
                except ApiError as exc:
                    return self._json(exc.status, {"error": str(exc)})
                return self._send(HTTPStatus.OK, image, "image/png")
            try:
                with engine.lock:
                    result = self._route(route, q, body)
            except ApiError as exc:
                return self._json(exc.status, {"error": str(exc)})
            except (KeyError, ValueError, TypeError) as exc:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": f"bad request: {exc}"})
            if result is None:
                return self._json(HTTPStatus.NOT_FOUND, {"error": "no such API"})
            self._json(HTTPStatus.OK, result)

        def _route(self, route: tuple[str, str], q: Any, body: dict[str, Any]) -> Any:
            e = engine
            match route:
                case ("GET", "project"):
                    return e.project()
                case ("GET", "file"):
                    return e.file(q("rel"))
                case ("POST", "buffer"):
                    return e.buffer(body["rel"], body["text"])
                case ("POST", "revert"):
                    return e.revert(body["rel"])
                case ("POST", "save"):
                    return e.save(body["rel"], body["text"])
                case ("GET", "check"):
                    return e.check(q("only_mod", "1") != "0")
                case ("GET", "complete"):
                    return e.complete(q("rel"), int(q("offset")))
                case ("GET", "hover"):
                    return e.hover(q("rel"), int(q("offset")))
                case ("GET", "definition"):
                    return e.definition(q("rel"), int(q("offset")))
                case ("GET", "references"):
                    return e.references(q("rel"), int(q("offset")))
                case ("POST", "rename"):
                    return e.rename(body["rel"], int(body["offset"]), str(body["new_name"]))
                case ("GET", "names"):
                    return e.names(q("registry"))
                case ("GET", "changed"):
                    return e.changed()
                case ("GET", "outline"):
                    return e.outline(q("rel"))
                case ("GET", "blocks"):
                    return e.blocks(q("rel"))
                case ("POST", "edit"):
                    return e.edit(body)
                case ("POST", "parties/plan"):
                    return e.parties(body, write=False)
                case ("POST", "parties/write"):
                    return e.parties(body, write=True)
                case ("GET", "poptypes/graph"):
                    return e.poptypes_graph()
                case ("GET", "reforms/window"):
                    return e.reform_window()
                case ("POST", "reforms/window"):
                    return e.reform_window_plan(body)
                case ("POST", "create/reform"):
                    return e.create("reform", body)
                case ("POST", "create/ideology"):
                    return e.create("ideology", body)
                case ("POST", "create/event"):
                    return e.create("event", body)
                case ("POST", "create/decision"):
                    return e.create("decision", body)
                case ("GET", "events/graph"):
                    return e.events_graph()
                case ("GET", "vanilla/diff"):
                    return e.vanilla(q("rel"))
                case ("GET", "stats"):
                    return e.stats()
                case ("POST", "localisation"):
                    return e.localisation(body)
                case ("GET", "localisation"):
                    return e.localisation_search(q("q"), int(q("limit", "200")))
                case ("GET", "git"):
                    return e.git(q("rel"))
                case ("GET", "templates"):
                    return e.templates()
                case ("GET", "template"):
                    return e.template_values(q("id"), q("file"))
                case ("POST", "template/fill"):
                    return e.template_fill(body)
                case ("POST", "template/save"):
                    return e.template_save(body)
                case ("POST", "template/delete"):
                    return e.template_delete(str(body["id"]))
                case ("POST", "trigger"):
                    return e.trigger(body["rel"], int(body["offset"]), body.get("answers") or {})
            return None

        def _static(self, path: str) -> None:
            root = BUILD if (BUILD / "index.html").is_file() else STATIC
            rel = path.lstrip("/") or "index.html"
            target = (root / rel).resolve()
            if not target.is_relative_to(root.resolve()) or not target.is_file():
                target = root / "index.html"
            self._send(
                HTTPStatus.OK,
                target.read_bytes(),
                _TYPES.get(target.suffix, "application/octet-stream"),
            )

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            self._handle("GET")

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            self._handle("POST")

    return Handler


def make_server(
    workspace: Workspace, port: int = 0, token: str | None = None
) -> tuple[ThreadingHTTPServer, str]:
    """Create (not start) the server on 127.0.0.1; returns it and its token."""
    token = token or secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(Engine(workspace), token))
    return server, token
