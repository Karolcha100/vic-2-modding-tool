"""Overviews of a mod: what it changes in vanilla (K6 H) and statistics (K6 I)."""

from __future__ import annotations

import difflib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from vic2toolmod import textio
from vic2toolmod.project.layout import Project
from vic2toolmod.script.cst import Assignment, Block, Scalar
from vic2toolmod.workspace import Workspace


@dataclass(frozen=True)
class FileDifference:
    """How a mod file relates to vanilla.

    Attributes:
        rel: Relative path.
        status: ``new`` (not in vanilla), ``changed``, ``same`` (identical copy)
            or ``hidden`` (vanilla file hidden by ``replace_path``).
        added: Lines added compared to vanilla.
        removed: Lines removed compared to vanilla.
    """

    rel: str
    status: str
    added: int = 0
    removed: int = 0


def _text(path: Path) -> str:
    return textio.decode(path.read_bytes())[0]


def compare_with_vanilla(project: Project, text_only: bool = True) -> list[FileDifference]:
    """Every mod file compared with the vanilla file of the same path.

    Args:
        project: Game + mod.
        text_only: Compare only text files (``.txt``, ``.csv``, ``.gui`` ...);
            binary files (maps, graphics) get ``changed`` / ``same`` by bytes.
    """
    if project.game_dir is None or project.mod_dir is None:
        return []
    vanilla = Project(project.game_dir).files()
    out = []
    for low, f in sorted(project.files().items()):
        if f.origin != "mod":
            continue
        base = vanilla.get(low)
        if base is None:
            out.append(FileDifference(f.rel, "new"))
            continue
        a, b = base.path.read_bytes(), f.path.read_bytes()
        if a == b:
            out.append(FileDifference(f.rel, "same"))
            continue
        if text_only and low.endswith((".txt", ".csv", ".gui", ".gfx", ".lua", ".mod", ".map")):
            old = _text(base.path).splitlines()
            new = _text(f.path).splitlines()
            added = removed = 0
            for line in difflib.unified_diff(old, new, lineterm="", n=0):
                if line.startswith("+") and not line.startswith("+++"):
                    added += 1
                elif line.startswith("-") and not line.startswith("---"):
                    removed += 1
            out.append(FileDifference(f.rel, "changed", added, removed))
        else:
            out.append(FileDifference(f.rel, "changed"))
    hidden = {p.lower() for p in project.replace_paths}
    for low, f in sorted(vanilla.items()):
        if str(Path(low).parent) in hidden and low not in project.files():
            out.append(FileDifference(f.rel, "hidden"))
    return out


def vanilla_diff(project: Project, rel: str, context: int = 3) -> str:
    """Unified diff of one file: vanilla version -> mod version."""
    assert project.game_dir is not None
    base = Project(project.game_dir).file(rel)
    mod = project.file(rel)
    old = _text(base.path).splitlines(keepends=True) if base else []
    new = _text(mod.path).splitlines(keepends=True) if mod else []
    return "".join(difflib.unified_diff(old, new, f"vanilla/{rel}", f"mod/{rel}", n=context))


@dataclass
class PopStats:
    """Pops at the start (``history/pops/<date>/``).

    Attributes:
        date: The pops folder used (e.g. ``1836.1.1``).
        total: Sum of pop sizes.
        by_culture, by_religion, by_type: Sizes per culture / religion / pop type.
        by_owner: Sizes per owner tag (from ``history/provinces``).
    """

    date: str
    total: float
    by_culture: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    by_religion: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    by_type: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    by_owner: dict[str, float] = field(default_factory=lambda: defaultdict(float))


def pop_stats(ws: Workspace, date: str | None = None) -> PopStats:
    """Sum the pops of the start date (the earliest ``history/pops`` folder by default)."""
    folders = sorted({f.rel.split("/")[2] for f in ws.project.glob("history/pops/*/*.txt")})
    if not folders:
        return PopStats("", 0)
    date = date or folders[0]
    owners: dict[str, str] = {}
    for f in ws.project.glob("history/provinces/*/*.txt"):
        pid = Path(f.rel).name.split(" ", 1)[0].split("-", 1)[0].strip()
        owner = ws.document(f.rel).find("owner")
        if owner is not None and isinstance(owner.value, Scalar):
            owners[pid] = owner.value.value.upper()
    stats = PopStats(date, 0)
    for f in ws.project.glob(f"history/pops/{date}/*.txt"):
        for prov in ws.document(f.rel).items:
            if not (isinstance(prov, Assignment) and isinstance(prov.value, Block)):
                continue
            for pop in prov.value.items:
                if not (isinstance(pop, Assignment) and isinstance(pop.value, Block)):
                    continue
                size_a = pop.value.find("size")
                try:
                    size = (
                        float(size_a.value.value)
                        if size_a and isinstance(size_a.value, Scalar)
                        else 0
                    )
                except ValueError:
                    continue
                culture = pop.value.find("culture")
                religion = pop.value.find("religion")
                stats.total += size
                stats.by_type[pop.key_text.lower()] += size
                if culture and isinstance(culture.value, Scalar):
                    stats.by_culture[culture.value.value.lower()] += size
                if religion and isinstance(religion.value, Scalar):
                    stats.by_religion[religion.value.value.lower()] += size
                stats.by_owner[owners.get(prov.key_text, "?")] += size
    return stats
