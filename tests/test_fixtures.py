import json
from pathlib import Path

import pytest

from vic2toolmod import textio
from vic2toolmod.script import parse_text
from vic2toolmod.script.printer import diagnostics_data, to_data

FIXTURES = Path(__file__).parent / "fixtures" / "script"
CASES = sorted(p.stem for p in FIXTURES.glob("*.txt"))


def test_fixtures_exist():
    assert len(CASES) >= 16
    for name in CASES:
        assert (FIXTURES / f"{name}.json").is_file(), name


@pytest.mark.parametrize("name", CASES)
def test_fixture(name):
    data = (FIXTURES / f"{name}.txt").read_bytes()
    text, encoding = textio.decode(data)
    doc = parse_text(text)
    expected = json.loads((FIXTURES / f"{name}.json").read_text())
    assert to_data(doc) == expected["items"]
    assert diagnostics_data(doc) == expected["diagnostics"]
    assert textio.encode(doc.to_text(), encoding) == data
