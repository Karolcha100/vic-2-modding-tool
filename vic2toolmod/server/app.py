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
``changed``         GET     files changed on disk since the last call (K30)
``parties/plan``    POST    party generator (K58): diff and summary
``parties/write``   POST    same, and write the files
``poptypes/graph``  GET     promotion graph (K59)
``events/graph``    GET     event chains (K6 C)
``vanilla/diff``    GET     mod files vs vanilla; ``rel`` -> diff of one file (K6 H)
``stats``           GET     pops at the start (K6 I)
``localisation``    POST    ``{key, english, other?, write?}`` -> plan / write a key (K35)
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
from vic2toolmod.script.cst import Block, Document
from vic2toolmod.script.diagnostics import Diagnostic
from vic2toolmod.services import LanguageService
from vic2toolmod.workspace import Workspace

STATIC = Path(__file__).parent / "static"
_TYPES = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
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

    def __init__(self, workspace: Workspace) -> None:
        self.ws = workspace
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
        """Text, encoding and diagnostics of a file."""
        rel = self._file_or_404(rel)
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
                case ("GET", "changed"):
                    return e.changed()
                case ("POST", "parties/plan"):
                    return e.parties(body, write=False)
                case ("POST", "parties/write"):
                    return e.parties(body, write=True)
                case ("GET", "poptypes/graph"):
                    return e.poptypes_graph()
                case ("GET", "events/graph"):
                    return e.events_graph()
                case ("GET", "vanilla/diff"):
                    return e.vanilla(q("rel"))
                case ("GET", "stats"):
                    return e.stats()
                case ("POST", "localisation"):
                    return e.localisation(body)
                case ("POST", "trigger"):
                    return e.trigger(body["rel"], int(body["offset"]), body.get("answers") or {})
            return None

        def _static(self, path: str) -> None:
            rel = path.lstrip("/") or "index.html"
            target = (STATIC / rel).resolve()
            if not target.is_relative_to(STATIC.resolve()) or not target.is_file():
                target = STATIC / "index.html"
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
