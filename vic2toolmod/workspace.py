"""The engine's single entry point for tools and the GUI.

A `Workspace` holds one project (game + mod): its documents (parsed lazily,
cached by file size and modification time, or taken from an editor buffer),
the registries of names, and the references between files. It answers the
questions an editor asks: what is wrong with this file, where is this name
defined, where is it used.

Typical use::

    ws = Workspace.open(game_dir, mod_dir)
    for report in ws.check():
        ...
    ws.definition("culture", "british")
    ws.usages("country", "ENG")
    ws.set_text("events/MyEvents.txt", edited_text)   # unsaved editor content
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vic2toolmod.check import FileReport, IgnoreRules, load_ignore_rules
from vic2toolmod.project.layout import Project, ProjectFile
from vic2toolmod.project.registries import Definition, Registries, RegistryIndex
from vic2toolmod.schema.loader import default_schema
from vic2toolmod.schema.model import Schema
from vic2toolmod.schema.validator import Validator, file_type_for
from vic2toolmod.script.cst import Document
from vic2toolmod.script.diagnostics import Diagnostic, Severity
from vic2toolmod.script.parser import parse_text
from vic2toolmod.textio import Encoding, decode

SCRIPT_SUFFIXES = (".txt", ".gfx", ".gui")


@dataclass(frozen=True, slots=True)
class Usage:
    """One place where a name is used.

    Attributes:
        file: Relative path.
        start: Offset of the name in the file.
        end: Offset just past it.
        line: 1-based line.
        column: 1-based column.
    """

    file: str
    start: int
    end: int
    line: int
    column: int


@dataclass
class _Entry:
    document: Document
    encoding: Encoding
    stamp: tuple[int, int] | None  # (size, mtime_ns) of the file, None = editor buffer


class Workspace:
    """A project with everything the engine knows about it."""

    def __init__(self, project: Project, schema: Schema | None = None) -> None:
        self.project = project
        self.schema = schema or default_schema()
        self.ignore: IgnoreRules = load_ignore_rules(project.mod_dir)
        self._entries: dict[str, _Entry] = {}
        self._registries: Registries | None = None
        self._index = RegistryIndex(project)
        # files changed since the registries were built; None = maybe any file
        self._dirty: set[str] | None = None
        # rel (lower) -> references found in that file by its last check
        self._refs: dict[str, list[tuple[tuple[str, str], Usage]]] = {}
        self._all_checked = False
        # rel (lower) -> (document, names version, diagnostics, references)
        self._reports: dict[
            str, tuple[Document, int, list[Diagnostic], list[tuple[tuple[str, str], Usage]]]
        ] = {}

    @classmethod
    def open(cls, game_dir: Path | None, mod_dir: Path | None = None) -> Workspace:
        """Open a mod on top of the game (either may be ``None``)."""
        return cls(Project.open(game_dir, mod_dir))

    # -- documents -------------------------------------------------------------
    def file(self, rel: str) -> ProjectFile | None:
        """The visible file at a relative path."""
        return self.project.file(rel)

    def document(self, rel: str) -> Document:
        """Parsed document of a file (from the editor buffer if one was set).

        Raises:
            KeyError: If the file does not exist in the project.
        """
        f = self.project.file(rel)
        entry = self._entries.get(rel.lower())
        if entry is not None and entry.stamp is None:
            return entry.document
        if f is None:
            raise KeyError(rel)
        st = f.path.stat()
        stamp = (st.st_size, st.st_mtime_ns)
        if entry is None or entry.stamp != stamp:
            text, encoding = decode(f.path.read_bytes())
            entry = _Entry(parse_text(text), encoding, stamp)
            self._entries[rel.lower()] = entry
        return entry.document

    def encoding(self, rel: str) -> Encoding:
        """Encoding of a file (as read from disk)."""
        self.document(rel)
        return self._entries[rel.lower()].encoding

    def set_text(self, rel: str, text: str) -> Document:
        """Use editor content for a file instead of the file on disk.

        Names defined in the text are picked up on the next `registries` call.
        """
        old = self._entries.get(rel.lower())
        encoding = old.encoding if old else Encoding.CP1252
        doc = parse_text(text)
        self._entries[rel.lower()] = _Entry(doc, encoding, None)
        self._touch(rel)
        return doc

    def revert(self, rel: str) -> None:
        """Forget editor content of a file (read it from disk again)."""
        self._entries.pop(rel.lower(), None)
        self._touch(rel)

    def invalidate(self) -> None:
        """Forget derived data after changes on disk (any file may have changed).

        The registries are then rebuilt from the files that really changed
        (size / time), not from scratch.
        """
        self._registries = None
        self._dirty = None
        self._refs = {}
        self._all_checked = False

    def _touch(self, rel: str) -> None:
        """One file's text changed: only its contribution is taken again."""
        self._registries = None
        if self._dirty is not None:
            self._dirty.add(rel.lower())

    def refresh(self) -> None:
        """Re-scan the folders (new / deleted files) and forget derived data."""
        self.project._files = None
        self.invalidate()

    # -- names -----------------------------------------------------------------
    def registries(self) -> Registries:
        """Names defined in the project (built on first use)."""
        if self._registries is None:
            self._registries = self._index.build(self.document, self._dirty)
            self._dirty = set()
        return self._registries

    @property
    def names_version(self) -> int:
        """Grows when the set of defined names changes (see `RegistryIndex`)."""
        self.registries()
        return self._index.version

    def definition(self, registry: str, name: str) -> Definition | None:
        """Where a name is defined (``None`` if nowhere)."""
        return self.registries().get(registry, name)

    def usages(self, registry: str, name: str) -> list[Usage]:
        """Every place where a name is used (needs a full check, done on first call)."""
        if not self._all_checked:
            self.check(only_mod=False)
        key = (registry, name.lower())
        return [u for refs in self._refs.values() for k, u in refs if k == key]

    def references_in(self, rel: str) -> list[tuple[tuple[str, str], Usage]]:
        """Names a file refers to: ``((registry, lower-case name), usage)`` (checks it)."""
        self.check_file(rel)
        return list(self._refs.get(rel.lower(), []))

    # -- checking ----------------------------------------------------------------
    def check_file(self, rel: str) -> FileReport:
        """Syntax, schema and name diagnostics of one file."""
        f = self.project.file(rel)
        if f is None:
            raise KeyError(rel)
        doc = self.document(rel)
        version = self.names_version
        ft = file_type_for(f.rel, self.schema)
        low = f.rel.lower()
        cached = self._reports.get(low)
        if cached is not None and cached[0] is doc and cached[1] == version:
            found, refs = cached[2], cached[3]
        else:
            # The validator asks the registries only whether names exist, so its
            # result stays valid while the document and the set of names do.
            reg = self.registries()
            validator = Validator(self.schema, reg.has, reg.frames)
            found = list(doc.diagnostics)
            if ft is not None:
                found += validator.validate(doc, ft.rule, ft.scope)
            refs = [
                (
                    (registry, name.lower()),
                    Usage(f.rel, tok.start, tok.end, *doc.position(tok.start)),
                )
                for registry, name, tok in validator.references
            ]
            self._reports[low] = (doc, version, found, refs)
        diags = found + self._duplicate_ids(f.rel, doc)
        diags = sorted((d for d in diags if not self.ignore.ignored(d)), key=lambda d: d.start)
        self._refs[low] = refs
        return FileReport(f, doc, ft.name if ft else None, diags)

    def check(self, only_mod: bool = True) -> list[FileReport]:
        """Check every script file (only the mod's own files when ``only_mod``).

        With ``only_mod``, vanilla files are not validated (their names are still
        known); `usages` validates everything when it is first called.
        """
        mod_only = only_mod and self.project.mod_dir is not None
        reports = [self.check_file(f.rel) for f in self.script_files(only_mod)]
        self._all_checked = self._all_checked or not mod_only
        return reports

    def script_files(self, only_mod: bool = False) -> list[ProjectFile]:
        """Script files (``.txt``, ``.gfx``, ``.gui``).

        With ``only_mod`` only the mod's own files (all files when there is no mod).
        """
        mod_only = only_mod and self.project.mod_dir is not None
        return [f for f in self._script_files() if not mod_only or f.origin == "mod"]

    # -- helpers -----------------------------------------------------------------
    def _script_files(self) -> list[ProjectFile]:
        return [
            f for low, f in sorted(self.project.files().items()) if low.endswith(SCRIPT_SUFFIXES)
        ]

    def _duplicate_ids(self, rel: str, doc: Document) -> list[Diagnostic]:
        out = []
        for dup in self.registries().duplicates.get("event", []):
            if dup.file != rel:
                continue
            first = self.registries().get("event", dup.name)
            where = f"{first.file}:{first.line}" if first else "?"
            out.append(
                Diagnostic(
                    Severity.WARNING,
                    "ref.duplicate-id",
                    f"event id {dup.name} is already used in {where}",
                    doc.lines.line_start(dup.line),
                    doc.lines.line_start(dup.line + 1),
                )
            )
        return out
