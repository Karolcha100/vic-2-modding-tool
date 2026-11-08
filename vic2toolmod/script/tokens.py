"""Tokens of Paradox (Clausewitz) script as used by Victoria 2.

Every token carries its *leading trivia*: the whitespace, line breaks and
``#`` comments that precede it. Concatenating ``leading + text`` of all tokens
of a file (including the final `TokenKind.EOF` token) gives back the file
exactly, which is what makes the parser lossless.
"""

from __future__ import annotations

import re
from enum import IntEnum

_COMMENT = re.compile(r"#[^\r\n]*")


class TokenKind(IntEnum):
    """Kinds of tokens."""

    WORD = 1
    """Unquoted value or key: ``yes``, ``USA``, ``-0.5``, ``1836.1.1``, ``any_pop``."""
    STRING = 2
    """Quoted string, possibly spanning lines: ``"EVTNAME95260"``."""
    BAD_STRING = 3
    """String whose closing quote is missing; it ends at the end of its line."""
    OPERATOR = 4
    """``=``, ``<``, ``>``, ``<=`` or ``>=``."""
    LBRACE = 5
    """``{``."""
    RBRACE = 6
    """``}``."""
    EOF = 7
    """End of file; its text is empty, its leading trivia is the file's tail."""


class Token:
    """One token of a script file.

    Attributes:
        kind: What kind of token this is.
        text: The token text exactly as in the file (quotes included).
        start: Offset of ``text`` in the file (in characters).
        leading: Trivia (whitespace, line breaks, comments) right before it.
    """

    __slots__ = ("kind", "leading", "start", "text")

    def __init__(self, kind: TokenKind, text: str, start: int, leading: str) -> None:
        self.kind = kind
        self.text = text
        self.start = start
        self.leading = leading

    @property
    def end(self) -> int:
        """Offset just past the token text."""
        return self.start + len(self.text)

    @property
    def full_start(self) -> int:
        """Offset where the leading trivia begins."""
        return self.start - len(self.leading)

    @property
    def value(self) -> str:
        """The token text with surrounding quotes removed (for strings)."""
        if self.kind is TokenKind.STRING:
            return self.text[1:-1]
        if self.kind is TokenKind.BAD_STRING:
            return self.text[1:]
        return self.text

    def comments(self) -> list[str]:
        """Comments in the leading trivia, without the ``#``, in file order."""
        return [m.group()[1:] for m in _COMMENT.finditer(self.leading)]

    def __repr__(self) -> str:
        return f"Token({self.kind.name}, {self.text!r}, {self.start})"
