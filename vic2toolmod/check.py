"""Check a whole project (vanilla + mod): syntax, schema and names.

Per-project settings (K21 = B, "ignore in this project") live in
``vic2toolmod.toml`` in the mod folder (the game ignores the file)::

    ignore_codes = ["schema.wrong-scope"]          # whole diagnostic codes
    ignore_messages = ["unknown trigger 'pop_unemployment'"]   # message substrings
"""

from __future__ import annotations

import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from vic2toolmod.project.layout import Project, ProjectFile
from vic2toolmod.schema.model import Schema
from vic2toolmod.script.cst import Document
from vic2toolmod.script.diagnostics import Diagnostic


@dataclass(frozen=True)
class FileReport:
    """Result for one file.

    Attributes:
        file: The file.
        document: Parsed document.
        file_type: Name of the matching file type (``None`` = not checked against the schema).
        diagnostics: Syntax and schema diagnostics, sorted.
    """

    file: ProjectFile
    document: Document
    file_type: str | None
    diagnostics: list[Diagnostic]


def check_project(
    project: Project,
    *,
    schema: Schema | None = None,
    only_mod: bool = True,
) -> list[FileReport]:
    """Check every script file of a project (see `vic2toolmod.workspace.Workspace.check`).

    Args:
        project: Game + mod.
        schema: Schema to use (default: the packaged one).
        only_mod: Report only files that come from the mod (vanilla files are
            still read to know their names).
    """
    from vic2toolmod.workspace import Workspace

    return Workspace(project, schema).check(only_mod=only_mod)


@dataclass(frozen=True)
class IgnoreRules:
    """Diagnostics the author chose to ignore in a project."""

    codes: frozenset[str] = frozenset()
    messages: tuple[str, ...] = ()

    def ignored(self, d: Diagnostic) -> bool:
        """Whether a diagnostic is ignored."""
        return d.code in self.codes or any(m in d.message for m in self.messages)


def load_ignore_rules(mod_dir: Path | None) -> IgnoreRules:
    """Read ``vic2toolmod.toml`` from a mod folder (missing file = nothing ignored)."""
    if mod_dir is None:
        return IgnoreRules()
    path = mod_dir / "vic2toolmod.toml"
    if not path.is_file():
        return IgnoreRules()
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return IgnoreRules(
        frozenset(str(c) for c in data.get("ignore_codes", [])),
        tuple(str(m) for m in data.get("ignore_messages", [])),
    )


def summarise(reports: list[FileReport], top: int = 40) -> str:
    """Counts of diagnostics by code and message, plus files without a file type."""
    by_message: Counter[tuple[str, str]] = Counter()
    untyped: Counter[str] = Counter()
    for r in reports:
        if r.file_type is None:
            parts = r.file.rel.split("/")
            untyped["/".join(parts[:2]) if len(parts) > 2 else r.file.rel] += 1
        for d in r.diagnostics:
            by_message[(d.code, d.message)] += 1
    lines = [f"{len(reports)} files, {sum(by_message.values())} problems"]
    codes: Counter[str] = Counter()
    for (code, _), n in by_message.items():
        codes[code] += n
    lines += [f"  {n:6}  {code}" for code, n in codes.most_common()]
    lines.append("most frequent:")
    lines += [f"  {n:6}  {code}: {msg}" for (code, msg), n in by_message.most_common(top)]
    if untyped:
        lines.append("files without a file type (not checked against the schema):")
        lines += [f"  {n:6}  {k}" for k, n in untyped.most_common()]
    return "\n".join(lines)
