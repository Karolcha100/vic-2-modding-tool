"""Meta relations between pops (T010, K89 = B, K90 = C).

A *rule* says once what many pop files should contain, e.g. "with conscription
every pop with ``strata = poor`` promotes more to soldiers". The game has no
rules or includes, so the tool writes the rule's modifiers into every matching
pop file, between marker comments it can find again::

    promote_to = {
        soldiers = {
            ...
            # vic2toolmod meta: conscription_poor
            modifier = { factor = 2 country = { military_service = two_year_draft } }
            # vic2toolmod meta end: conscription_poor
        }
    }

Rules live in the mod, one file each, in ``vic2toolmod/meta/<name>.txt``
(a folder the game does not read; K89 = B), in script syntax::

    name = conscription_poor
    description = "Draft makes poor pops soldiers"
    block = promote_to           # see BLOCKS
    target = soldiers            # promote_to: pop type; issues: issue option; ideologies: ideology
    strata = { poor }            # which pop types: by strata ...
    pop_types = { }              # ... and / or by name (empty both = all)
    group = no                   # yes: the modifiers inside one group = { } (K90 note)
    modifiers = {
        modifier = { factor = 2 country = { military_service = two_year_draft } }
    }

Blocks (K90 = C): in ``poptypes/<pop>.txt`` ``promote_to``, ``issues`` and
``ideologies`` (with a target), ``migration_target`` and
``country_migration_target``; in ``common/pop_types.txt`` the chances
(``promotion_chance`` …, no pop filter: one file).

`plan` gives the file changes of all rules (insert, update, remove copies
that no longer match, remove copies of deleted rules); copies changed by hand
are reported (`Plan.edited`) and overwritten only when asked (``force``).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from vic2toolmod.changes import FileChange
from vic2toolmod.edit import newline_of
from vic2toolmod.script.cst import Assignment, Block, Document, Scalar
from vic2toolmod.script.parser import parse_text
from vic2toolmod.textio import Encoding, decode
from vic2toolmod.workspace import Workspace

META_DIR = "vic2toolmod/meta"
#: Blocks of poptypes/<pop>.txt; True = needs a target (a block inside the block).
POP_BLOCKS = {
    "promote_to": True,
    "issues": True,
    "ideologies": True,
    "migration_target": False,
    "country_migration_target": False,
}
#: Blocks of common/pop_types.txt (one file, no pop filter).
CHANCE_BLOCKS = (
    "promotion_chance",
    "demotion_chance",
    "migration_chance",
    "colonialmigration_chance",
    "emigration_chance",
    "assimilation_chance",
    "conversion_chance",
)
POP_TYPES_FILE = "common/pop_types.txt"
STRATA = ("poor", "middle", "rich")
_NAME = re.compile(r"[A-Za-z0-9_]+")
_START = "# vic2toolmod meta: "
_END = "# vic2toolmod meta end: "
_REGION = re.compile(
    r"^(?P<indent>[ \t]*)# vic2toolmod meta: (?P<name>[A-Za-z0-9_]+)"
    r"(?: (?P<sum>[0-9a-f]{8}))?[ \t]*\r?\n"
    r"(?P<body>.*?)"
    r"^[ \t]*# vic2toolmod meta end: (?P=name)[ \t]*(?:\r\n|\n|\r|$)",
    re.M | re.S,
)


class MetaError(ValueError):
    """A rule that cannot be used (bad name, block, target, modifiers)."""


@dataclass
class Rule:
    """One meta relation (see the module docstring)."""

    name: str
    block: str
    target: str = ""
    description: str = ""
    strata: list[str] = field(default_factory=list)
    pop_types: list[str] = field(default_factory=list)
    group: bool = False
    modifiers: str = ""
    """The modifiers' code, as written (``modifier = { … }`` …)."""

    def check(self) -> None:
        """Raise `MetaError` for a rule that cannot be applied."""
        if not _NAME.fullmatch(self.name):
            raise MetaError("the name may only have letters, digits and _")
        if self.block not in POP_BLOCKS and self.block not in CHANCE_BLOCKS:
            raise MetaError(f"unknown block {self.block!r}")
        if POP_BLOCKS.get(self.block) and not _NAME.fullmatch(self.target):
            raise MetaError(f"{self.block} needs a target (a name)")
        bad = [s for s in self.strata if s not in STRATA]
        if bad:
            raise MetaError(f"unknown strata: {', '.join(bad)}")
        doc = parse_text(self.modifiers)
        if any(d.severity.name == "ERROR" for d in doc.diagnostics):
            raise MetaError("the modifiers' code has syntax errors")
        if not any(isinstance(i, Assignment) for i in doc.items):
            raise MetaError("the rule has no modifiers")

    def to_text(self) -> str:
        """The rule file."""
        body = "\n".join("\t" + line if line.strip() else "" for line in _lines(self.modifiers))
        out = [
            "# Meta relation of vic2toolmod (T010): edit it in Analyses -> Meta relations.",
            f"name = {self.name}",
        ]
        if self.description:
            out.append(f'description = "{self.description.replace(chr(34), chr(39))}"')
        out.append(f"block = {self.block}")
        if self.target:
            out.append(f"target = {self.target}")
        out.append(f"strata = {{ {' '.join(self.strata)} }}" if self.strata else "strata = { }")
        out.append(
            f"pop_types = {{ {' '.join(self.pop_types)} }}" if self.pop_types else "pop_types = { }"
        )
        out.append(f"group = {'yes' if self.group else 'no'}")
        out.append("modifiers = {\n" + body + "\n}")
        return "\n".join(out) + "\n"


def _lines(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n").split("\n")
    # remove the common indentation, so the code can be indented anew
    indents = [len(x) - len(x.lstrip(" \t")) for x in lines if x.strip()]
    cut = min(indents) if indents else 0
    return [x[cut:].rstrip() for x in lines]


def parse_rule(text: str, fallback_name: str = "") -> Rule:
    """Read a rule file."""
    doc = parse_text(text)

    def scalar(key: str) -> str:
        a = doc.find(key)
        return a.value.value if a is not None and isinstance(a.value, Scalar) else ""

    def words(key: str) -> list[str]:
        a = doc.find(key)
        if a is None or not isinstance(a.value, Block):
            return []
        return [i.value for i in a.value.items if isinstance(i, Scalar)]

    mods = doc.find("modifiers")
    code = ""
    if mods is not None and isinstance(mods.value, Block) and mods.value.rbrace is not None:
        code = doc.text[mods.value.lbrace.end : mods.value.rbrace.start]
    return Rule(
        name=scalar("name") or fallback_name,
        block=scalar("block"),
        target=scalar("target"),
        description=scalar("description"),
        strata=[s.lower() for s in words("strata")],
        pop_types=words("pop_types"),
        group=scalar("group").lower() == "yes",
        modifiers="\n".join(_lines(code)),
    )


def rules(ws: Workspace) -> list[Rule]:
    """The mod's rules (by name)."""
    mod = ws.project.mod_dir
    if mod is None or not (mod / META_DIR).is_dir():
        return []
    out = []
    for path in sorted((mod / META_DIR).glob("*.txt")):
        out.append(parse_rule(decode(path.read_bytes())[0], path.stem))
    return sorted(out, key=lambda r: r.name.lower())


def pop_types(ws: Workspace) -> dict[str, str]:
    """Pop type -> its strata (``poptypes/*.txt``)."""
    out = {}
    for f in ws.script_files():
        low = f.rel.lower()
        if low.startswith("poptypes/") and low.endswith(".txt"):
            a = ws.document(f.rel).find("strata")
            out[Path(f.rel).stem] = (
                a.value.value.lower() if a and isinstance(a.value, Scalar) else ""
            )
    return out


def matches(rule: Rule, pops: dict[str, str]) -> list[str]:
    """The pop types a rule goes into (empty strata and list: all)."""
    if rule.block in CHANCE_BLOCKS:
        return []
    wanted = {p.lower() for p in rule.pop_types}
    return sorted(
        p
        for p, strata in pops.items()
        if ((not rule.strata and not wanted) or strata in rule.strata or p.lower() in wanted)
        # a pop does not promote to itself
        and not (rule.block == "promote_to" and p.lower() == rule.target.lower())
    )


def _sum(body: str) -> str:
    """Short checksum of a copy's body (spaces do not count)."""
    return hashlib.sha1(_flat(body).encode(), usedforsecurity=False).hexdigest()[:8]


def render(rule: Rule, indent: str, nl: str) -> str:
    """The rule's copy in a file: markers (with a checksum of the body) and the modifiers.

    The checksum lets `plan` tell a copy the tool wrote from one changed by hand.
    """
    inner = indent + "\t" if rule.group else indent
    body = [inner + line if line.strip() else "" for line in _lines(rule.modifiers)]
    if rule.group:
        body = [indent + "group = {", *body, indent + "}"]
    text = nl.join(body)
    lines = [f"{indent}{_START}{rule.name} {_sum(text)}", *body, indent + _END + rule.name]
    return nl.join(lines) + nl


@dataclass
class Copy:
    """A copy of a rule found in a file."""

    name: str
    start: int
    end: int
    indent: str
    body: str
    checksum: str

    @property
    def edited(self) -> bool:
        """The body is not what the tool wrote (its checksum does not match)."""
        return _sum(self.body.rstrip("\r\n")) != self.checksum


def copies(text: str) -> list[Copy]:
    """Every rule copy in a file's text."""
    return [
        Copy(m["name"], m.start(), m.end(), m["indent"], m["body"], m["sum"] or "")
        for m in _REGION.finditer(text)
    ]


def _flat(text: str) -> str:
    return " ".join(text.split())


@dataclass
class Plan:
    """Changes that make the files match the rules.

    Attributes:
        changes: File changes.
        added / updated / removed: ``(rule, file)`` pairs.
        edited: Copies changed by hand (kept unless ``force``).
        missing: ``(rule, file, why)``: where a copy cannot go (no such block …).
    """

    changes: list[FileChange] = field(default_factory=list)
    added: list[tuple[str, str]] = field(default_factory=list)
    updated: list[tuple[str, str]] = field(default_factory=list)
    removed: list[tuple[str, str]] = field(default_factory=list)
    edited: list[tuple[str, str]] = field(default_factory=list)
    missing: list[tuple[str, str, str]] = field(default_factory=list)


def _block_path(doc: Document, keys: list[str]) -> Assignment | None:
    items = doc.items
    found: Assignment | None = None
    for key in keys:
        found = next(
            (
                i
                for i in items
                if isinstance(i, Assignment)
                and i.key_text.lower() == key.lower()
                and isinstance(i.value, Block)
            ),
            None,
        )
        if found is None:
            return None
        assert isinstance(found.value, Block)
        items = found.value.items
    return found


def plan(ws: Workspace, all_rules: list[Rule] | None = None, force: bool = False) -> Plan:
    """Changes that bring every pop file in line with the rules (nothing is written)."""
    mod = ws.project.mod_dir
    if mod is None:
        raise MetaError("the game's own files are read-only: open a mod")
    rule_list = rules(ws) if all_rules is None else all_rules
    by_name = {r.name: r for r in rule_list}
    pops = pop_types(ws)
    result = Plan()
    # which rule goes into which file
    wanted: dict[str, list[Rule]] = {}
    for r in rule_list:
        files = (
            [POP_TYPES_FILE]
            if r.block in CHANCE_BLOCKS
            else [f"poptypes/{p}.txt" for p in matches(r, pops)]
        )
        for rel in files:
            wanted.setdefault(rel.lower(), []).append(r)
    candidates = {f"poptypes/{p}.txt".lower(): f"poptypes/{p}.txt" for p in pops}
    candidates[POP_TYPES_FILE] = POP_TYPES_FILE
    for low, rel in sorted(candidates.items()):
        f = ws.file(rel)
        if f is None:
            continue
        rel = f.rel
        text = ws.document(rel).text
        new = text
        nl = newline_of(text)
        found = {c.name: c for c in copies(text)}
        # 1. existing copies: update, keep (edited by hand) or remove
        for c in sorted(found.values(), key=lambda c: -c.start):
            rule = by_name.get(c.name)
            keep = rule is not None and any(r.name == c.name for r in wanted.get(low, []))
            if not keep:
                new = new[: c.start] + new[c.end :]
                result.removed.append((c.name, rel))
                continue
            assert rule is not None
            fresh = render(rule, c.indent, nl)
            if _flat(new[c.start : c.end]) == _flat(fresh):
                continue
            if not force and c.edited:
                result.edited.append((c.name, rel))
                continue
            new = new[: c.start] + fresh + new[c.end :]
            result.updated.append((c.name, rel))
        # 2. new copies
        for rule in wanted.get(low, []):
            if rule.name in found:
                continue
            new, why = _insert(new, rule, nl)
            if why:
                result.missing.append((rule.name, rel, why))
            else:
                result.added.append((rule.name, rel))
        if new != text:
            _, encoding = decode(f.path.read_bytes()) if f.path.exists() else ("", Encoding.CP1252)
            old = text if f.origin == "mod" else None
            result.changes.append(FileChange(rel, mod / rel, old, new, encoding))
    return result


def _insert(text: str, rule: Rule, nl: str) -> tuple[str, str]:
    """Add a copy at the end of the rule's block; ``(new text, "")`` or ``(text, why not)``."""
    doc = parse_text(text)
    keys = [rule.block] + ([rule.target] if POP_BLOCKS.get(rule.block) else [])
    parent = _block_path(doc, keys[:1])
    if parent is None:
        return text, f"no {rule.block} = {{ }} block"
    if len(keys) == 2:
        block = _block_path(doc, keys)
        if block is None:  # the target is new for this pop: make its block
            assert isinstance(parent.value, Block) and parent.value.rbrace is not None
            base = "0" if rule.block == "promote_to" else "1"
            depth = _depth(text, parent.start) + 1
            ind = "\t" * depth
            copy = render(rule, ind + "\t", nl)
            piece = f"{ind}{rule.target} = {{{nl}{ind}\tfactor = {base}{nl}{copy}{ind}}}{nl}"
            return _before_brace(text, parent.value.rbrace.start, piece, depth - 1, nl), ""
        parent = block
    assert isinstance(parent.value, Block) and parent.value.rbrace is not None
    depth = _depth(text, parent.start) + 1
    return _before_brace(
        text, parent.value.rbrace.start, render(rule, "\t" * depth, nl), depth - 1, nl
    ), ""


def _depth(text: str, offset: int) -> int:
    """Indentation (in tabs, 4 spaces = 1) of the line at ``offset``."""
    start = max(text.rfind("\n", 0, offset), text.rfind("\r", 0, offset)) + 1
    lead = text[start:offset]
    lead = lead[: len(lead) - len(lead.lstrip(" \t"))]
    return lead.count("\t") + lead.count(" ") // 4


def _before_brace(text: str, brace: int, piece: str, brace_depth: int, nl: str) -> str:
    """Put whole lines ``piece`` just before the ``}`` at ``brace``."""
    line_start = max(text.rfind("\n", 0, brace), text.rfind("\r", 0, brace)) + 1
    if not text[line_start:brace].strip():  # "}" on its own line
        return text[:line_start] + piece + text[line_start:]
    return text[:brace] + nl + piece + "\t" * brace_depth + text[brace:]


def save_rule(ws: Workspace, rule: Rule) -> FileChange:
    """The change that writes a rule file."""
    rule.check()
    mod = ws.project.mod_dir
    if mod is None:
        raise MetaError("open a mod to keep rules in it")
    path = mod / META_DIR / f"{rule.name}.txt"
    old = decode(path.read_bytes())[0] if path.exists() else None
    return FileChange(f"{META_DIR}/{rule.name}.txt", path, old, rule.to_text(), Encoding.CP1252)
