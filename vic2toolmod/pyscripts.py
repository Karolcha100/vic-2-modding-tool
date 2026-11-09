"""Light Python scripts for repeated jobs on a mod (T007).

A script is a ``.py`` file run inside the tool. It gets two names:

- ``mod``: a `ModApi` (find files, read, write, replace text, parse, names);
- ``params``: the values of its fields (``dict[str, str | int | bool]``).

``print`` goes to the script's output. Nothing is written while the script
runs: ``mod.write`` / ``mod.replace`` only plan changes, which are shown as a
diff and written (with a backup) only when asked (``--write`` / "Apply").

Lines at the top starting with ``#@`` describe the script::

    #@ name: Replace text in files
    #@ description: Replace a text (or a regular expression) in many files.
    #@ param: files = events/*.txt | which files (* also crosses folders)
    #@ param: old | text to find
    #@ param: regex:bool = no | "old" is a regular expression

A field is ``name[:type][ = default][ | help]``; types: ``text`` (the
default), ``int``, ``bool`` (``yes`` / ``no``). Built-in scripts live next to
this module (``pyscripts_data``), the author's own ones in the ``scripts``
folder next to the settings file (``~/.config/vic2toolmod/scripts/`` on Linux).

Scripts are ordinary Python with full access to the computer, like any
program you run: run only scripts you wrote or read.
"""

from __future__ import annotations

import fnmatch
import io
import re
import traceback
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vic2toolmod.changes import FileChange
from vic2toolmod.config import config_path
from vic2toolmod.script.cst import Document
from vic2toolmod.script.parser import parse_text
from vic2toolmod.textio import Encoding, decode
from vic2toolmod.workspace import Workspace

BUILTIN_DIR = Path(__file__).with_name("pyscripts_data")
_HEADER = re.compile(r"#\s*@\s*([a-z]+)\s*:\s?(.*)")
_PARAM = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*(?P<type>[a-z]+)\s*)?"
    r"(?:=\s*(?P<default>[^|]*?)\s*)?(?:\|\s*(?P<help>.*))?$"
)
_SLUG = re.compile(r"[^a-z0-9]+")
_TYPES = ("text", "int", "bool")


class ScriptError(ValueError):
    """A script cannot be run (bad field, bad file name …)."""


def user_dir() -> Path:
    """Folder of the author's own scripts."""
    return config_path().parent / "scripts"


@dataclass(frozen=True)
class Param:
    """A field of a script."""

    name: str
    type: str = "text"
    default: str = ""
    help: str = ""


@dataclass
class Script:
    """A script file.

    Attributes:
        id: ``builtin/<file stem>`` or ``own/<file stem>``.
        name: Shown name.
        description: One or two sentences.
        params: Fields to fill in.
        code: The whole file (header included).
        builtin: Shipped with the tool (cannot be changed or deleted).
    """

    id: str
    name: str
    description: str
    params: list[Param]
    code: str
    builtin: bool = False


def parse_script(sid: str, code: str, builtin: bool = False) -> Script:
    """Read the ``#@`` header of a script."""
    meta: dict[str, str] = {}
    params: list[Param] = []
    for line in code.replace("\r\n", "\n").split("\n"):
        m = _HEADER.match(line.strip())
        if not m:
            if line.strip() and not line.lstrip().startswith("#"):
                break  # the header ends at the first line of code
            continue
        if m[1] == "param":
            p = _PARAM.match(m[2].strip())
            if not p:
                raise ScriptError(f"bad field line {m[2]!r}: name[:type][ = default][ | help]")
            kind = p["type"] or "text"
            if kind not in _TYPES:
                raise ScriptError(f"field {p['name']!r}: unknown type {kind!r} (text, int, bool)")
            params.append(Param(p["name"], kind, (p["default"] or "").strip(), p["help"] or ""))
        else:
            meta[m[1]] = m[2].strip()
    return Script(
        id=sid,
        name=meta.get("name") or sid.split("/")[-1],
        description=meta.get("description", ""),
        params=params,
        code=code,
        builtin=builtin,
    )


def list_scripts(own: Path | None = None) -> list[Script]:
    """Built-in scripts first, then the author's own (by name)."""
    out = [
        parse_script(f"builtin/{p.stem}", p.read_text(encoding="utf-8"), builtin=True)
        for p in sorted(BUILTIN_DIR.glob("*.py"))
    ]
    folder = own or user_dir()
    if folder.is_dir():
        mine = []
        for p in folder.glob("*.py"):
            try:
                mine.append(parse_script(f"own/{p.stem}", p.read_text(encoding="utf-8")))
            except ScriptError as exc:
                text = p.read_text(encoding="utf-8")
                mine.append(Script(f"own/{p.stem}", p.stem, f"header error: {exc}", [], text))
        out += sorted(mine, key=lambda s: s.name.lower())
    return out


def get_script(sid: str, own: Path | None = None) -> Script:
    """One script by id, or a ``.py`` file given by its path."""
    for s in list_scripts(own):
        if s.id == sid or s.id.split("/", 1)[1] == sid:
            return s
    path = Path(sid)
    if path.suffix == ".py" and path.is_file():
        return parse_script(f"file/{path.stem}", path.read_text(encoding="utf-8"))
    raise ScriptError(f"no script {sid!r}")


def save_script(name: str, code: str, overwrite: bool = False, own: Path | None = None) -> Script:
    """Save one of the author's scripts (``own/<slug of name>``).

    The ``#@ name:`` line is set to ``name`` (added when missing).
    """
    slug = _SLUG.sub("_", name.lower()).strip("_")
    if not slug:
        raise ScriptError("the script needs a name")
    lines = code.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if (m := _HEADER.match(line.strip())) and m[1] == "name":
            lines[i] = f"#@ name: {name.strip()}"
            break
    else:
        lines.insert(0, f"#@ name: {name.strip()}")
    text = "\n".join(lines).rstrip("\n") + "\n"
    script = parse_script(f"own/{slug}", text)
    compile(text, f"{slug}.py", "exec")  # SyntaxError for code that cannot run
    target = (own or user_dir()) / f"{slug}.py"
    if target.exists() and not overwrite:
        raise ScriptError(f"a script named {name!r} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return script


def delete_script(sid: str, own: Path | None = None) -> None:
    """Delete one of the author's scripts (built-in ones cannot be deleted)."""
    if not sid.startswith("own/"):
        raise ScriptError("only your own scripts can be deleted")
    folder = own or user_dir()
    path = folder / f"{sid[4:]}.py"
    if path.parent != folder or not path.is_file():
        raise ScriptError(f"no script {sid!r}")
    path.unlink()


def values(script: Script, given: dict[str, str]) -> dict[str, str | int | bool]:
    """Field values with their types (missing ones take the default)."""
    out: dict[str, str | int | bool] = {}
    for p in script.params:
        raw = str(given.get(p.name, p.default)).strip()
        if p.type == "int":
            try:
                out[p.name] = int(raw)
            except ValueError:
                raise ScriptError(f"{p.name}: a whole number is needed") from None
        elif p.type == "bool":
            if raw not in ("yes", "no"):
                raise ScriptError(f"{p.name}: yes or no")
            out[p.name] = raw == "yes"
        else:
            out[p.name] = raw
    unknown = set(given) - {p.name for p in script.params}
    if unknown:
        raise ScriptError(f"unknown field(s): {', '.join(sorted(unknown))}")
    return out


@dataclass
class Match:
    """A line found by `ModApi.find`."""

    rel: str
    line: int
    text: str


class ModApi:
    """What a script sees as ``mod``.

    Paths are relative to the mod folder with ``/`` (``events/501_x.txt``);
    any spelling of upper / lower case finds the file.
    """

    def __init__(self, ws: Workspace) -> None:
        self.ws = ws
        """The whole engine (`Workspace`) for anything the helpers do not cover."""
        self._changes: dict[str, FileChange] = {}

    # -- files -------------------------------------------------------------------
    def files(self, pattern: str = "*.txt", only_mod: bool = True) -> list[str]:
        """Files whose path matches ``pattern`` (``*`` also crosses folders, any case).

        With ``only_mod`` (the default) only the mod's own files; ``False`` adds
        the game files the mod does not replace.
        """
        pat = pattern.replace("\\", "/").lower()
        mod_only = only_mod and self.ws.project.mod_dir is not None
        return [
            f.rel
            for low, f in sorted(self.ws.project.files().items())
            if fnmatch.fnmatchcase(low, pat) and (not mod_only or f.origin == "mod")
        ]

    def read(self, rel: str) -> str:
        """Text of a file (with the changes this script already planned)."""
        planned = self._changes.get(rel.lower())
        if planned is not None:
            return planned.new_text
        f = self.ws.file(rel)
        if f is None:
            raise ScriptError(f"no file {rel!r}")
        return self.ws.document(f.rel).text

    def write(self, rel: str, text: str) -> None:
        """Plan new text for a file (a new file or a copy of a game file goes into the mod)."""
        mod = self.ws.project.mod_dir
        if mod is None:
            raise ScriptError("the game's own files are read-only: open a mod to change files")
        clean = rel.strip().replace("\\", "/")
        if not clean or clean.startswith("/") or ".." in clean.split("/"):
            raise ScriptError(f"bad file name {rel!r} (a path inside the mod)")
        f = self.ws.file(clean)
        target = mod / (f.rel if f else clean)
        key = (f.rel if f else clean).lower()
        if key in self._changes:
            old = self._changes[key]
            self._changes[key] = FileChange(old.rel, old.path, old.old_text, text, old.encoding)
            return
        old_text: str | None = None
        encoding = Encoding.CP1252
        if target.is_file():
            old_text, encoding = decode(target.read_bytes())
            if f is not None and self.ws.has_unsaved(f.rel, old_text):
                raise ScriptError(
                    f"{f.rel} has unsaved changes in the editor: save or revert it first"
                )
        elif f is not None:  # a game file: the mod gets its own copy
            encoding = self.ws.encoding(f.rel)
        if old_text == text:
            return
        self._changes[key] = FileChange(f.rel if f else clean, target, old_text, text, encoding)

    def replace(
        self,
        old: str,
        new: str,
        files: str = "*.txt",
        regex: bool = False,
        only_mod: bool = True,
    ) -> int:
        r"""Replace ``old`` by ``new`` in all matching files; returns the number of replacements.

        With ``regex``, ``old`` is a Python regular expression and ``new`` may use
        ``\1`` / ``\g<name>``.
        """
        if not old:
            raise ScriptError("nothing to replace: 'old' is empty")
        pattern = re.compile(old if regex else re.escape(old))
        total = 0
        for rel in self.files(files, only_mod):
            text = self.read(rel)
            if regex:
                changed, n = pattern.subn(new, text)
            else:
                changed, n = text.replace(old, new), text.count(old)
            if n:
                self.write(rel, changed)
                total += n
        return total

    def find(
        self, text: str, files: str = "*.txt", regex: bool = False, only_mod: bool = True
    ) -> list[Match]:
        """Lines containing ``text`` (or matching the regular expression)."""
        pattern = re.compile(text if regex else re.escape(text))
        out = []
        for rel in self.files(files, only_mod):
            for n, line in enumerate(self.read(rel).splitlines(), 1):
                if pattern.search(line):
                    out.append(Match(rel, n, line.strip()))
        return out

    # -- engine ----------------------------------------------------------------------
    def document(self, rel: str) -> Document:
        """Parsed file (syntax tree, see `vic2toolmod.script.cst`) of the saved text."""
        planned = self._changes.get(rel.lower())
        if planned is not None:
            return parse_text(planned.new_text)
        f = self.ws.file(rel)
        if f is None:
            raise ScriptError(f"no file {rel!r}")
        return self.ws.document(f.rel)

    def names(self, kind: str) -> list[str]:
        """Names of a registry (``country``, ``event``, ``modifier``, ``flag`` …)."""
        return sorted(self.ws.registries().names.get(kind, {}))

    @property
    def changes(self) -> list[FileChange]:
        """The changes planned so far."""
        return list(self._changes.values())


@dataclass
class RunResult:
    """What a run of a script gave.

    Attributes:
        changes: Planned file changes.
        output: Everything the script printed.
        error: The error message (with the script's lines of the traceback), or ``""``.
    """

    changes: list[FileChange] = field(default_factory=list)
    output: str = ""
    error: str = ""


def run(ws: Workspace, script: Script, given: dict[str, str] | None = None) -> RunResult:
    """Run a script: nothing is written, the result holds the planned changes.

    Raises:
        ScriptError: For bad field values (the script is not started).
    """
    params = values(script, given or {})
    api = ModApi(ws)
    out = io.StringIO()
    name = f"<{script.id}>"
    scope: dict[str, Any] = {"__name__": "__vic2script__", "mod": api, "params": params}
    error = ""
    try:
        code = compile(script.code, name, "exec")
        with redirect_stdout(out):
            exec(code, scope)  # noqa: S102 - running the author's script is the feature
    except Exception as exc:  # the script's own error: show it, keep the tool running
        frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == name]
        where = "".join(f"  line {f.lineno}: {f.line}\n" for f in frames)
        if isinstance(exc, SyntaxError):
            where = f"  line {exc.lineno}: {(exc.text or '').strip()}\n"
            message = exc.msg
        else:
            message = str(exc)
        error = f"{type(exc).__name__}: {message}\n{where}".rstrip()
    return RunResult(api.changes, out.getvalue(), error)
