"""Creator of a new country (K70 E).

A new country is made from an existing one (the template), like the game's
own releasable countries:

- ``common/countries.txt`` gets ``TAG = "countries/<Name>.txt"`` (before
  ``dynamic_tags = yes`` when the file has it - tags after it are dynamic);
- ``common/countries/<Name>.txt`` is the template's file with the new colour,
  and its parties renamed from ``<TPL>_…`` to ``<TAG>_…``;
- ``history/countries/<TAG> - <Name>.txt`` is the template's history without
  dated blocks, units (``oob``), foreign investment, flags and decisions, with
  the given capital, cultures, religion, government and civilisation;
- localisation: ``TAG``, ``TAG_ADJ`` and the renamed parties (their English
  text copied from the template's parties);
- flags: the template's ``gfx/flags/<TPL>*.tga`` copied as placeholders.

Provinces (K76 = C): the given ones get ``add_core = TAG`` in their
``history/provinces`` file (the country can then be released there); with
``exists`` it also owns and controls them from the start (``owner`` /
``controller``, taken from the old owner). Without provinces the country
appears only when released or created by an event / decision (``release``,
``release_vassal``, ``change_tag``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from vic2toolmod.changes import FileChange
from vic2toolmod.edit import (
    TextEdit,
    apply_edits,
    delete,
    insert,
    insert_after,
    newline_of,
    set_value,
)
from vic2toolmod.project.localisation import set_entries
from vic2toolmod.script.cst import Assignment, Block, Document
from vic2toolmod.textio import Encoding
from vic2toolmod.workspace import Workspace

_TAG = re.compile(r"[A-Z][A-Z0-9]{2}")
_FILE_NAME = re.compile(r"[A-Za-z0-9_\- ]+")
_DATE = re.compile(r"\d+\.\d+\.\d+")
_DROP = frozenset(
    {"oob", "foreign_investment", "decision", "set_country_flag", "set_global_flag", "govt_flag"}
)
FLAG_SUFFIXES = ("", "_communist", "_fascist", "_monarchy", "_republic")


@dataclass
class CountrySpec:
    """A new country.

    Attributes:
        tag: Three letters / digits, capital first letter (``BOE``).
        name: English name (``Boer Republic``); also the file names.
        adjective: English adjective (``Boer``).
        template: Tag of the country to copy (``SAF``).
        color: Map colour.
        capital: Capital province id (default: the template's).
        primary_culture: Default: the template's.
        cultures: Accepted cultures; ``None`` keeps the template's.
        religion: Default: the template's.
        government: Default: the template's.
        civilized: ``None`` keeps the template's.
        copy_flags: Copy the template's flags as placeholders.
        provinces: Province ids that get ``add_core = TAG`` (K76).
        exists: The country owns and controls ``provinces`` from the start.
    """

    tag: str
    name: str
    adjective: str
    template: str
    color: tuple[int, int, int]
    capital: int | None = None
    primary_culture: str | None = None
    cultures: list[str] | None = None
    religion: str | None = None
    government: str | None = None
    civilized: bool | None = None
    copy_flags: bool = True
    provinces: list[int] = field(default_factory=list)
    exists: bool = False


@dataclass
class CountryPlan:
    """Planned text changes, binary copies (flags) and remarks."""

    changes: list[FileChange]
    copies: list[tuple[Path, Path]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def plan_country(ws: Workspace, spec: CountrySpec) -> CountryPlan:
    """Plan a new country (nothing is written)."""
    mod = ws.project.mod_dir
    if mod is None:
        raise ValueError("a mod folder is needed")
    regs = ws.registries()
    tag, tpl = spec.tag.strip().upper(), spec.template.strip().upper()
    if not _TAG.fullmatch(tag):
        raise ValueError(f"bad tag {spec.tag!r} (three letters or digits, the first a letter)")
    if regs.has("country", tag):
        raise ValueError(f"country {tag} already exists")
    name = spec.name.strip()
    if not _FILE_NAME.fullmatch(name):
        raise ValueError(f"bad name {spec.name!r} (letters, digits, spaces, _ and -)")
    if any(not 0 <= c <= 255 for c in spec.color):
        raise ValueError("colour values must be 0..255")
    for kind, value in (
        ("culture", spec.primary_culture),
        ("religion", spec.religion),
        ("government", spec.government),
        *(("culture", c) for c in spec.cultures or []),
    ):
        if value and not regs.has(kind, value):
            raise ValueError(f"unknown {kind} {value!r}")
    if spec.capital is not None and not regs.has("province", str(spec.capital)):
        raise ValueError(f"unknown province {spec.capital}")
    bad = [p for p in spec.provinces if not regs.has("province", str(p))]
    if bad:
        raise ValueError(f"unknown province(s) {', '.join(map(str, bad))}")
    if spec.exists and not spec.provinces:
        raise ValueError("a country that exists from the start needs provinces")

    changes: list[FileChange] = []
    notes: list[str] = []

    # common/countries.txt
    list_rel = "common/countries.txt"
    lf = ws.file(list_rel)
    if lf is None:
        raise ValueError("common/countries.txt not found")
    ldoc = ws.document(lf.rel)
    entry = next(
        (a for a in ldoc.assignments() if a.key_text.upper() == tpl and a.value is not None), None
    )
    if entry is None:
        raise ValueError(f"template country {tpl} is not in common/countries.txt")
    country_rel = f"countries/{name}.txt"
    nl = newline_of(ldoc.text)
    line = f'{tag}\t= "{country_rel}"{nl}'
    dyn = ldoc.find("dynamic_tags")
    if dyn is not None:
        at = ldoc.text.rfind("\n", 0, dyn.start) + 1
        # Above the comments and blank lines that head the dynamic tags.
        while at > 0:
            prev = ldoc.text.rfind("\n", 0, at - 1) + 1
            if ldoc.text[prev:at].strip() and not ldoc.text[prev:at].lstrip().startswith("#"):
                break
            at = prev
        new_list = ldoc.text[:at] + line + ldoc.text[at:]
    else:
        sep = "" if ldoc.text.endswith(("\n", "\r")) or not ldoc.text else nl
        new_list = ldoc.text + sep + line
    changes.append(_change(ws, lf.rel, ldoc.text, new_list))

    # common/countries/<Name>.txt
    tpl_country = "common/" + _unquote(entry.value.to_text().strip())  # type: ignore[union-attr]
    cf = ws.file(tpl_country)
    if cf is None:
        raise ValueError(f"{tpl_country} (the template's country file) not found")
    target_country = f"common/{country_rel}"
    if ws.file(target_country) is not None:
        raise ValueError(f"{target_country} already exists")
    cdoc = ws.document(cf.rel)
    edits: list[TextEdit] = []
    color = cdoc.find("color")
    rgb = [str(c) for c in spec.color]
    if color is not None:
        edits.append(set_value(cdoc, color, rgb))
    renamed: dict[str, str] = {}
    for party in cdoc.assignments("party"):
        if not isinstance(party.value, Block):
            continue
        pname = party.value.find("name")
        if pname is None or pname.value is None:
            continue
        old = _unquote(pname.value.to_text().strip())
        if old.upper().startswith(tpl + "_"):
            new = tag + old[len(tpl) :]
            renamed[old] = new
            edits.append(set_value(cdoc, pname, f'"{new}"'))
    country_text = apply_edits(cdoc.text, edits)
    if color is None:
        country_text = f"color = {{ {' '.join(rgb)} }}{newline_of(cdoc.text)}" + country_text
    changes.append(_change(ws, target_country, None, country_text, ws.encoding(cf.rel)))

    # history/countries/<TAG> - <Name>.txt
    hist = _history_file(ws, tpl)
    target_hist = f"history/countries/{tag} - {name}.txt"
    if hist is None:
        notes.append(f"{tpl} has no history file: write {target_hist} yourself")
    else:
        hdoc = ws.document(hist)
        changes.append(
            _change(
                ws,
                target_hist,
                None,
                _history(hdoc, spec, renamed),
                ws.encoding(hist),
            )
        )

    # localisation
    loc = regs.localisation
    entries: list[tuple[str, str, dict[str, str]]] = [
        (tag, name, {}),
        (f"{tag}_ADJ", spec.adjective.strip() or name, {}),
    ]
    for old, new in renamed.items():
        e = loc.get(old) if loc is not None else None
        entries.append((new, e.text() if e else new, {}))
    changes += set_entries(ws.project, entries)

    # flags
    copies: list[tuple[Path, Path]] = []
    if spec.copy_flags:
        for suffix in FLAG_SUFFIXES:
            src = ws.file(f"gfx/flags/{tpl}{suffix}.tga")
            if src is not None:
                copies.append((src.path, mod / "gfx" / "flags" / f"{tag}{suffix}.tga"))
        if copies:
            notes.append(f"{len(copies)} flags copied from {tpl} as placeholders: draw your own")
        else:
            notes.append(f"{tpl} has no flags: add gfx/flags/{tag}.tga etc. yourself")
    # provinces (K76 = C)
    changes += _provinces(ws, spec, tag, notes)
    if not spec.exists:
        notes.append(
            f"{tag} owns no provinces at the start: release it or create it with an event /"
            " decision" + (" (it has cores in the chosen provinces)" if spec.provinces else "")
        )
    return CountryPlan(changes, copies, notes)


_PROVINCE_FILE = re.compile(r"history/provinces/[^/]+/(\d+)(?!\d)")


def _province_files(ws: Workspace) -> dict[int, str]:
    """Province id -> its history file."""
    out: dict[int, str] = {}
    for low, f in sorted(ws.project.files().items()):
        m = _PROVINCE_FILE.match(low)
        if m:
            out.setdefault(int(m[1]), f.rel)
    return out


def _provinces(ws: Workspace, spec: CountrySpec, tag: str, notes: list[str]) -> list[FileChange]:
    """``add_core = TAG`` (and with ``exists`` owner / controller) in the provinces' history."""
    if not spec.provinces:
        return []
    files = _province_files(ws)
    changes: list[FileChange] = []
    taken: dict[str, list[int]] = {}
    later: list[int] = []
    for pid in dict.fromkeys(spec.provinces):
        rel = files.get(pid)
        if rel is None:
            notes.append(f"province {pid} has no history file: add add_core = {tag} yourself")
            continue
        doc = ws.document(rel)
        top = [a for a in doc.items if isinstance(a, Assignment)]
        edits: list[TextEdit] = []
        cores = [a for a in top if a.key_text.lower() == "add_core"]
        has_core = any(
            a.value is not None and a.value.to_text().strip().upper() == tag for a in cores
        )
        if spec.exists:
            for key in ("owner", "controller"):
                node = next((a for a in top if a.key_text.lower() == key), None)
                if node is None:
                    edits.append(insert(doc, doc, [(key, tag)], 0))
                    continue
                old = node.value.to_text().strip().upper() if node.value is not None else ""
                if key == "owner" and old and old != tag:
                    taken.setdefault(old, []).append(pid)
                edits.append(set_value(doc, node, tag))
            if any(
                _DATE.fullmatch(a.key_text)
                and isinstance(a.value, Block)
                and any(i.key_text.lower() == "owner" for i in a.value.assignments())
                for a in top
            ):
                later.append(pid)
        if not has_core:
            anchor = (
                cores[-1]
                if cores
                else next((a for a in top if a.key_text.lower() in ("controller", "owner")), None)
            )
            if anchor is not None:
                edits.append(insert_after(doc, anchor, [("add_core", tag)]))
            else:
                edits.append(insert(doc, doc, [("add_core", tag)], 0))
        if not edits:
            continue
        f = ws.file(rel)
        assert f is not None
        new = apply_edits(doc.text, edits)
        changes.append(
            _change(ws, f.rel, doc.text if f.origin == "mod" else None, new, ws.encoding(f.rel))
        )
    if spec.exists:
        if spec.capital is not None and spec.capital not in spec.provinces:
            notes.append(f"the capital {spec.capital} is not one of {tag}'s provinces")
        for old, pids in sorted(taken.items()):
            notes.append(f"taken from {old}: {', '.join(map(str, pids))} (check {old}'s capital)")
        if later:
            notes.append("dated blocks change the owner later in: " + ", ".join(map(str, later)))
    return changes


def write_copies(copies: list[tuple[Path, Path]]) -> list[Path]:
    """Copy binary files (flags) that do not exist yet; returns the new files."""
    done = []
    for src, dest in copies:
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        done.append(dest)
    return done


def _history(doc: Document, spec: CountrySpec, renamed: dict[str, str]) -> str:
    """The template's history, trimmed and with the new values."""
    edits: list[TextEdit] = []
    overrides = {
        "capital": str(spec.capital) if spec.capital is not None else None,
        "primary_culture": spec.primary_culture,
        "religion": spec.religion,
        "government": spec.government,
        "civilized": None if spec.civilized is None else ("yes" if spec.civilized else "no"),
    }
    present: set[str] = set()
    for item in doc.items:
        if not isinstance(item, Assignment):
            continue
        key = item.key_text.lower()
        if _DATE.fullmatch(key) or key in _DROP:
            edits.append(delete(doc, item))
            continue
        if key == "culture" and spec.cultures is not None:
            edits.append(delete(doc, item))
            continue
        value = overrides.get(key)
        if value is not None:
            present.add(key)
            edits.append(set_value(doc, item, value))
        elif key == "ruling_party" and item.value is not None:
            old = _unquote(item.value.to_text().strip())
            if old in renamed:
                edits.append(set_value(doc, item, renamed[old]))
    text = apply_edits(doc.text, edits)
    nl = newline_of(doc.text)
    extra = [f"{k} = {v}" for k, v in overrides.items() if v is not None and k not in present]
    extra += [f"culture = {c}" for c in spec.cultures or []]
    if extra:
        text = nl.join(extra) + nl + text
    return text.rstrip() + nl


def _history_file(ws: Workspace, tag: str) -> str | None:
    prefix = f"history/countries/{tag.lower()}"
    for low, f in sorted(ws.project.files().items()):
        rest = low[len(prefix) :]
        if low.startswith(prefix) and rest[:1] in (" ", "-", "."):
            return f.rel
    return None


def _change(
    ws: Workspace, rel: str, old: str | None, new: str, enc: Encoding | None = None
) -> FileChange:
    assert ws.project.mod_dir is not None
    if old is not None:
        enc = ws.encoding(rel)
    return FileChange(rel, ws.project.mod_dir / rel, old, new, enc or Encoding.CP1252)


def _unquote(text: str) -> str:
    return text[1:-1] if len(text) >= 2 and text[0] == text[-1] == '"' else text
