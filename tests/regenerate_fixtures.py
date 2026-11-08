"""Regenerate tests/fixtures/script/*.json from the current parser (review the diff!)."""

import json
from pathlib import Path

from vic2toolmod import textio
from vic2toolmod.script import parse_text
from vic2toolmod.script.printer import diagnostics_data, to_data

FIXTURES = Path(__file__).parent / "fixtures" / "script"

for path in sorted(FIXTURES.glob("*.txt")):
    text, _ = textio.decode(path.read_bytes())
    doc = parse_text(text)
    data = {"items": to_data(doc), "diagnostics": diagnostics_data(doc)}
    path.with_suffix(".json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print("wrote", path.with_suffix(".json").name)
