"""Party generator (K58 = D): add a party of a (new) ideology to many countries.

Parties live in ``common/countries/<Country>.txt``::

    party = {
        name = "PRU_liberal"
        start_date = 1830.1.1
        end_date = 1861.1.1
        ideology = liberal
        economic_policy = laissez_faire
        trade_policy = free_trade
        ...
    }

The generator

1. selects countries by rules (tags, culture groups of the primary culture,
   civilized or not; only countries that already have parties);
2. builds a party per country: policies copied from that country's party of a
   similar ideology (``copy_from``), then fixed values (``policies``);
3. adds an English name to the localisation from a template such as
   ``"{adj} Christian Democrats"`` (``{adj}`` = the country's adjective,
   ``{name}`` = its name, ``{tag}``);
4. returns the planned `FileChange` list - preview it with
   `vic2toolmod.changes.diff`, write it with `vic2toolmod.changes.write_changes`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from vic2toolmod.changes import FileChange
from vic2toolmod.edit import apply_edits, insert_after, newline_of
from vic2toolmod.script.cst import Assignment, Block, Document, Scalar
from vic2toolmod.workspace import Workspace

LOC_FILE = "localisation/00_vic2toolmod_parties.csv"


@dataclass
class PartySpec:
    """What party to create.

    Attributes:
        ideology: Ideology of the new party.
        start_date: First day the party exists.
        end_date: Last day.
        copy_from: Ideologies whose party (of the same country) gives the
            starting policies, tried in order.
        policies: Party issue -> option, applied after copying.
        name_key: Localisation key template (``{tag}``, ``{ideology}``).
        loc_text: English name template (``{adj}``, ``{name}``, ``{tag}``);
            ``None`` = do not add localisation.
    """

    ideology: str
    start_date: str = "1836.1.1"
    end_date: str = "2000.1.1"
    copy_from: tuple[str, ...] = ()
    policies: dict[str, str] = field(default_factory=dict)
    name_key: str = "{tag}_{ideology}"
    loc_text: str | None = None


@dataclass
class CountryFilter:
    """Which countries get the party (all conditions must hold).

    Attributes:
        tags: Only these tags (``None`` = any).
        culture_groups: Primary culture in one of these groups (``None`` = any).
        civilized: Only civilized (``True``) / uncivilized (``False``) countries.
        skip_existing: Skip countries that already have a party of the ideology.
    """

    tags: set[str] | None = None
    culture_groups: set[str] | None = None
    civilized: bool | None = None
    skip_existing: bool = True


@dataclass
class Plan:
    """Result of planning: file changes plus what happened to each country."""

    changes: list[FileChange]
    created: list[str]
    skipped: dict[str, str]


def _country_files(ws: Workspace) -> dict[str, str]:
    """Tag -> relative path of its ``common/countries/...`` file."""
    out = {}
    doc = ws.document("common/countries.txt")
    for item in doc.items:
        if isinstance(item, Assignment) and isinstance(item.value, Scalar):
            out[item.key_text.upper()] = "common/" + item.value.value.replace("\\", "/")
    return out


def _history(ws: Workspace) -> dict[str, Document]:
    """Tag -> parsed ``history/countries/TAG - Name.txt``."""
    out = {}
    for f in ws.project.glob("history/countries/*.txt"):
        tag = Path(f.rel).name[:3].upper()
        out[tag] = ws.document(f.rel)
    return out


def _culture_groups(ws: Workspace) -> dict[str, str]:
    """Culture -> its group."""
    out = {}
    doc = ws.document("common/cultures.txt")
    for group in doc.items:
        if isinstance(group, Assignment) and isinstance(group.value, Block):
            for c in group.value.items:
                if isinstance(c, Assignment) and isinstance(c.value, Block):
                    out[c.key_text.lower()] = group.key_text.lower()
    return out


def _scalar(block: Document | Block, key: str) -> str | None:
    a = block.find(key)
    return a.value.value if a is not None and isinstance(a.value, Scalar) else None


def _parties(doc: Document) -> list[Block]:
    return [a.value for a in doc.assignments("party") if isinstance(a.value, Block)]


def party_issues(ws: Workspace) -> list[str]:
    """Party issues of the mod (children of ``party_issues`` in ``common/issues.txt``)."""
    doc = ws.document("common/issues.txt")
    pi = doc.find("party_issues")
    if pi is None or not isinstance(pi.value, Block):
        return []
    return [a.key_text for a in pi.value.assignments() if isinstance(a.value, Block)]


def plan_parties(ws: Workspace, spec: PartySpec, where: CountryFilter) -> Plan:
    """Plan adding the party to every selected country (nothing is written)."""
    if ws.project.mod_dir is None:
        raise ValueError("a mod folder is needed to write changes")
    issues = party_issues(ws)
    files = _country_files(ws)
    history = _history(ws)
    groups = _culture_groups(ws)
    loc = ws.registries().localisation
    changes: list[FileChange] = []
    created: list[str] = []
    skipped: dict[str, str] = {}
    loc_lines: list[str] = []
    for tag, rel in sorted(files.items()):
        if where.tags is not None and tag not in where.tags:
            continue
        hist = history.get(tag)
        if where.culture_groups is not None:
            culture = _scalar(hist, "primary_culture") if hist else None
            if culture is None or groups.get(culture.lower()) not in where.culture_groups:
                continue
        if where.civilized is not None:
            civ = (_scalar(hist, "civilized") if hist else None) == "yes"
            if civ != where.civilized:
                continue
        if ws.file(rel) is None:
            skipped[tag] = f"{rel} does not exist"
            continue
        doc = ws.document(rel)
        parties = _parties(doc)
        if not parties:
            skipped[tag] = "has no parties"
            continue
        if where.skip_existing and any(
            (_scalar(p, "ideology") or "").lower() == spec.ideology.lower() for p in parties
        ):
            skipped[tag] = f"already has a {spec.ideology} party"
            continue
        policies: dict[str, str] = {}
        for ideology in spec.copy_from:
            source = next(
                (p for p in parties if (_scalar(p, "ideology") or "").lower() == ideology.lower()),
                None,
            )
            if source is not None:
                policies = {i: v for i in issues if (v := _scalar(source, i)) is not None}
                break
        policies.update(spec.policies)
        missing = [i for i in issues if i not in policies]
        if missing:
            skipped[tag] = "no value for " + ", ".join(missing)
            continue
        key = spec.name_key.format(tag=tag, ideology=spec.ideology)
        items = [
            ("name", f'"{key}"'),
            ("start_date", spec.start_date),
            ("end_date", spec.end_date),
            ("ideology", spec.ideology),
            *((i, policies[i]) for i in issues),
        ]
        last = [a for a in doc.assignments("party")][-1]
        edit = insert_after(doc, last, [("party", items)])
        new_text = apply_edits(doc.text, [edit])
        f = ws.file(rel)
        assert f is not None
        target = ws.project.mod_dir / f.rel
        changes.append(FileChange(f.rel, target, doc.text, new_text, ws.encoding(rel)))
        created.append(tag)
        if spec.loc_text is not None and (loc is None or key not in loc):
            adj_entry = loc.get(f"{tag}_ADJ") if loc else None
            name_entry = loc.get(tag) if loc else None
            adj = adj_entry.text() if adj_entry else tag
            name = name_entry.text() if name_entry else tag
            text = spec.loc_text.format(adj=adj, name=name, tag=tag)
            loc_lines.append(f"{key};{text};{text};{text};;{text};;;;;;;;;x")
    if loc_lines:
        changes.append(_loc_change(ws, loc_lines))
    return Plan(changes, created, skipped)


def _loc_change(ws: Workspace, lines: list[str]) -> FileChange:
    assert ws.project.mod_dir is not None
    path = ws.project.mod_dir / LOC_FILE
    old = path.read_bytes().decode("cp1252", errors="replace") if path.exists() else None
    nl = newline_of(old) if old else "\r\n"
    base = old if old is not None else ""
    if base and not base.endswith(("\n", "\r")):
        base += nl
    return FileChange(LOC_FILE, path, old, base + nl.join(lines) + nl)
