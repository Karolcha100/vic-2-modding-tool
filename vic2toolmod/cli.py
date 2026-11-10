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
* ``diff-vanilla [--file REL]`` - what the mod changes in vanilla (K6 H);
* ``stats`` - pops at the start by owner, culture, religion, type (K6 I);
* ``events [--json FILE]`` - event chains (K6 C): events fired but missing,
  triggered-only events nothing fires; ``--json`` saves the graph;
* ``poptypes [--json FILE] [--registry R]`` - which reforms / techs change
  which pop weights (K59); ``--json`` saves the promotion graph;
* ``gui [--port N] [--no-browser] [--stay]`` - start the local server for the GUI
  (127.0.0.1 only, with a random token in the address). It stops when the
  browser window is closed (``--stay``: keeps running); a second plain
  ``gui`` opens a tab on the running server, or replaces it when the tool's
  code changed (`vic2toolmod.server.lifecycle`);
* ``install-desktop`` - add a "vic2toolmod" shortcut to the Linux application menu;
* ``generate-parties IDEOLOGY [options] [--write]`` - add a party of an
  ideology to many countries (K58); shows a diff, writes only with ``--write``;
* ``run-script SCRIPT [-p NAME=VALUE ...] [--write]`` - run a light Python
  script on the mod (T007, `vic2toolmod.pyscripts`); shows its output and a
  diff, writes only with ``--write``; ``run-script --list`` lists the scripts.

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
from typing import TYPE_CHECKING

from vic2toolmod.config import load_settings
from vic2toolmod.files import iter_script_files
from vic2toolmod.script.parser import parse_file
from vic2toolmod.script.printer import diagnostics_data, outline, to_data
from vic2toolmod.script.roundtrip import check_file

if TYPE_CHECKING:
    from vic2toolmod.workspace import Workspace


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
    problems = [d for r in reports for d in r.diagnostics if d.severity != "info"]
    infos = sum(1 for r in reports for d in r.diagnostics if d.severity == "info")
    files = sum(1 for r in reports if any(d.severity != "info" for d in r.diagnostics))
    print(f"{len(problems)} problems in {files} files (+ {infos} notes)", file=sys.stderr)
    return 1 if problems else 0


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


def _cmd_run_script(args: argparse.Namespace) -> int:
    from vic2toolmod.changes import diff, write_changes
    from vic2toolmod.pyscripts import ScriptError, get_script, list_scripts, run, user_dir

    if args.list or not args.script:
        for s in list_scripts():
            fields = " ".join(f"{p.name}={p.default!r}" if p.default else p.name for p in s.params)
            print(f"{s.id}: {s.name}" + (f"  [{fields}]" if fields else ""))
            if s.description:
                print(f"    {s.description}")
        print(f"(your own scripts: {user_dir()})", file=sys.stderr)
        return 0
    try:
        script = get_script(args.script)
        given = dict(p.split("=", 1) for p in args.param or [])
        ws = _workspace(args)
        result = run(ws, script, given)
    except (ScriptError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc
    if result.output:
        print(result.output, end="" if result.output.endswith("\n") else "\n", file=sys.stderr)
    if result.error:
        print(result.error, file=sys.stderr)
        print("the script failed - nothing written", file=sys.stderr)
        return 1
    print(diff(result.changes), end="")
    if args.write and result.changes:
        backup = write_changes(result.changes)
        print(f"{len(result.changes)} file(s) written; backup: {backup}", file=sys.stderr)
    elif result.changes:
        print(f"dry run ({len(result.changes)} file(s)) - add --write to save", file=sys.stderr)
    return 0


def _workspace(args: argparse.Namespace) -> Workspace:
    from vic2toolmod.workspace import Workspace

    settings = load_settings()
    mod = args.mod or (settings.mod_dirs[0] if settings.mod_dirs else None)
    return Workspace.open(args.game or settings.game_dir, mod)


def _cmd_diff_vanilla(args: argparse.Namespace) -> int:
    from vic2toolmod.analysis.overview import compare_with_vanilla, vanilla_diff

    ws = _workspace(args)
    if args.file:
        print(vanilla_diff(ws.project, args.file))
        return 0
    diffs = compare_with_vanilla(ws.project)
    for status in ("new", "changed", "same", "hidden"):
        group = [d for d in diffs if d.status == status]
        print(f"{status}: {len(group)} files")
        if status in ("changed",):
            for d in sorted(group, key=lambda d: -(d.added + d.removed))[: args.top]:
                print(f"    {d.rel}: +{d.added} -{d.removed}")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    from vic2toolmod.analysis.overview import pop_stats

    s = pop_stats(_workspace(args))
    print(f"pops in history/pops/{s.date}: total size {s.total:,.0f}")
    for title, table in (
        ("owner", s.by_owner),
        ("culture", s.by_culture),
        ("religion", s.by_religion),
        ("type", s.by_type),
    ):
        print(f"by {title}:")
        for name, size in sorted(table.items(), key=lambda kv: -kv[1])[: args.top]:
            print(f"    {name:<24} {size:>14,.0f}  {100 * size / s.total:5.1f}%")
    return 0


def _cmd_events(args: argparse.Namespace) -> int:
    from vic2toolmod.analysis.events import event_graph
    from vic2toolmod.workspace import Workspace

    settings = load_settings()
    mod = args.mod or (settings.mod_dirs[0] if settings.mod_dirs else None)
    graph = event_graph(Workspace.open(args.game or settings.game_dir, mod))
    if args.json:
        args.json.write_text(json.dumps(graph, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"event graph written to {args.json}", file=sys.stderr)
    nodes = graph["nodes"]
    print(f"{sum(n['type'] == 'event' for n in nodes)} events, {len(graph['edges'])} calls")
    for n in nodes:
        if n.get("missing"):
            callers = [e for e in graph["edges"] if e["target"] == n["id"]]
            where = ", ".join(f"{e['file']}:{e['line']}" for e in callers)
            print(f"missing event {n['event_id']} fired from {where}")
    for n in nodes:
        if n.get("orphan"):
            print(f"triggered-only event {n['event_id']} is never fired ({n['file']}:{n['line']})")
    return 0


def _cmd_poptypes(args: argparse.Namespace) -> int:
    from vic2toolmod.analysis.poptypes import influences, pop_weights, promotion_graph
    from vic2toolmod.workspace import Workspace

    settings = load_settings()
    mod = args.mod or (settings.mod_dirs[0] if settings.mod_dirs else None)
    ws = Workspace.open(args.game or settings.game_dir, mod)
    weights = pop_weights(ws)
    if args.json:
        args.json.write_text(json.dumps(promotion_graph(weights), indent=1), encoding="utf-8")
        print(f"promotion graph written to {args.json}", file=sys.stderr)
    table = influences(weights, tuple(args.registry or ("issue_option", "technology", "invention")))
    for (registry, name), uses in sorted(table.items()):
        print(f"{name} ({registry}):")
        for w, m in uses:
            target = w.target or w.kind
            what = (
                f"{w.pop} -> {target}" if w.kind == "promote_to" else f"{w.pop} {w.kind} {target}"
            )
            print(
                f"    {what}: x{m.factor:g}  [{w.file}:{m.line}]"
                if m.factor is not None
                else f"    {what}  [{w.file}:{m.line}]"
            )
    return 0


def _cmd_install_desktop(args: argparse.Namespace) -> int:
    from vic2toolmod.desktop import install_desktop

    print(f"menu shortcut written: {install_desktop()}")
    return 0


def _cmd_gui(args: argparse.Namespace) -> int:
    import os
    import webbrowser

    from vic2toolmod.server import lifecycle, make_server
    from vic2toolmod.workspace import Workspace

    settings = load_settings()
    resume = json.loads(os.environ.pop(lifecycle.RESUME_ENV, "") or "{}")
    # A plain start is "the" GUI server: found and reused by the next plain start.
    plain = args.port == 0 and args.mod is None and args.game is None
    register = bool(resume.get("register")) if resume else plain
    if plain and not resume and (state := lifecycle.read_state()) is not None:
        info = lifecycle.ping(state)
        if info is not None and info.get("stamp") == lifecycle.code_stamp():
            url = lifecycle.url_of(state)
            print(f"vic2toolmod GUI is already running: {url}", flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        if info is not None:
            print("replacing the running GUI server (the tool's code changed)", flush=True)
            lifecycle.ask_to_quit(state)

    if resume:
        game = Path(resume["game"]) if resume.get("game") else None
        mod = Path(resume["mod"]) if resume.get("mod") else None
    else:
        game = args.game or settings.game_dir
        mod = args.mod or (settings.mod_dirs[0] if settings.mod_dirs else None)
    ws = Workspace.open(game, mod)
    stay = bool(resume.get("stay")) if resume else args.stay
    life = lifecycle.Lifetime(auto=not stay)
    server, token = make_server(
        ws, args.port, token=resume.get("token"), warm_up=True, lifetime=life
    )
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/?token={token}"
    print(f"vic2toolmod GUI: {url}  (Ctrl+C to stop)", flush=True)
    if register:
        lifecycle.write_state(port, token)
    life.watch(server.shutdown)
    if not args.no_browser and not resume:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if register:
            lifecycle.clear_state(port)
    if life.restart:
        project = server.engine.ws.project  # type: ignore[attr-defined]
        state = {
            "token": token,
            "register": register,
            "stay": stay,
            "game": str(project.game_dir) if project.game_dir else None,
            "mod": str(project.mod_dir) if project.mod_dir else None,
        }
        env = {**os.environ, lifecycle.RESUME_ENV: json.dumps(state)}
        argv = [sys.executable, "-m", "vic2toolmod", "gui", "--port", str(port), "--no-browser"]
        if sys.platform == "win32":
            import subprocess

            subprocess.Popen(argv, env=env)  # noqa: S603 - our own command
        else:
            os.execve(sys.executable, argv, env)  # noqa: S606 - our own command
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

    p = sub.add_parser("install-desktop", help="add a shortcut to the Linux application menu")
    p.set_defaults(func=_cmd_install_desktop)

    p = sub.add_parser("gui", help="start the local server for the GUI")
    p.add_argument("--mod", type=Path, help="mod folder (default: configured)")
    p.add_argument("--game", type=Path, help="game folder (default: configured)")
    p.add_argument("--port", type=int, default=0, help="port (default: any free one)")
    p.add_argument(
        "--stay",
        action="store_true",
        help="keep running after the browser window is closed",
    )
    p.add_argument("--no-browser", action="store_true", help="do not open a browser")
    p.set_defaults(func=_cmd_gui)

    for name, func, help_ in (
        ("diff-vanilla", _cmd_diff_vanilla, "what the mod changes in vanilla"),
        ("stats", _cmd_stats, "pops at the start by owner / culture / religion / type"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--mod", type=Path, help="mod folder (default: configured)")
        p.add_argument("--game", type=Path, help="game folder (default: configured)")
        p.add_argument("--top", type=int, default=15, help="rows per table")
        if name == "diff-vanilla":
            p.add_argument("--file", help="show the diff of one file")
        p.set_defaults(func=func)

    p = sub.add_parser("events", help="event chains: missing and never-fired events")
    p.add_argument("--mod", type=Path, help="mod folder (default: configured)")
    p.add_argument("--game", type=Path, help="game folder (default: configured)")
    p.add_argument("--json", type=Path, help="write the event graph as JSON")
    p.set_defaults(func=_cmd_events)

    p = sub.add_parser("poptypes", help="what changes pop promotion / ideologies / issues")
    p.add_argument("--mod", type=Path, help="mod folder (default: configured)")
    p.add_argument("--game", type=Path, help="game folder (default: configured)")
    p.add_argument("--json", type=Path, help="write the promotion graph as JSON")
    p.add_argument(
        "--registry", action="append", help="kinds of names (default: reforms, techs, inventions)"
    )
    p.set_defaults(func=_cmd_poptypes)

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

    p = sub.add_parser("run-script", help="run a light Python script on the mod (preview first)")
    p.add_argument("script", nargs="?", help="script id (replace_text, own/x) or a .py file")
    p.add_argument("-p", "--param", action="append", metavar="NAME=VALUE", help="field value")
    p.add_argument("--list", action="store_true", help="list the scripts and their fields")
    p.add_argument("--mod", type=Path, help="mod folder (default: configured)")
    p.add_argument("--game", type=Path, help="game folder (default: configured)")
    p.add_argument("--write", action="store_true", help="write the files (with a backup)")
    p.set_defaults(func=_cmd_run_script)

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
