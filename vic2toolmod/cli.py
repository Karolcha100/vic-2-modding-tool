"""Command line interface: ``python -m vic2toolmod <command> ...``.

Commands:

* ``parse FILE [--json]`` - show the syntax tree and syntax errors of a file;
* ``roundtrip PATH...`` - check that every script file is read and written back
  byte for byte, and report timing;
* ``errors PATH...`` - list syntax errors of every script file
  (``path:line:column: severity code: message``).

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
