"""Teach the schema what vanilla 3.04 uses.

Vanilla is the reference: whatever the game's own files use is valid. This
tool runs the checker on vanilla and

* adds scopes in which a command is used to a separate ``vanilla_scopes``
  list of its entry (so it stays visible which scopes come from CWTools and
  which were observed in vanilla);
* adds modifier keys used in modifier blocks to ``modifiers.yaml`` with
  ``source: vanilla``.

Usage: ``python tools/learn_from_vanilla.py "<game folder>"`` (rewrites files in
``vic2toolmod/schema/data``; review the diff).
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from vic2toolmod.check import check_project
from vic2toolmod.project import Project

DATA = Path(__file__).resolve().parent.parent / "vic2toolmod" / "schema" / "data" / "commands"
MESSAGE = re.compile(r"'([^']+)' works in .* scope, not in (\w+)")
MODIFIER = re.compile(r"unknown modifier '([^']+)'")


def main(game: Path) -> None:
    """Collect wrong-scope diagnostics on vanilla and widen the schema."""
    seen: dict[str, set[str]] = defaultdict(set)
    modifiers: set[str] = set()
    for report in check_project(Project.open(game), only_mod=False):
        for d in report.diagnostics:
            if d.code == "schema.wrong-scope" and (m := MESSAGE.match(d.message)):
                seen[m[1].lower()].add(m[2])
            elif d.code == "schema.unknown-key" and (m := MODIFIER.match(d.message)):
                modifiers.add(m[1].lower())
    if modifiers:
        path = DATA.parent / "modifiers.yaml"
        text = path.read_text()
        header = "".join(line + "\n" for line in text.splitlines() if line.startswith("#"))
        data = yaml.safe_load(text)
        for name in sorted(modifiers):
            data["modifiers"].setdefault(name, {"value": "float", "source": "vanilla"})
        path.write_text(header + yaml.safe_dump(data, default_flow_style=None, sort_keys=True))
        print("modifiers added:", ", ".join(sorted(modifiers)))
    dump = {"default_flow_style": None, "sort_keys": True, "allow_unicode": True, "width": 100}
    for path in sorted(DATA.glob("*.yaml")):
        text = path.read_text()
        header = "".join(line + "\n" for line in text.splitlines() if line.startswith("#"))
        data = yaml.safe_load(text)
        changed = False
        for section, entries in data.items():
            if section == "dynamic":
                continue
            for name, raw in (entries or {}).items():
                if name.lower() not in seen:
                    continue
                for alt in raw if isinstance(raw, list) else [raw]:
                    scopes = alt.get("scopes", ["any"])
                    if "any" in scopes:
                        continue
                    extra = sorted(
                        seen[name.lower()] - set(scopes) | set(alt.get("vanilla_scopes", []))
                    )
                    if extra:
                        alt["vanilla_scopes"] = extra
                        changed = True
        if changed:
            path.write_text(header + yaml.safe_dump(data, **dump))
            print("updated", path.name)
    for name, scopes in sorted(seen.items()):
        print(f"  {name}: {sorted(scopes)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
