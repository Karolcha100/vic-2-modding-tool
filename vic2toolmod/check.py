"""Check a whole project (vanilla + mod): syntax, schema and names."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

from vic2toolmod.project.layout import Project, ProjectFile
from vic2toolmod.project.registries import Registries, build_registries
from vic2toolmod.schema.loader import default_schema
from vic2toolmod.schema.model import Schema
from vic2toolmod.schema.validator import Validator, file_type_for
from vic2toolmod.script.cst import Document
from vic2toolmod.script.diagnostics import Diagnostic
from vic2toolmod.script.parser import parse_file


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
    registries: Registries | None = None,
    only_mod: bool = True,
) -> Iterator[FileReport]:
    """Check every script file of a project.

    Args:
        project: Game + mod.
        schema: Schema to use (default: the packaged one).
        registries: Names (default: built from the project).
        only_mod: Report only files that come from the mod (vanilla files are
            still read to know their names).
    """
    schema = schema or default_schema()
    cache: dict[str, Document] = {}
    registries = registries or build_registries(project, cache)
    validator = Validator(schema, registries.has)
    for low, f in sorted(project.files().items()):
        if only_mod and project.mod_dir is not None and f.origin != "mod":
            continue
        if not low.endswith((".txt", ".gfx", ".gui")):
            continue
        doc = cache.get(f.rel)
        if doc is None:
            doc, _ = parse_file(f.path)
        ft = file_type_for(f.rel, schema)
        diags = list(doc.diagnostics)
        if ft is not None:
            diags += validator.validate(doc, ft.rule, ft.scope)
            diags.sort(key=lambda d: d.start)
        yield FileReport(f, doc, ft.name if ft else None, diags)


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
