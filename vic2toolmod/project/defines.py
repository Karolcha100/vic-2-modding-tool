"""Reading ``common/defines.lua`` (a Lua table of numbers and strings).

Only the subset the game uses is understood: nested tables ``name = { ... }``,
``key = value`` separated by commas, numbers, ``'strings'`` / ``"strings"``
and ``--`` comments. The result is a nested dict; values keep their text form
next to the parsed number, so the file could be rewritten later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from vic2toolmod import textio

_TOKEN = re.compile(
    r"""
      (?P<ws>\s+|--[^\n]*)
    | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<number>-?\d+(?:\.\d+)?|-?\.\d+)
    | (?P<string>'[^']*'|"[^"]*")
    | (?P<punct>[={},])
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class DefineValue:
    """One value: its text in the file and its parsed form (float or str).

    Attributes:
        text: Text as written (``'1836.1.1'``, ``0.5``).
        value: Parsed value.
        line: Line number (1-based).
    """

    text: str
    value: float | str
    line: int


Defines = dict[str, Union["Defines", DefineValue]]


class DefinesError(ValueError):
    """The file is not in the expected format."""


def parse_defines(text: str) -> Defines:
    """Parse the text of ``defines.lua``.

    Raises:
        DefinesError: On unexpected syntax (with the line number).
    """
    tokens: list[tuple[str, str, int]] = []
    pos = 0
    line = 1
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise DefinesError(f"line {line}: unexpected {text[pos]!r}")
        kind = m.lastgroup or ""
        if kind != "ws":
            tokens.append((kind, m.group(), line))
        line += m.group().count("\n")
        pos = m.end()

    i = 0

    def expect(kind: str, value: str | None = None) -> tuple[str, str, int]:
        nonlocal i
        if i >= len(tokens):
            raise DefinesError("unexpected end of file")
        tok = tokens[i]
        if tok[0] != kind or (value is not None and tok[1] != value):
            raise DefinesError(f"line {tok[2]}: expected {value or kind}, got {tok[1]!r}")
        i += 1
        return tok

    def table() -> Defines:
        nonlocal i
        out: Defines = {}
        expect("punct", "{")
        while tokens[i][1] != "}":
            _, key, _ = expect("name")
            expect("punct", "=")
            kind, val, ln = tokens[i]
            if val == "{":
                out[key] = table()
            elif kind == "number":
                i += 1
                out[key] = DefineValue(val, float(val), ln)
            elif kind == "string":
                i += 1
                out[key] = DefineValue(val, val[1:-1], ln)
            else:
                raise DefinesError(f"line {ln}: unexpected {val!r}")
            if tokens[i][1] == ",":
                i += 1
        expect("punct", "}")
        return out

    result: Defines = {}
    while i < len(tokens):
        _, name, _ = expect("name")
        expect("punct", "=")
        result[name] = table()
    return result


def read_defines(path: str | Path) -> Defines:
    """Read and parse a ``defines.lua`` file."""
    text, _ = textio.decode(Path(path).read_bytes())
    return parse_defines(text)
