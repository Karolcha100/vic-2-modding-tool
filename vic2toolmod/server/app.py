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
``versions``        GET     saved versions of the mod (T025): kind, list, changed files
``versions/files``  GET     ``id`` -> files a version changed; ``compare=1`` -> vs. now
``versions/save``   POST    ``{name, description?}`` -> a new version of the whole mod
``versions/restore`` POST   ``{id, name}`` -> the files as in that version (now saved first)
``picture``         GET     ``name`` -> event picture (``gfx/pictures/events``) as PNG
``image``           GET     ``rel`` -> a ``.tga`` / ``.dds`` file under ``gfx/`` as PNG (T006)
``trigger``         POST    ``{rel, offset, answers?}`` -> trigger facts and result (K53)
``trigger/world``   POST    ``{rel, offset, tag, date?, player?}`` -> answers from history (K75 B)
``trigger/countries`` POST  ``{rel, offset, date?, player?}`` -> countries that meet it
``ping``            GET     ``{stamp, stale, pid}``: is the server there, is its code current
``bye``             POST    ``client`` (query): a browser tab was closed (`lifecycle`)
``quit``            POST    stop the server; ``restart``: stop and start again (same address)
``meta``            GET     meta relations of pops (T010): rules, pop types, names to offer
``meta/plan``       POST    ``{rule?, old_name?, delete?, force?, write?}`` -> diff of all files
``modgroups/text``  POST    ``{text, block, target?}`` -> groups in a rule's modifiers
``modgroups/text-edit`` POST ``{text, id, steps}`` -> the modifiers' text with new steps
``picture/stretch`` POST    ``{sprite, width, height, border, write?}`` -> a sprite's picture at a
                            new size, frame kept (K94; border: n, [left, top, right,
                            bottom] or "auto" with ``inside``: x0, y0, x1, y1 of the
                            picture in the window, T017): preview; ``write`` into the mod
``format/text``     POST    ``{text}`` -> the text formatted (T011)
``format/plan``     POST    format the mod's files: files that change, lines, skipped
``format/diff``     GET     ``rel`` -> diff of one file of the last plan
``format/write``    POST    ``{rels}`` -> write those files of the last plan (backup)
``scripts``         GET     light Python scripts (T007): built-in and own, with fields
``modgroups``       GET     modifier groups (T008): ``rel?`` (one file) / whole mod
``modgroups/edits`` POST    ``{rel, id, steps}`` -> text edits for the editor buffer
``modgroups/plan``  POST    ``{plans: [{rel, id, steps}], write?}`` -> diff (write: backup)
``script/run``      POST    ``{id or code, values, write?}`` -> output, error, diff
``script/save``     POST    ``{name, code, overwrite?}`` -> save an own script
``script/delete``   POST    ``{id}`` -> delete an own script
==================  ======  ==================================================

Static files of the built frontend are served from ``static/``.
"""

from __future__ import annotations

import gc
import json
import os
import secrets
import sys
import threading
import time
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from vic2toolmod.changes import FileChange, diff, write_changes
from vic2toolmod.script.cst import Assignment, Block, Document, Node, Scalar
from vic2toolmod.script.diagnostics import Diagnostic
from vic2toolmod.server.lifecycle import Lifetime, code_stamp
from vic2toolmod.services import LanguageService
from vic2toolmod.workspace import Workspace

if TYPE_CHECKING:
    from vic2toolmod.analysis.modifier_groups import StepRow

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


def memory_mb() -> int | None:
    """Memory the server holds now, in MB (Linux only; elsewhere ``None``)."""
    if sys.platform != "linux":
        return None
    try:
        with open("/proc/self/statm") as f:
            pages = int(f.read().split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return pages * os.sysconf("SC_PAGE_SIZE") // 2**20


def _steps(body: dict[str, Any]) -> list[StepRow]:
    """``steps: [[value, factor(, negated)], ...]`` of a request (negated: ``NOT = {}``, T023)."""
    out: list[StepRow] = []
    for row in body.get("steps") or []:
        out.append(
            (str(row[0]), str(row[1]), bool(row[2])) if len(row) > 2 else (str(row[0]), str(row[1]))
        )
    return out


class Engine:
    """The workspace and services behind the API (one lock for everything)."""

    def __init__(
        self,
        workspace: Workspace,
        templates_dir: Path | None = None,
        scripts_dir: Path | None = None,
    ) -> None:
        self.ws = workspace
        self.templates_dir = templates_dir
        """Own templates folder (default: next to the settings file)."""
        self.scripts_dir = scripts_dir
        """Own scripts folder (default: next to the settings file)."""
        self.services = LanguageService(workspace)
        self.lifetime: Lifetime | None = None
        """When to stop the server (``None``: never on its own)."""
        self.stamp = code_stamp()
        """Fingerprint of the tool's code when the server started."""
        self._stale: tuple[float, bool] = (0.0, False)
        self._format_plan: Any = None  # format.ModPlan of the last "format the whole mod"
        self._groups: dict[str, Any] = {}  # modifier_groups.GroupCache
        self._worlds: dict[str, Any] = {}  # the world at a date (K75 B), see _world
        self._vanilla: tuple[dict[str, tuple[int, int]], list[dict[str, Any]]] | None = None
        self.lock = threading.Lock()
        self._sprites: dict[tuple[str, int, int, int, int], bytes] = {}
        self._stamps = self._snapshot()

    # -- helpers -----------------------------------------------------------------
    def _snapshot(self) -> dict[str, tuple[int, int]]:
        return self.ws.project.mod_files_on_disk()

    def _write(self, changes: list[FileChange]) -> Path | None:
        """Write changes into the mod folder (refused when only the game is open)."""
        if self.ws.project.mod_dir is None:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "the game's own files are read-only: open a mod to change files",
            )
        return write_changes(changes)

    # -- projects (K81 = A) ----------------------------------------------------------
    def projects(self) -> dict[str, Any]:
        """Mods that can be opened: the game's ``mod/*.mod``, the settings, recent ones."""
        from vic2toolmod.config import load_settings
        from vic2toolmod.project.layout import read_mod_file

        game = self.ws.project.game_dir
        current = self.ws.project.mod_dir
        here = current.resolve() if current else None
        found: dict[str, dict[str, Any]] = {}

        def add(path: Path, name: str, source: str) -> None:
            if path.is_dir():
                real = path.resolve()
                # the open mod keeps its own path (the game's mod/ folder often links to it)
                shown = current if real == here and current is not None else path
                found.setdefault(str(real), {"path": str(shown), "name": name, "source": source})

        if game is not None:
            for mod_file in sorted((game / "mod").glob("*.mod")):
                try:
                    m = read_mod_file(mod_file)
                except (OSError, ValueError):
                    continue
                folder = m.path.replace("\\", "/").strip("/") or f"mod/{mod_file.stem}"
                add(game / folder, m.name or mod_file.stem, "game")
        for d in load_settings().mod_dirs:
            add(d, d.name, "settings")
        for recent in _recent():
            add(Path(recent), Path(recent).name, "recent")
        return {
            "current": str(current) if current else None,
            "game_dir": str(game) if game else None,
            "recent": _recent(),
            "mods": list(found.values()),
        }

    def open_project(self, mod: str | None) -> dict[str, Any]:
        """Open another mod (``None``: the game alone, read-only) instead of this one."""
        mod_dir = Path(mod).expanduser() if mod else None
        if mod_dir is not None and not mod_dir.is_dir():
            raise ApiError(HTTPStatus.NOT_FOUND, f"no such folder: {mod}")
        ws = Workspace.open(self.ws.project.game_dir, mod_dir)
        self.ws = ws
        self.services = LanguageService(ws)
        self._stamps = self._snapshot()
        self._sprites.clear()
        self._groups.clear()
        self._vanilla = None
        if mod_dir is not None:
            _remember(mod_dir)
        threading.Thread(target=self.warm_up, name="warm-up", daemon=True).start()
        return {"mod_dir": str(mod_dir) if mod_dir else None}

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

    def warm_up(self) -> None:
        """Build the index and check the mod's files, one file per lock.

        Then freeze what is loaded for the garbage collector: the parsed
        project is millions of objects that live as long as the server, and
        full collections over them made typing stutter (0.5 s pauses).
        """
        with self.lock:
            ws = self.ws
            files = [f.rel for f in ws.script_files(only_mod=True)]
        for rel in files:
            with self.lock:
                if self.ws is not ws:
                    return  # another project was opened meanwhile
                try:
                    ws.check_file(rel)
                except KeyError:
                    continue  # the file vanished
        gc.collect()
        gc.freeze()

    # -- API -------------------------------------------------------------------------
    def project(self) -> dict[str, Any]:
        """Folders and visible files."""
        p = self.ws.project
        return {
            "game_dir": str(p.game_dir) if p.game_dir else None,
            "mod_dir": str(p.mod_dir) if p.mod_dir else None,
            "read_only": p.mod_dir is None,
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
            self._write([])  # refused: only the game is open
        assert self.ws.project.mod_dir is not None
        target = self.ws.project.mod_dir / f.rel
        old = target.read_bytes().decode("latin-1") if target.exists() else None
        change = FileChange(f.rel, target, old, text, self.ws.encoding(rel))
        try:
            backup = self._write([change])
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
                    icon = self.services._icon(v, n)
                    if icon is not None:
                        out["sprite"] = list(icon)
                    picture = self.services._picture(v, n)
                    if picture is not None:
                        out["picture"] = picture
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
        """Mod files whose size / time changed (or appeared, vanished) since the last call.

        Only the mod folder is read; the work is done without the engine lock,
        so the editor does not wait for it.
        """
        now = self._snapshot()
        with self.lock:
            old, self._stamps = self._stamps, now
            changed = sorted(k for k in now.keys() | old.keys() if now.get(k) != old.get(k))
            if changed:
                if now.keys() != old.keys():
                    self.ws.project._files = None  # files appeared / vanished
                self.ws.invalidate()
        return {"changed": changed, "stale": self.stale(), "memory_mb": memory_mb()}

    def stale(self) -> bool:
        """The tool's code on disk is no longer what this server runs (looked at every 5 s)."""
        at, value = self._stale
        now = time.monotonic()
        if not value and now - at > 5:
            value = code_stamp() != self.stamp
            self._stale = (now, value)
        return value

    def ping(self) -> dict[str, Any]:
        """Who answers here: the code's fingerprint, whether it is out of date, the process."""
        mod = self.ws.project.mod_dir
        return {
            "stamp": self.stamp,
            "stale": self.stale(),
            "pid": os.getpid(),
            "memory_mb": memory_mb(),
            "mod_dir": str(mod) if mod else None,
        }

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
            backup = self._write(plan.changes)
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
        # Comparing every mod file takes seconds: done again only when a mod file changed.
        now = self._snapshot()
        if self._vanilla is None or self._vanilla[0] != now:
            files = [asdict(d) for d in compare_with_vanilla(self.ws.project)]
            self._vanilla = (now, files)
        return {"files": self._vanilla[1]}

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
            self._write([change])
            self.ws.refresh()
        return result

    def _trigger_block(self, rel: str, offset: int) -> tuple[Document, Block]:
        """The innermost trigger block around an offset of a file."""
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
        return doc, best

    def _world(self, date: str) -> Any:
        """The world at a date from the history files (K75 B), read again when they change."""
        from vic2toolmod.analysis.world import World

        stamp = 0
        for low, f in self.ws.project.files().items():
            if low.startswith(("history/", "map/continent", "map/region", "common/countries")):
                try:
                    st = f.path.stat()
                except OSError:
                    continue
                stamp = hash((stamp, low, st.st_mtime_ns, st.st_size))
        key = (date, stamp, self.ws.names_version)
        if self._worlds.get("key") != key:
            try:
                self._worlds = {"key": key, "world": World.read(self.ws, date)}
            except ValueError as exc:
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        return self._worlds["world"]

    def trigger_world(self, body: dict[str, Any]) -> dict[str, Any]:
        """Answers from the history for a country at a date, and the result (K75 B)."""
        from vic2toolmod.analysis.trigger_tester import TriggerTester
        from vic2toolmod.analysis.world import Scope

        doc, block = self._trigger_block(str(body["rel"]), int(body["offset"]))
        world = self._world(str(body.get("date") or "1836.1.1"))
        world.player = str(body.get("player") or "").upper()
        tag = str(body["tag"]).upper()
        if tag not in world.countries:
            raise ApiError(HTTPStatus.NOT_FOUND, f"no history for the country {tag}")
        tester = TriggerTester(self.ws.schema, doc)
        answers = world.answers(tester, block, tag)
        verdict = world.check(block, Scope("country", tag, tag, 0))
        result = tester.evaluate(block, answers)
        return {
            "answers": answers,
            "result": asdict(result),
            "value": verdict.value,
            "reasons": verdict.reasons[:20],
        }

    def trigger_countries(self, body: dict[str, Any]) -> dict[str, Any]:
        """Which countries (existing at the date) meet a trigger block, from the history."""
        from vic2toolmod.analysis.world import Scope

        _, block = self._trigger_block(str(body["rel"]), int(body["offset"]))
        world = self._world(str(body.get("date") or "1836.1.1"))
        world.player = str(body.get("player") or "").upper()
        true: list[str] = []
        unknown: list[dict[str, Any]] = []
        false = 0
        for tag in sorted(world.countries):
            if not world.owned(tag):
                continue
            v = world.check(block, Scope("country", tag, tag, 0))
            if v.value is True:
                true.append(tag)
            elif v.value is None:
                unknown.append({"tag": tag, "reasons": v.reasons[:3]})
            else:
                false += 1
        return {"true": true, "unknown": unknown, "false": false}

    def trigger(self, rel: str, offset: int, answers: dict[str, Any]) -> dict[str, Any]:
        """Facts of the trigger block around an offset and, with answers, the result (K53)."""
        from vic2toolmod.analysis.trigger_tester import TriggerTester

        doc, best = self._trigger_block(rel, offset)
        tester = TriggerTester(self.ws.schema, doc)
        facts = tester.facts(best)
        result = tester.evaluate(best, answers) if answers else None
        return {
            "start": best.lbrace.start,
            "facts": [asdict(f) | {"question": f.question} for f in facts],
            "result": asdict(result) if result else None,
        }

    def reform_window(self) -> dict[str, Any]:
        """Layout of the reform window and what the GUI needs to draw it (K69, K80 A).

        Besides the issue boxes: the window as an element tree, the template of
        one reform option row (``reform_option_window``), each issue's options,
        the texts of localisation keys and the sizes of the sprites used.
        """
        from vic2toolmod.analysis import gui_tree
        from vic2toolmod.analysis.reform_window import (
            GUI_FILE,
            WINDOW,
            issue_categories,
            issue_options,
            read_layout,
        )

        out = asdict(read_layout(self.ws)) | {"categories": issue_categories(self.ws)}
        tree = gui_tree.read_window(self.ws, GUI_FILE, WINDOW)
        behind = gui_tree.backdrop(self.ws, GUI_FILE, WINDOW)
        try:
            row = gui_tree.read_window(self.ws, GUI_FILE, "reform_option_window")
        except ValueError:
            row = None
        options = issue_options(self.ws)
        loc = self.ws.registries().localisation

        def text(key: str) -> str | None:
            e = loc.get(key) if loc is not None and key else None
            return e.text() if e else None

        drawn = self._gui_payload([tree, *behind, *([row] if row else [])])
        sprites = drawn["sprites"]
        # only the big pictures behind the window (its background), not the
        # charts and overlays of the panel around it
        big = [
            e
            for e in behind
            if "unciv" not in e.name.lower()  # the overlay of uncivilised countries
            and max(sprites.get(e.sprite, {}).get("w", 0), sprites.get(e.sprite, {}).get("h", 0))
            >= 300
        ]
        return out | {
            "tree": asdict(tree),
            "backdrop": [asdict(e) for e in big],
            "option_row": asdict(row) if row else None,
            "issues": {
                i: {
                    "text": text(i) or i,
                    "options": [{"key": o, "text": text(o) or o} for o in options.get(i, [])],
                }
                for issues in out["categories"].values()
                for i in issues
            },
            "texts": drawn["texts"],
            "sprites": sprites,
        }

    def _gui_payload(self, roots: list[Any]) -> dict[str, Any]:
        """Texts of the localisation keys and sizes of the sprites used by element trees."""
        from vic2toolmod.analysis import gui_tree

        regs = self.ws.registries()
        loc = regs.localisation
        keys: set[str] = set()
        used: set[str] = set()

        def collect(e: gui_tree.Element) -> None:
            if e.text:
                keys.add(e.text)
            if e.sprite:
                used.add(e.sprite)
            for c in e.children:
                collect(c)

        for r in roots:
            collect(r)
        texts = {}
        for k in sorted(keys):
            entry = loc.get(k) if loc is not None else None
            if entry is not None:
                texts[k] = entry.text()
        sprites: dict[str, Any] = {}
        for name in sorted(used):
            s = regs.sprites.get(name.lower())
            rel = self.texture(s.texture) if s else None
            f = self.ws.file(rel) if rel else None
            size = gui_tree.texture_size(f.path) if f else None
            sprites[name] = {
                "frames": s.frames if s else 0,
                "w": size[0] // max(1, s.frames) if size and s else 0,
                "h": size[1] if size else 0,
                "found": f is not None,
            }
        return {"texts": texts, "sprites": sprites}

    # -- any window of interface/*.gui (K80 B) ------------------------------------------
    def gui_windows(self, rel: str) -> dict[str, Any]:
        """Every window of a ``.gui`` file: name, line, nesting depth."""
        from vic2toolmod.analysis import gui_tree

        try:
            found = gui_tree.windows(self.ws, self._file_or_404(rel))
        except ValueError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, str(exc)) from exc
        return {"windows": [{"name": n, "line": ln, "depth": d} for n, ln, d in found]}

    def gui_window(self, rel: str, name: str) -> dict[str, Any]:
        """One window as an element tree with the pictures behind it, texts and sprites."""
        from vic2toolmod.analysis import gui_tree

        try:
            tree = gui_tree.read_window(self.ws, self._file_or_404(rel), name)
        except ValueError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, str(exc)) from exc
        behind = gui_tree.backdrop(self.ws, rel, name)
        return {"file": rel, "tree": asdict(tree), "backdrop": [asdict(e) for e in behind]} | (
            self._gui_payload([tree, *behind])
        )

    def gui_plan(self, body: dict[str, Any]) -> dict[str, Any]:
        """Plan (and with ``write`` write) new positions / sizes of window elements."""
        from vic2toolmod.analysis import gui_tree

        rel = self._file_or_404(str(body["rel"]))
        changes = {
            int(line): {k: int(v) for k, v in c.items() if k in ("x", "y", "w", "h")}
            for line, c in body["changes"].items()
        }
        try:
            change = gui_tree.plan_changes(self.ws, rel, changes)
        except ValueError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        result: dict[str, Any] = {"diff": diff([change])}
        if body.get("write"):
            backup = self._write([change])
            self.ws.refresh()
            self._stamps = self._snapshot()
            result["backup"] = str(backup) if backup else None
        return result

    def reform_window_plan(self, body: dict[str, Any]) -> dict[str, Any]:
        """Plan (and with ``write`` write) a new reform window layout."""
        from vic2toolmod.analysis.reform_window import plan_layout

        positions = {str(k): (int(v[0]), int(v[1])) for k, v in body["positions"].items()}
        change = plan_layout(self.ws, positions, add_missing=bool(body.get("add_missing", True)))
        result: dict[str, Any] = {"diff": diff([change])}
        if body.get("write"):
            backup = self._write([change])
            self.ws.refresh()
            result["backup"] = str(backup) if backup else None
        return result

    def create(self, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        """Plan (and with ``write`` write) a new reform or ideology (K70 C, D)."""
        from vic2toolmod.generators.ideology import IdeologySpec, plan_ideology
        from vic2toolmod.generators.reform import OptionSpec, ReformSpec, plan_reform

        s = body["spec"]
        copies: list[tuple[Path, Path]] = []
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
            elif kind == "country":
                from vic2toolmod.generators.country import CountrySpec, plan_country

                def opt(key: str) -> str | None:
                    v = s.get(key)
                    return str(v).strip() if v not in (None, "") else None

                cultures = s.get("cultures")
                civilized = s.get("civilized")
                plan5 = plan_country(
                    self.ws,
                    CountrySpec(
                        tag=str(s["tag"]),
                        name=str(s["name"]),
                        adjective=str(s.get("adjective", "")),
                        template=str(s["template"]),
                        color=(int(s["color"][0]), int(s["color"][1]), int(s["color"][2])),
                        capital=int(s["capital"]) if opt("capital") else None,
                        primary_culture=opt("primary_culture"),
                        cultures=None if cultures is None else [str(c) for c in cultures],
                        religion=opt("religion"),
                        government=opt("government"),
                        civilized=None if civilized in (None, "") else bool(civilized),
                        copy_flags=bool(s.get("copy_flags", True)),
                        provinces=[int(p) for p in s.get("provinces") or []],
                        exists=bool(s.get("exists", False)),
                    ),
                )
                changes, notes, copies = plan5.changes, plan5.notes, plan5.copies
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
        mod = self.ws.project.mod_dir
        result: dict[str, Any] = {
            "diff": diff(changes),
            "files": [c.rel for c in changes]
            + [dest.relative_to(mod).as_posix() for _, dest in copies if mod is not None],
            "notes": notes,
        }
        if body.get("write"):
            backup = self._write(changes)
            if copies:
                from vic2toolmod.generators.country import write_copies

                write_copies(copies)
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
            backup = self._write(filled.changes)
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

    # -- modifier groups (T008) ------------------------------------------------------
    def modgroups(self, rel: str) -> dict[str, Any]:
        """Modifier groups of one file (``rel``) or of every mod file."""
        from vic2toolmod.analysis.modifier_groups import find_groups, scan

        if rel:
            name = self._file_or_404(rel)
            groups = find_groups(self.ws.document(name), name, self.ws.schema)
        else:
            groups = scan(self.ws, cache=self._groups)
        return {"groups": [{**asdict(g), "signature": g.signature} for g in groups]}

    def modgroup_edits(self, body: dict[str, Any]) -> dict[str, Any]:
        """Text edits giving a group of the open buffer new steps (applied by the editor)."""
        from vic2toolmod.analysis.modifier_groups import find_groups, rewrite_edits

        rel = self._file_or_404(str(body["rel"]))
        doc = self.ws.document(rel)
        group = next((g for g in find_groups(doc, rel, self.ws.schema) if g.id == body["id"]), None)
        if group is None:
            raise ApiError(HTTPStatus.CONFLICT, "the group is gone (the text changed?)")
        try:
            edits = rewrite_edits(doc, group, _steps(body))
        except ValueError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        return {"edits": [{"start": e.start, "end": e.end, "text": e.new_text} for e in edits]}

    def modgroup_plan(self, body: dict[str, Any]) -> dict[str, Any]:
        """New steps for groups in any files: the diff, and with ``write`` the files written."""
        from vic2toolmod.analysis.modifier_groups import rewrite

        try:
            plans = [(str(p["rel"]), str(p["id"]), _steps(p)) for p in body.get("plans") or []]
            changes = rewrite(self.ws, plans)
        except ValueError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        out: dict[str, Any] = {"diff": diff(changes), "files": [c.rel for c in changes]}
        if body.get("write") and changes:
            try:
                backup = self._write(changes)
            except ValueError as exc:
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
            for c in changes:
                self.ws.revert(c.rel)
            self.ws.refresh()
            out["backup"] = str(backup) if backup else None
            out["written"] = True
        return out

    # -- meta relations (T010) -----------------------------------------------------------
    def meta(self) -> dict[str, Any]:
        """Rules with the pop types they go into, pop types by strata, names to offer."""
        from vic2toolmod.generators import meta

        pops = meta.pop_types(self.ws)
        names = self.ws.registries().names
        return {
            "rules": [{**asdict(r), "pops": meta.matches(r, pops)} for r in meta.rules(self.ws)],
            "pops": pops,
            "blocks": {"pop": list(meta.POP_BLOCKS), "chance": list(meta.CHANCE_BLOCKS)},
            "names": {
                k: sorted(names.get(k, {})) for k in ("pop_type", "issue_option", "ideology")
            },
            "folder": meta.META_DIR,
        }

    def meta_plan(self, body: dict[str, Any]) -> dict[str, Any]:
        """Save / delete one rule and bring every file in line; ``write`` makes it so."""
        from vic2toolmod.generators import meta

        mod = self.ws.project.mod_dir
        if mod is None:
            raise ApiError(HTTPStatus.CONFLICT, "open a mod to keep meta relations in it")
        try:
            current = {r.name: r for r in meta.rules(self.ws)}
            changes: list[FileChange] = []
            gone: list[Path] = []
            old_name = str(body.get("old_name") or "")
            if body.get("delete"):
                name = str(body.get("name") or old_name)
                current.pop(name, None)
                gone.append(mod / meta.META_DIR / f"{name}.txt")
            elif body.get("rule"):
                raw = body["rule"]
                rule = meta.Rule(
                    name=str(raw.get("name", "")).strip(),
                    block=str(raw.get("block", "")),
                    target=str(raw.get("target", "")).strip(),
                    description=str(raw.get("description", "")).strip(),
                    strata=[str(s) for s in raw.get("strata") or []],
                    pop_types=[str(p) for p in raw.get("pop_types") or []],
                    group=bool(raw.get("group")),
                    modifiers=str(raw.get("modifiers", "")),
                )
                rule.check()
                if old_name and old_name != rule.name:
                    current.pop(old_name, None)
                    gone.append(mod / meta.META_DIR / f"{old_name}.txt")
                elif not old_name and rule.name in current:
                    raise meta.MetaError(f"a rule named {rule.name!r} already exists")
                current[rule.name] = rule
                changes.append(meta.save_rule(self.ws, rule))
            result = meta.plan(self.ws, list(current.values()), force=bool(body.get("force")))
        except meta.MetaError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        changes += result.changes
        out: dict[str, Any] = {
            "diff": diff(changes) + "".join(f"(deleted) {p.name}\n" for p in gone if p.exists()),
            "files": [c.rel for c in changes],
            "added": result.added,
            "updated": result.updated,
            "removed": result.removed,
            "edited": result.edited,
            "missing": result.missing,
        }
        if body.get("write"):
            backup = self._write(changes) if changes else None
            for path in gone:
                if path.exists():
                    if backup is not None:
                        (backup / meta.META_DIR).mkdir(parents=True, exist_ok=True)
                        (backup / meta.META_DIR / path.name).write_bytes(path.read_bytes())
                    path.unlink()
            for c in changes:
                self.ws.revert(c.rel)
            self.ws.refresh()
            out["written"] = True
            out["backup"] = str(backup) if backup else None
        return out

    def modgroups_text(self, body: dict[str, Any], steps: list[StepRow] | None) -> Any:
        """Groups in a piece of code (a rule's modifiers); with ``steps`` the code rewritten."""
        from vic2toolmod.analysis.modifier_groups import combine_of, find_groups, rewrite_edits
        from vic2toolmod.edit import apply_edits
        from vic2toolmod.script.parser import parse_text

        head = "rule = {\n"
        text = head + str(body.get("text", "")) + "\n}\n"
        doc = parse_text(text)
        groups = find_groups(doc, "meta", self.ws.schema)
        block = str(body.get("block", ""))
        rel = "common/pop_types.txt" if block.endswith("_chance") else "poptypes/x.txt"
        combine, note = combine_of(rel, [block, str(body.get("target", ""))])
        for g in groups:
            g.combine, g.combine_note, g.path = combine, note, [block or "modifiers"]
        if steps is None:
            return {"groups": [{**asdict(g), "signature": g.signature} for g in groups]}
        group = next((g for g in groups if g.id == body.get("id")), None)
        if group is None:
            raise ApiError(HTTPStatus.CONFLICT, "the group is gone (the code changed?)")
        try:
            new = apply_edits(text, rewrite_edits(doc, group, steps))
        except ValueError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        return {"text": new[len(head) : -len("\n}\n")]}

    # -- bigger window backgrounds (K94) ---------------------------------------------------
    def stretch_picture(self, body: dict[str, Any]) -> dict[str, Any]:
        """A sprite's picture at a new size with its frame kept (nine-slice, K94).

        Without ``write``: a small PNG preview (base64). With ``write``: the
        picture becomes a *new* file and a new sprite, and only the element
        (``rel`` + ``line`` of its block in a ``.gui`` file) is pointed at it -
        textures such as ``main_bg.dds`` are shared by many windows, so the
        original stays as it is:

        - ``gfx/interface/vic2toolmod/<stem>_<w>x<h>.dds`` (or ``.tga``),
        - ``GFX_<name>_<w>x<h>`` in ``interface/vic2toolmod_stretched.gfx``,
        - the element's ``spriteType`` / ``quadTextureSprite`` in the ``.gui``.
        """
        import base64

        from vic2toolmod.analysis.gui_tree import _SPRITE_KEYS
        from vic2toolmod.edit import apply_edits, replace_token_text
        from vic2toolmod.images import (
            ImageError,
            dds,
            image_to_rgba,
            png,
            quiet_frame,
            shrink,
            stretch,
            tga,
        )

        name = str(body["sprite"])
        s = self.ws.registries().sprites.get(name.lower())
        rel = self.texture(s.texture) if s else None
        f = self.ws.file(rel) if rel else None
        if s is None or f is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"no picture for sprite {name!r}")
        if s.frames > 1:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY, "an icon strip (several frames) is not stretched"
            )
        width, height = int(body["width"]), int(body["height"])
        if not (1 <= width <= 8192 and 1 <= height <= 8192):
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "the size must be 1..8192")
        try:
            w, h, px = image_to_rgba(f.path.read_bytes())
            raw = body.get("border", 40)
            border: int | tuple[int, int, int, int]
            if raw == "auto":  # repeat one even column / row before the right / bottom edge
                box = body.get("inside")  # the part of the picture the window shows
                inside = (int(box[0]), int(box[1]), int(box[2]), int(box[3])) if box else None
                border = quiet_frame(w, h, px, inside)
            elif isinstance(raw, list):
                border = (int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3]))
            else:
                border = int(raw)
            out = stretch(w, h, px, width, height, border)
        except ImageError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        result: dict[str, Any] = {
            "file": f.rel,
            "from": [w, h],
            "to": [width, height],
            "border": list(border) if isinstance(border, tuple) else [border] * 4,
        }
        if not body.get("write"):
            pw, ph, small = shrink(width, height, out, 480)
            result["preview"] = base64.b64encode(png(pw, ph, small)).decode()
            return result
        mod = self.ws.project.mod_dir
        if mod is None:
            self._write([])  # refused: only the game is open
        assert mod is not None
        # the element that shows the picture
        gui = self._file_or_404(str(body.get("rel", "")))
        doc = self.ws.document(gui)
        line = int(body.get("line", 0))
        node = next(
            (
                n
                for n in doc.walk()
                if isinstance(n, Assignment)
                and isinstance(n.value, Block)
                and doc.position(n.start)[0] == line
            ),
            None,
        )
        ref = (
            next(
                (
                    i
                    for i in node.value.items
                    if isinstance(i, Assignment)
                    and i.key_text.lower() in _SPRITE_KEYS
                    and isinstance(i.value, Scalar)
                ),
                None,
            )
            if node is not None and isinstance(node.value, Block)
            else None
        )
        if ref is None or not isinstance(ref.value, Scalar):
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY, f"no element with a picture at line {line}"
            )
        base = name[4:] if name.upper().startswith("GFX_") else name
        stem = Path(f.rel).stem
        suffix = ".tga" if f.rel.lower().endswith(".tga") else ".dds"
        tex_rel = f"gfx/interface/vic2toolmod/{stem}_{width}x{height}{suffix}"
        new_name = f"GFX_{base}_{width}x{height}"
        gfx_rel = "interface/vic2toolmod_stretched.gfx"
        gfx_file = self.ws.file(gfx_rel)
        gfx_old = self.ws.document(gfx_file.rel).text if gfx_file else None
        entry = (
            f'\tspriteType = {{\n\t\tname = "{new_name}"\n'
            f'\t\ttexturefile = "{tex_rel.replace("/", chr(92) * 2)}"\n'
            f"\t\tnorefcount = yes\n\t}}\n"
        )
        if gfx_old is None:
            gfx_new = (
                "# Pictures stretched by vic2toolmod (K94): bigger window backgrounds.\n"
                "spriteTypes = {\n" + entry + "}\n"
            )
        elif f'"{new_name}"' in gfx_old:
            gfx_new = gfx_old
        else:
            end = gfx_old.rstrip().rfind("}")
            gfx_new = gfx_old[:end] + entry + gfx_old[end:]
        gui_old = doc.text
        gui_new = apply_edits(gui_old, [replace_token_text(ref.value, f'"{new_name}"')])
        changes = [
            FileChange(gfx_rel, mod / gfx_rel, gfx_old, gfx_new),
            FileChange(gui, mod / gui, gui_old, gui_new, self.ws.encoding(gui)),
        ]
        backup = self._write([c for c in changes if c.old_text != c.new_text])
        target = mod / tex_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        data = tga(width, height, out) if suffix == ".tga" else dds(width, height, out)
        target.write_bytes(data)
        self.ws.revert(gui)
        self._sprites.clear()
        self.ws.refresh()
        self._stamps = self._snapshot()
        result.update(
            written=True,
            texture=tex_rel,
            sprite=new_name,
            backup=str(backup) if backup else None,
        )
        return result

    # -- formatting (T011) ---------------------------------------------------------------
    def format_text(self, text: str) -> dict[str, Any]:
        """One text formatted (the editor applies it as one undo step)."""
        from vic2toolmod.format import FormatError, format_text

        try:
            return {"text": format_text(text)}
        except FormatError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    def format_plan(self) -> dict[str, Any]:
        """Format every script file of the mod (nothing written): what would change."""
        from vic2toolmod.format import format_mod

        try:
            plan = format_mod(self.ws)
        except ValueError as exc:
            raise ApiError(HTTPStatus.CONFLICT, str(exc)) from exc
        self._format_plan = plan
        return {
            "files": [{"rel": c.rel, "lines": plan.lines[c.rel]} for c in plan.changes],
            "skipped": [{"rel": r, "reason": why} for r, why in sorted(plan.skipped.items())],
            "same": plan.same,
        }

    def format_diff(self, rel: str) -> dict[str, Any]:
        """Diff of one file of the last plan."""
        plan = self._format_plan
        change = next((c for c in plan.changes if c.rel == rel), None) if plan else None
        if change is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"{rel} is not in the last formatting plan")
        return {"diff": diff([change])}

    def format_write(self, rels: list[str]) -> dict[str, Any]:
        """Write chosen files of the last plan (only if they did not change since)."""
        from vic2toolmod.textio import decode

        plan = self._format_plan
        if plan is None:
            raise ApiError(HTTPStatus.CONFLICT, "make the plan first")
        wanted = set(rels)
        changes = [c for c in plan.changes if c.rel in wanted]
        for c in changes:
            now, _ = decode(c.path.read_bytes())
            if now != c.old_text or self.ws.has_unsaved(c.rel, now):
                raise ApiError(
                    HTTPStatus.CONFLICT, f"{c.rel} changed since the plan: make the plan again"
                )
        try:
            backup = self._write(changes)
        except ValueError as exc:  # EncodingError
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        for c in changes:
            self.ws.revert(c.rel)
        self.ws.refresh()
        self._format_plan = None
        return {"written": len(changes), "backup": str(backup) if backup else None}

    # -- light Python scripts (T007) -----------------------------------------------
    def scripts(self) -> dict[str, Any]:
        """All scripts with their fields and code."""
        from vic2toolmod.pyscripts import list_scripts, user_dir

        return {
            "dir": str(self.scripts_dir or user_dir()),
            "scripts": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "builtin": s.builtin,
                    "code": s.code,
                    "params": [asdict(p) for p in s.params],
                }
                for s in list_scripts(self.scripts_dir)
            ],
        }

    def script_run(self, body: dict[str, Any]) -> dict[str, Any]:
        """Run a script (its saved code, or ``code`` from the editor); ``write`` applies it."""
        from vic2toolmod.pyscripts import ScriptError, get_script, parse_script, run

        try:
            if body.get("code") is not None:
                script = parse_script(str(body.get("id") or "edited"), str(body["code"]))
            else:
                script = get_script(str(body["id"]), self.scripts_dir)
            given = {str(k): str(v) for k, v in (body.get("values") or {}).items()}
            result = run(self.ws, script, given)
        except ScriptError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        out: dict[str, Any] = {
            "output": result.output,
            "error": result.error,
            "diff": diff(result.changes),
            "files": [c.rel for c in result.changes],
        }
        if body.get("write") and result.changes and not result.error:
            try:
                backup = self._write(result.changes)
            except ValueError as exc:  # EncodingError
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
            for c in result.changes:
                self.ws.revert(c.rel)  # open editors reload the new text
            self.ws.refresh()
            out["backup"] = str(backup) if backup else None
            out["written"] = True
        return out

    def script_save(self, body: dict[str, Any]) -> dict[str, Any]:
        """Save one of the author's scripts."""
        from vic2toolmod.pyscripts import ScriptError, save_script

        try:
            s = save_script(
                str(body["name"]),
                str(body["code"]),
                overwrite=bool(body.get("overwrite")),
                own=self.scripts_dir,
            )
        except (ScriptError, SyntaxError) as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        return {"id": s.id}

    def script_delete(self, sid: str) -> dict[str, Any]:
        """Delete one of the author's scripts."""
        from vic2toolmod.pyscripts import ScriptError, delete_script

        try:
            delete_script(sid, self.scripts_dir)
        except ScriptError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        return {"deleted": sid}

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

    # -- versions of the mod (T025) ----------------------------------------------------
    def _versions(self) -> Any:
        from vic2toolmod.versions import store

        mod = self.ws.project.mod_dir
        if mod is None:
            raise ApiError(
                HTTPStatus.FORBIDDEN, "the game's own files have no versions: open a mod"
            )
        return store(mod)

    def versions(self) -> dict[str, Any]:
        """How the mod's versions are kept (git / copies) and the list, newest first."""
        from vic2toolmod.versions import VersionError

        try:
            return asdict(self._versions().info())
        except VersionError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    def versions_files(self, vid: str, compare: bool) -> dict[str, Any]:
        """Files a version changed, or (``compare``) files that differ from it now."""
        from vic2toolmod.versions import VersionError

        try:
            v = self._versions()
            found = v.compare(vid) if compare else v.files(vid)
        except VersionError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        return {"files": [{"status": s, "path": p} for s, p in found]}

    def versions_save(self, body: dict[str, Any]) -> dict[str, Any]:
        """Save the whole mod as a new version (editor texts must be saved first)."""
        from vic2toolmod.versions import VersionError

        name = str(body.get("name", "")).strip()
        if not name:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "give the version a name")
        self._no_unsaved()
        try:
            v = self._versions().save(name, str(body.get("description", "")))
        except VersionError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        return asdict(v)

    def versions_restore(self, body: dict[str, Any]) -> dict[str, Any]:
        """Make the mod's files what they were in a version; the state now is saved first."""
        from vic2toolmod.versions import VersionError

        self._no_unsaved()
        try:
            v = self._versions().restore(str(body["id"]), str(body.get("name", body["id"])))
        except VersionError as exc:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        # every file may have changed: read them from disk again
        self.ws.refresh()
        self._groups.clear()
        return {"version": asdict(v) if v else None}

    def _no_unsaved(self) -> None:
        unsaved = self.ws.unsaved()
        if unsaved:
            shown = ", ".join(unsaved[:5]) + (" …" if len(unsaved) > 5 else "")
            raise ApiError(
                HTTPStatus.CONFLICT, f"save or revert the files open in the editor first: {shown}"
            )

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

    def image(self, rel: str) -> bytes:
        """A picture file under ``gfx/`` (``.tga`` / ``.dds``) as PNG (T006)."""
        from vic2toolmod.images import ImageError, image_to_rgba, png

        low = rel.replace("\\", "/").lower()
        if not low.startswith("gfx/") or not low.endswith((".tga", ".dds")) or ".." in low:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"not a picture under gfx/: {rel!r}")
        f = self.ws.file(rel)
        if f is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"no file {rel!r}")
        st = f.path.stat()
        key = (f.rel.lower(), st.st_size, st.st_mtime_ns, 0, 0)
        cached = self._sprites.get(key)
        if cached is None:
            try:
                cached = png(*image_to_rgba(f.path.read_bytes()))
            except ImageError as exc:
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
            if len(self._sprites) > 2000:
                self._sprites.clear()
            self._sprites[key] = cached
        return cached

    def texture(self, texture: str) -> str | None:
        """Relative path of a texture named in a ``.gfx`` file, if it exists.

        ``.gfx`` files write paths with backslashes and often ``.tga`` while the
        file is ``.dds`` (the game tries the other extension too).
        """
        rel = texture.replace("\\", "/").strip().lstrip("/")
        while "//" in rel:
            rel = rel.replace("//", "/")
        stem, dot, ext = rel.rpartition(".")
        candidates = [rel]
        if dot and ext.lower() in ("tga", "dds"):
            candidates.append(f"{stem}.{'dds' if ext.lower() == 'tga' else 'tga'}")
        for c in candidates:
            f = self.ws.file(c)
            if f is not None:
                return f.rel
        return None

    def sprite(self, name: str, frame: int) -> bytes:
        """One frame (from 1) of a sprite of ``interface/*.gfx`` as PNG (T003)."""
        from vic2toolmod.images import ImageError, image_to_rgba, png
        from vic2toolmod.images import frame as crop

        s = self.ws.registries().sprites.get(name.lower())
        if s is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"no sprite {name!r}")
        rel = self.texture(s.texture)
        if rel is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"texture {s.texture!r} not found")
        f = self.ws.file(rel)
        assert f is not None
        st = f.path.stat()
        key = (rel.lower(), st.st_size, st.st_mtime_ns, s.frames, frame)
        cached = self._sprites.get(key)
        if cached is None:
            try:
                cached = png(*crop(*image_to_rgba(f.path.read_bytes()), s.frames, frame))
            except ImageError as exc:
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
            if len(self._sprites) > 2000:
                self._sprites.clear()
            self._sprites[key] = cached
        return cached

    def poptypes_graph(self) -> dict[str, Any]:
        """Promotion graph of the pop types (K59)."""
        from vic2toolmod.analysis.poptypes import pop_weights, promotion_graph

        return promotion_graph(pop_weights(self.ws))


def _recent_file() -> Path:
    from vic2toolmod.config import config_path

    return config_path().parent / "recent.json"


def _recent() -> list[str]:
    """Recently opened mod folders, newest first."""
    try:
        data = json.loads(_recent_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(d) for d in data if isinstance(d, str)] if isinstance(data, list) else []


def _remember(mod_dir: Path) -> None:
    items = [str(mod_dir)] + [d for d in _recent() if d != str(mod_dir)]
    try:
        _recent_file().parent.mkdir(parents=True, exist_ok=True)
        _recent_file().write_text(json.dumps(items[:10], indent=1), encoding="utf-8")
    except OSError:
        pass  # not remembered; opening still works


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
            life = engine.lifetime
            if not url.path.startswith("/api/"):
                if method == "GET":
                    if life is not None:
                        life.seen()
                    return self._static(url.path)
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            if not self._authorised(query):
                return self._json(HTTPStatus.FORBIDDEN, {"error": "bad or missing token"})
            route = (method, url.path[len("/api/") :])
            # The server's own life: answered without waiting for the engine.
            if route == ("GET", "ping"):
                return self._json(HTTPStatus.OK, engine.ping())
            if route in (("POST", "bye"), ("POST", "quit"), ("POST", "restart")):
                if life is not None:
                    if route[1] == "bye":
                        life.bye((query.get("client") or [""])[0])
                    else:
                        life.restart = route[1] == "restart"
                        life.stop_now = True
                return self._json(HTTPStatus.OK, {"ok": life is not None})
            if life is not None:
                life.seen(self.headers.get("X-Client") or "")
            body: dict[str, Any] = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    return self._json(HTTPStatus.BAD_REQUEST, {"error": "body is not JSON"})

            def q(name: str, default: str = "") -> str:
                return (query.get(name) or [default])[0]

            if route == ("GET", "changed"):  # takes the lock itself, only briefly
                return self._json(HTTPStatus.OK, engine.changed())
            if route in (("GET", "picture"), ("GET", "sprite"), ("GET", "image")):
                try:
                    with engine.lock:
                        if route[1] == "sprite":
                            image = engine.sprite(q("name"), int(q("frame", "1")))
                        elif route[1] == "image":
                            image = engine.image(q("rel"))
                        else:
                            image = engine.picture(q("name"))
                except ApiError as exc:
                    return self._json(exc.status, {"error": str(exc)})
                except ValueError as exc:
                    return self._json(HTTPStatus.BAD_REQUEST, {"error": f"bad request: {exc}"})
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
                case ("GET", "gui/windows"):
                    return e.gui_windows(q("rel"))
                case ("GET", "gui/window"):
                    return e.gui_window(q("rel"), q("name"))
                case ("POST", "gui/plan"):
                    return e.gui_plan(body)
                case ("GET", "projects"):
                    return e.projects()
                case ("POST", "project/open"):
                    return e.open_project(body.get("mod"))
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
                case ("POST", "create/country"):
                    return e.create("country", body)
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
                case ("GET", "versions"):
                    return e.versions()
                case ("GET", "versions/files"):
                    return e.versions_files(q("id"), q("compare") == "1")
                case ("POST", "versions/save"):
                    return e.versions_save(body)
                case ("POST", "versions/restore"):
                    return e.versions_restore(body)
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
                case ("GET", "modgroups"):
                    return e.modgroups(q("rel"))
                case ("POST", "modgroups/edits"):
                    return e.modgroup_edits(body)
                case ("POST", "modgroups/plan"):
                    return e.modgroup_plan(body)
                case ("GET", "meta"):
                    return e.meta()
                case ("POST", "meta/plan"):
                    return e.meta_plan(body)
                case ("POST", "modgroups/text"):
                    return e.modgroups_text(body, None)
                case ("POST", "modgroups/text-edit"):
                    return e.modgroups_text(body, _steps(body))
                case ("POST", "picture/stretch"):
                    return e.stretch_picture(body)
                case ("POST", "format/text"):
                    return e.format_text(str(body["text"]))
                case ("POST", "format/plan"):
                    return e.format_plan()
                case ("GET", "format/diff"):
                    return e.format_diff(q("rel"))
                case ("POST", "format/write"):
                    return e.format_write([str(r) for r in body.get("rels") or []])
                case ("GET", "scripts"):
                    return e.scripts()
                case ("POST", "script/run"):
                    return e.script_run(body)
                case ("POST", "script/save"):
                    return e.script_save(body)
                case ("POST", "script/delete"):
                    return e.script_delete(str(body["id"]))
                case ("POST", "trigger"):
                    return e.trigger(body["rel"], int(body["offset"]), body.get("answers") or {})
                case ("POST", "trigger/world"):
                    return e.trigger_world(body)
                case ("POST", "trigger/countries"):
                    return e.trigger_countries(body)
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
    workspace: Workspace,
    port: int = 0,
    token: str | None = None,
    warm_up: bool = False,
    lifetime: Lifetime | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    """Create (not start) the server on 127.0.0.1; returns it and its token.

    With ``warm_up`` the index is built and the mod checked in a background
    thread right away (`Engine.warm_up`), so the first requests are fast.
    With ``lifetime`` the server stops on its own (`lifecycle.Lifetime`); the
    caller starts ``lifetime.watch(server.shutdown)``.
    """
    token = token or secrets.token_urlsafe(24)
    engine = Engine(workspace)
    engine.lifetime = lifetime
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(engine, token))
    server.engine = engine  # type: ignore[attr-defined]
    if warm_up:
        threading.Thread(target=engine.warm_up, name="warm-up", daemon=True).start()
    return server, token
