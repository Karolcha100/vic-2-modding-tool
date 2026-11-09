"""Code templates (K39 = B): built-in ones and the author's own.

A template is a piece of script with fields to fill in. A field is written
``{{name}}``, ``{{name:type}}``, ``{{name=default}}`` or ``{{name:type=default}}``;
the same name may appear many times (the type and default come from any of
them). Types:

- ``text`` (the default): one line without ``"``;
- ``int``: a whole number;
- ``name``: a script name (letters, digits, ``_``, ``.``, ``-``);
- ``bool``: ``yes`` or ``no``;
- ``event_id``: a whole number, by default a free event id (K29);
- ``ref:<kind>``: a name of the mod's registries (``ref:country``,
  ``ref:modifier``, ``ref:event`` …); the GUI offers the known names and a
  name that does not exist yet gives a note, not an error.

Lines at the top starting with ``#@`` describe the template::

    #@ name: Country event with two options
    #@ description: A country event fired by other events.
    #@ folder: events
    #@ loc: EVTNAME{{id}} = {{title}}

``loc`` lines (any number) become English localisation entries. Built-in
templates live next to this module; the author's own ones in the
``templates`` folder next to the settings file
(``~/.config/vic2toolmod/templates/`` on Linux).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from vic2toolmod.changes import FileChange
from vic2toolmod.config import config_path
from vic2toolmod.project.events import MAX_ID, next_free_id
from vic2toolmod.project.localisation import set_entries
from vic2toolmod.textio import Encoding
from vic2toolmod.workspace import Workspace

FIELD = re.compile(
    r"\{\{\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?::\s*(?P<type>[a-z_]+(?::[a-z_]+)?)\s*)?"
    r"(?:=(?P<default>[^}\n]*))?\}\}"
)
_HEADER = re.compile(r"#@\s*([a-z]+)\s*:\s?(.*)")
_SLUG = re.compile(r"[^a-z0-9]+")
_NAME = re.compile(r"[A-Za-z0-9_.\-]+")
_INT = re.compile(r"[-+]?\d+")
_TYPES = ("text", "int", "name", "bool", "event_id")
_REL = re.compile(r"[A-Za-z0-9_\- ]+(/[A-Za-z0-9_\- ]+)*\.txt")

BUILTIN_DIR = Path(__file__).with_name("templates_data")


def user_dir() -> Path:
    """Folder of the author's own templates."""
    return config_path().parent / "templates"


@dataclass(frozen=True)
class TemplateField:
    """A field to fill in."""

    name: str
    type: str = "text"
    default: str = ""


@dataclass
class Template:
    """A template.

    Attributes:
        id: ``builtin/<file stem>`` or ``own/<file stem>``.
        name: Shown name.
        description: One or two sentences.
        folder: Where the code usually goes (``events``, ``decisions`` …), may be empty.
        body: The script with fields.
        loc: ``KEY = English text`` lines with fields.
        builtin: Shipped with the tool (cannot be deleted).
    """

    id: str
    name: str
    description: str
    folder: str
    body: str
    loc: list[str] = field(default_factory=list)
    builtin: bool = False

    @property
    def fields(self) -> list[TemplateField]:
        """The fields in order of first appearance."""
        types: dict[str, str | None] = {}
        default: dict[str, str | None] = {}
        for text in [self.body, *self.loc]:
            for m in FIELD.finditer(text):
                name = m["name"]
                if types.get(name) is None:
                    types[name] = m["type"]
                if default.get(name) is None:
                    default[name] = m["default"]
        return [TemplateField(n, types[n] or "text", (default[n] or "").strip()) for n in types]

    def to_text(self) -> str:
        """The template file's text."""
        head = [f"#@ name: {self.name}"]
        if self.description:
            head.append(f"#@ description: {self.description}")
        if self.folder:
            head.append(f"#@ folder: {self.folder}")
        head += [f"#@ loc: {line}" for line in self.loc]
        return "\n".join(head) + "\n" + self.body.rstrip("\n") + "\n"


def parse_template(tid: str, text: str, builtin: bool = False) -> Template:
    """Read a template file."""
    meta: dict[str, str] = {}
    loc: list[str] = []
    lines = text.replace("\r\n", "\n").split("\n")
    n = 0
    while n < len(lines) and (m := _HEADER.match(lines[n])):
        if m[1] == "loc":
            loc.append(m[2].strip())
        else:
            meta[m[1]] = m[2].strip()
        n += 1
    body = "\n".join(lines[n:]).strip("\n") + "\n"
    return Template(
        id=tid,
        name=meta.get("name") or tid.split("/")[-1],
        description=meta.get("description", ""),
        folder=meta.get("folder", "").strip("/"),
        body=body,
        loc=loc,
        builtin=builtin,
    )


def list_templates(own: Path | None = None) -> list[Template]:
    """Built-in templates first, then the author's own (by name)."""
    out = [
        parse_template(f"builtin/{p.stem}", p.read_text(encoding="utf-8"), builtin=True)
        for p in sorted(BUILTIN_DIR.glob("*.txt"))
    ]
    folder = own or user_dir()
    if folder.is_dir():
        mine = [
            parse_template(f"own/{p.stem}", p.read_text(encoding="utf-8"))
            for p in folder.glob("*.txt")
        ]
        out += sorted(mine, key=lambda t: t.name.lower())
    return out


def get_template(tid: str, own: Path | None = None) -> Template:
    """One template by id."""
    for t in list_templates(own):
        if t.id == tid:
            return t
    raise ValueError(f"no template {tid!r}")


def check_template(t: Template) -> None:
    """Raise ``ValueError`` for a template that cannot work (bad field types, bad loc lines)."""
    for f in t.fields:
        if f.type not in _TYPES and not f.type.startswith("ref:"):
            raise ValueError(f"field {f.name!r}: unknown type {f.type!r}")
    for line in t.loc:
        if "=" not in line:
            raise ValueError(f"loc line {line!r} needs 'KEY = text'")
    if not t.body.strip():
        raise ValueError("the template has no code")


def save_template(
    name: str,
    body: str,
    description: str = "",
    folder: str = "",
    loc: list[str] | None = None,
    overwrite: bool = False,
    own: Path | None = None,
) -> Template:
    """Save one of the author's templates (``own/<slug of name>``)."""
    slug = _SLUG.sub("_", name.lower()).strip("_")
    if not slug:
        raise ValueError("the template needs a name")
    tpl = Template(
        f"own/{slug}", name.strip(), description.strip(), folder.strip().strip("/"), body, loc or []
    )
    check_template(tpl)
    target = (own or user_dir()) / f"{slug}.txt"
    if target.exists() and not overwrite:
        raise ValueError(f"a template named {name!r} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(tpl.to_text(), encoding="utf-8")
    return tpl


def delete_template(tid: str, own: Path | None = None) -> None:
    """Delete one of the author's templates (built-in ones cannot be deleted)."""
    if not tid.startswith("own/"):
        raise ValueError("only your own templates can be deleted")
    path = (own or user_dir()) / f"{tid[4:]}.txt"
    if path.parent != (own or user_dir()) or not path.is_file():
        raise ValueError(f"no template {tid!r}")
    path.unlink()


def defaults(ws: Workspace, t: Template, file: str | None = None) -> dict[str, str]:
    """Starting values of the fields (free event ids are found here)."""
    old = _old_text(ws, file)
    taken: set[int] = set()
    out: dict[str, str] = {}
    for f in t.fields:
        if f.type == "event_id" and not f.default:
            eid = next_free_id(ws.registries(), old, taken)
            taken.add(eid)
            out[f.name] = str(eid)
        else:
            out[f.name] = f.default
    return out


def choices(ws: Workspace, t: Template) -> dict[str, list[str]]:
    """Known names for the ``ref:<kind>`` fields."""
    regs = ws.registries()
    out: dict[str, list[str]] = {}
    for f in t.fields:
        if f.type.startswith("ref:"):
            out[f.name] = sorted(regs.names.get(f.type[4:], {}))
    return out


@dataclass
class Filled:
    """A filled template.

    Attributes:
        text: The script, with the file's line breaks when it goes into a file.
        changes: File changes (the target file, localisation).
        notes: Remarks (names that do not exist yet …).
    """

    text: str
    changes: list[FileChange]
    notes: list[str]


def fill(
    ws: Workspace,
    t: Template,
    values: dict[str, str],
    file: str | None = None,
) -> Filled:
    """Fill a template in.

    Args:
        ws: The project.
        t: The template.
        values: Field values (missing ones take the default).
        file: Mod file to append the code to (``events/MyEvents.txt``, new or
            existing). Without it only the text is returned (to insert into the
            editor) and the changes hold just the localisation.

    Raises:
        ValueError: For a bad value or file name.
    """
    check_template(t)
    vals: dict[str, str] = {}
    notes: list[str] = []
    regs = ws.registries()
    for f in t.fields:
        v = str(values.get(f.name, f.default)).strip()
        problem = _check(f, v)
        if problem:
            raise ValueError(f"{f.name}: {problem}")
        if f.type.startswith("ref:") and not regs.has(f.type[4:], v):
            notes.append(f"{f.name}: {f.type[4:]} {v!r} does not exist (yet)")
        if f.type == "event_id" and regs.has("event", v):
            notes.append(f"{f.name}: event id {v} is already used")
        vals[f.name] = v

    def sub(text: str) -> str:
        return FIELD.sub(lambda m: vals[m["name"]], text)

    body = sub(t.body)
    changes: list[FileChange] = []
    if file is not None:
        rel = _check_rel(file)
        if ws.project.mod_dir is None:
            raise ValueError("a mod folder is needed")
        existing = ws.file(rel)
        rel = existing.rel if existing else rel
        old = ws.document(rel).text if existing else None
        nl = "\r\n" if old is None or "\r\n" in old else "\n"
        piece = body.replace("\r\n", "\n").replace("\n", nl)
        if old is None:
            new = piece
        else:
            sep = "" if not old or old.endswith(("\n", "\r")) else nl
            new = old + sep + nl + piece
        enc = (ws.encoding(rel) if old is not None else None) or Encoding.CP1252
        changes.append(FileChange(rel, ws.project.mod_dir / rel, old, new, enc))
        body = piece
    loc: list[tuple[str, str, dict[str, str]]] = []
    for line in t.loc:
        key, _, english = sub(line).partition("=")
        loc.append((key.strip(), english.strip(), {}))
    if loc:
        changes += set_entries(ws.project, loc)
    return Filled(body, changes, notes)


def _check(f: TemplateField, v: str) -> str | None:
    if f.type in ("int", "event_id"):
        if not _INT.fullmatch(v):
            return "a whole number is needed"
        if f.type == "event_id" and not 0 < int(v) <= MAX_ID:
            return f"an event id must be 1..{MAX_ID}"
        return None
    if f.type == "bool":
        return None if v in ("yes", "no") else "yes or no"
    if f.type == "name" or f.type.startswith("ref:"):
        return None if _NAME.fullmatch(v) else "a name without spaces is needed"
    if '"' in v or "\n" in v:
        return 'the text cannot contain " or a line break'
    return None


def _check_rel(file: str) -> str:
    rel = file.strip().replace("\\", "/")
    if not _REL.fullmatch(rel) or ".." in rel.split("/"):
        raise ValueError(f"bad file name {file!r} (a .txt path inside the mod)")
    return rel


def _old_text(ws: Workspace, file: str | None) -> str | None:
    if not file:
        return None
    f = ws.file(file)
    return ws.document(f.rel).text if f else None
