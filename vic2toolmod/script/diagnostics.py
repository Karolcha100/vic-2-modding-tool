"""Problems found in a file, with positions that a user (or a GUI) can show."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from enum import StrEnum

_LINE_BREAK = re.compile(r"\r\n|\n|\r")


class Severity(StrEnum):
    """How serious a problem is."""

    ERROR = "error"
    """The game will misread the file or fail."""
    WARNING = "warning"
    """Probably a mistake."""
    INFO = "info"
    """Worth knowing, not necessarily wrong."""


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One problem in a file.

    Attributes:
        severity: How serious it is.
        code: Stable machine-readable identifier, e.g. ``syntax.unclosed-brace``.
        message: Human-readable description (English).
        start: Offset of the first character the problem is about.
        end: Offset just past the last character the problem is about.
    """

    severity: Severity
    code: str
    message: str
    start: int
    end: int


class LineIndex:
    r"""Converts character offsets to 1-based line and column numbers.

    ``\r\n``, ``\n`` and a lone ``\r`` each count as one line break.
    """

    def __init__(self, text: str) -> None:
        self._starts = [0] + [m.end() for m in _LINE_BREAK.finditer(text)]

    def position(self, offset: int) -> tuple[int, int]:
        """Return ``(line, column)`` of an offset, both counted from 1."""
        line = bisect.bisect_right(self._starts, offset) - 1
        return line + 1, offset - self._starts[line] + 1

    def line_start(self, line: int) -> int:
        """Offset of the first character of a 1-based line (clamped to the file)."""
        return self._starts[max(0, min(line, len(self._starts)) - 1)]

    @property
    def line_count(self) -> int:
        """Number of lines (a trailing line break starts an empty last line)."""
        return len(self._starts)
