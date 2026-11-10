"""Scopes in which Project Alice accepts each trigger and effect (K88 = B).

Project Alice (https://github.com/schombert/Project-Alice, GPL-3) is an
open-source reimplementation of Victoria 2 that reads the game's own files.
Its script parser checks the scope of every trigger and effect
(``context.main_slot == trigger::slot_contents::state`` …). This tool reads
those checks and writes, as facts only (no code is copied):

    vic2toolmod/schema/data/alice_scopes.yaml

Only names our schema knows (the original game's) are kept; Alice's own
extensions (its ``docs/extensions.md``) are left out. The validator uses the
file to mark scope notes "Project Alice accepts this scope" and hide them by
default; nothing else changes.

Usage::

    git clone --depth 1 --filter=blob:none --sparse https://github.com/schombert/Project-Alice
    (cd Project-Alice && git sparse-checkout set docs src/parsing)
    python tools/import_alice_scopes.py Project-Alice
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

from vic2toolmod.schema.loader import default_schema
from vic2toolmod.schema.model import Context

OUT = Path(__file__).resolve().parent.parent / "vic2toolmod/schema/data/alice_scopes.yaml"
_SLOTS = {"nation": "country", "state": "state", "province": "province", "pop": "pop"}
_FUNC = re.compile(r"^\tvoid ([a-z_0-9]+)\(", re.M)
_SLOT = re.compile(r"main_slot\s*==\s*trigger::slot_contents::(nation|state|province|pop)")
#: ``exists = TAG`` is checked in no scope at all (only ``exists = yes`` needs a country).
_ANY_SCOPE = {("trigger", "exists")}


def scopes_by_function(source: str) -> dict[str, set[str]]:
    """Function name -> the scopes its scope checks name."""
    out: dict[str, set[str]] = {}
    starts = [(m.start(), m.group(1)) for m in _FUNC.finditer(source)]
    for (start, name), (end, _) in zip(starts, [*starts[1:], (len(source), "")], strict=True):
        found = {_SLOTS[s] for s in _SLOT.findall(source, start, end)}
        if found:
            out.setdefault(name, set()).update(found)
    return out


def extensions(alice: Path) -> set[str]:
    """Names Alice added to the language (``- `name …`` items of docs/extensions.md)."""
    text = (alice / "docs/extensions.md").read_text(encoding="utf-8", errors="replace")
    return {m.lower() for m in re.findall(r"^- `([a-z_0-9]+)", text, re.M)}


def main(alice: Path) -> int:
    """Write the data file from an Alice checkout."""
    schema = default_schema()
    added = extensions(alice)
    version = subprocess.run(
        ["git", "-C", str(alice), "log", "-1", "--format=%h %ad", "--date=short"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    data: dict[str, dict[str, list[str]]] = {}
    headers = ((Context.TRIGGER, "trigger_parsing.hpp"), (Context.EFFECT, "effect_parsing.hpp"))
    for context, header in headers:
        source = (alice / "src/parsing" / header).read_text(encoding="utf-8", errors="replace")
        ours = {k.lower() for (c, k) in schema.commands if c == context}
        found = scopes_by_function(source)
        section: dict[str, list[str]] = {}
        for name in sorted(ours):
            if name in added:
                continue
            if (context.value, name) in _ANY_SCOPE:
                section[name] = sorted(_SLOTS.values())
            elif name in found:
                section[name] = sorted(found[name])
        data[context.value] = section
    head = (
        "# Scopes in which Project Alice (open-source Victoria 2, GPL-3) accepts each\n"
        "# trigger / effect of the original game - facts read from its parser, no code.\n"
        f"# Made by tools/import_alice_scopes.py from Alice {version or '(unknown version)'}.\n"
        "# Used only to mark scope notes \"Project Alice accepts this scope\" (K88 = B).\n"
    )
    OUT.write_text(head + yaml.safe_dump(data, sort_keys=True, width=100), encoding="utf-8")
    print(f"{OUT}: {len(data['trigger'])} triggers, {len(data['effect'])} effects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
