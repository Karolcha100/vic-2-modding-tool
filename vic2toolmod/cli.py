"""Command line interface: ``python -m vic2toolmod <command> ...``.

Commands:

* ``parse FILE [--json]`` - show the syntax tree and syntax errors of a file;
* ``roundtrip PATH...`` - check that every script file is read and written back
  byte for byte, and report timing;
* ``errors PATH...`` - list syntax errors of every script file
  (``path:line:column: severity code: message``);
* ``check [MOD] [--game DIR] [--summary] [--vanilla]`` - check a mod on top
  of the game: syntax, schema (triggers, effects, scopes, value types) and
  names (tags, cultures, events, ...);
* ``generate-parties IDEOLOGY [options] [--write]`` - add a party of an
  ideology to many countries (K58); shows a diff, writes only with ``--write``.

When ``roundtrip`` / ``errors`` get no paths, the game and mod folders from
the settings (`vic2toolmod.config`) are used.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from vic2toolmod.config import load_settings
from vic2toolmod.files import iter_script_files
from vic2toolmod.script.parser import parse_file
from vic2toolmod.script.printer import diagnostics_data, outline, to_data
from vic2toolmod.script.roundtrip import check_file


def _default_paths() -> list[Path]:
    settings = load_settings()
    paths = list(settings.mod_dirs)
    if settings.game_dir is not None:
        paths.insert(0, settings.game_dir)
    return paths


def _paths_or_default(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(p) for p in paths]
    found = _default_paths()
    if not found:
        raise SystemExit(
            "no paths given and no game/mod folders configured "
            "(set VIC2_GAME_DIR / VIC2_MOD_DIR or create the settings file)"
        )
    return found


def _cmd_parse(args: argparse.Namespace) -> int:
    doc, encoding = parse_file(args.file)
    if args.json:
        json.dump(
            {
                "encoding": encoding.value,
                "items": to_data(doc),
                "diagnostics": diagnostics_data(doc),
            },
            sys.stdout,
            indent=1,
            ensure_ascii=False,
        )
        print()
    else:
        print(outline(doc))
        for d in doc.diagnostics:
            line, col = doc.position(d.start)
            print(f"{args.file}:{line}:{col}: {d.severity.value} {d.code}: {d.message}")
    return 1 if doc.has_errors else 0


def _cmd_roundtrip(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    files = failed = size = 0
    parse_time = 0.0
    for path in iter_script_files(_paths_or_default(args.paths)):
        result = check_file(path)
        files += 1
        size += result.size
        parse_time += result.parse_seconds
        if not result.ok:
            failed += 1
            print(f"DIFFERENT {path} (first difference at byte {result.first_difference})")
    total = time.perf_counter() - started
    mb = size / 1e6
    print(
        f"{files} files, {mb:.1f} MB: {files - failed} identical, {failed} different; "
        f"parse {parse_time:.1f} s ({mb / parse_time if parse_time else 0:.1f} MB/s), "
        f"total {total:.1f} s"
    )
    return 1 if failed else 0


def _cmd_errors(args: argparse.Namespace) -> int:
    count = files_with_errors = 0
    for path in iter_script_files(_paths_or_default(args.paths)):
        doc, _ = parse_file(path)
        if doc.diagnostics:
            files_with_errors += 1
        for d in doc.diagnostics:
            line, col = doc.position(d.start)
            print(f"{path}:{line}:{col}: {d.severity.value} {d.code}: {d.message}")
            count += 1
    print(f"{count} problems in {files_with_errors} files", file=sys.stderr)
    return 1 if count else 0


def _cmd_check(args: argparse.Namespace) -> int:
    from vic2toolmod.check import check_project, summarise
    from vic2toolmod.project import Project

    settings = load_settings()
    game = args.game or settings.game_dir
    mod = args.mod or (settings.mod_dirs[0] if settings.mod_dirs and not args.vanilla else None)
    if args.vanilla:
        mod = None
    if game is None and mod is None:
        raise SystemExit("no game or mod folder given or configured")
    project = Project.open(game, mod)
    reports = list(check_project(project, only_mod=mod is not None))
    if args.summary:
        print(summarise(reports))
    else:
        for r in reports:
            for d in r.diagnostics:
                line, col = r.document.position(d.start)
                print(f"{r.file.rel}:{line}:{col}: {d.severity.value} {d.code}: {d.message}")
    total = sum(len(r.diagnostics) for r in reports)
    print(f"{total} problems in {sum(1 for r in reports if r.diagnostics)} files", file=sys.stderr)
    return 1 if total else 0


def _cmd_generate_parties(args: argparse.Namespace) -> int:
    from vic2toolmod.changes import diff, write_changes
    from vic2toolmod.generators.parties import CountryFilter, PartySpec, plan_parties
    from vic2toolmod.workspace import Workspace

    settings = load_settings()
    mod = args.mod or (settings.mod_dirs[0] if settings.mod_dirs else None)
    if mod is None:
        raise SystemExit("no mod folder given or configured")
    ws = Workspace.open(args.game or settings.game_dir, mod)
    policies = dict(p.split("=", 1) for p in args.set or [])
    spec = PartySpec(
        args.ideology,
        start_date=args.start,
        end_date=args.end,
        copy_from=tuple(args.copy_from or ()),
        policies=policies,
        loc_text=args.loc,
    )
    where = CountryFilter(
        tags={t.upper() for t in args.tags.split(",")} if args.tags else None,
        culture_groups={g.lower() for g in args.culture_groups.split(",")}
        if args.culture_groups
        else None,
        civilized={"yes": True, "no": False}.get(args.civilized or ""),
    )
    plan = plan_parties(ws, spec, where)
    print(diff(plan.changes))
    print(f"{len(plan.created)} parties planned: {' '.join(plan.created)}", file=sys.stderr)
    for tag, why in sorted(plan.skipped.items()):
        print(f"  skipped {tag}: {why}", file=sys.stderr)
    if args.write and plan.changes:
        backup = write_changes(plan.changes)
        print(f"written; backup of changed files: {backup}", file=sys.stderr)
    elif plan.changes:
        print("dry run - add --write to save", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser (exposed for tests and documentation)."""
    parser = argparse.ArgumentParser(prog="vic2toolmod", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse", help="show the syntax tree and errors of a file")
    p.add_argument("file", type=Path)
    p.add_argument("--json", action="store_true", help="print the tree as JSON")
    p.set_defaults(func=_cmd_parse)

    p = sub.add_parser("roundtrip", help="check lossless read/write of script files")
    p.add_argument("paths", nargs="*", help="files or folders (default: configured folders)")
    p.set_defaults(func=_cmd_roundtrip)

    p = sub.add_parser("check", help="check a mod against the schema and its names")
    p.add_argument("mod", nargs="?", type=Path, help="mod folder (default: configured)")
    p.add_argument("--game", type=Path, help="game folder (default: configured)")
    p.add_argument("--vanilla", action="store_true", help="check the game itself, no mod")
    p.add_argument("--summary", action="store_true", help="counts instead of every problem")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("generate-parties", help="add a party of an ideology to many countries")
    p.add_argument("ideology")
    p.add_argument("--mod", type=Path, help="mod folder (default: configured)")
    p.add_argument("--game", type=Path, help="game folder (default: configured)")
    p.add_argument(
        "--copy-from", action="append", help="ideology to copy policies from (repeatable)"
    )
    p.add_argument(
        "--set", action="append", metavar="ISSUE=OPTION", help="fixed policy (repeatable)"
    )
    p.add_argument("--start", default="1836.1.1", help="start date")
    p.add_argument("--end", default="2000.1.1", help="end date")
    p.add_argument("--tags", help="only these tags, comma separated")
    p.add_argument("--culture-groups", help="only countries of these culture groups")
    p.add_argument("--civilized", choices=["yes", "no"], help="only (un)civilized countries")
    p.add_argument("--loc", help='English name template, e.g. "{adj} Christian Democrats"')
    p.add_argument("--write", action="store_true", help="write the files (with a backup)")
    p.set_defaults(func=_cmd_generate_parties)

    p = sub.add_parser("errors", help="list syntax errors of script files")
    p.add_argument("paths", nargs="*", help="files or folders (default: configured folders)")
    p.set_defaults(func=_cmd_errors)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line interface.

    Args:
        argv: Arguments without the program name; ``sys.argv[1:]`` when omitted.

    Returns:
        Process exit code: 0 when everything is fine, 1 when problems were found.
    """
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code
