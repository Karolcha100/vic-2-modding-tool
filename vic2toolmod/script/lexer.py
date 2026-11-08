"""Turn script text into tokens without losing anything.

The lexer never fails: every character of the input ends up either in a
token's text or in a token's leading trivia. Problems (an unterminated string)
are expressed by the token kind and reported by the parser.
"""

from __future__ import annotations

import re

from vic2toolmod.script.tokens import Token, TokenKind

# Group 1 is the leading trivia; groups 2..7 are the token alternatives, so
# ``match.lastindex`` tells which one matched (1 = only trivia, i.e. EOF).
_TOKEN_RE = re.compile(
    r"""
    ((?:[ \t\r\n\f\v]+|\#[^\r\n]*)*)       # 1: trivia - whitespace and comments
    (?:
        ([^ \t\r\n\f\v={}"\#<>]+)           # 2: word
      | ("[^"]*")                           # 3: string (may span lines)
      | ("[^\r\n]*)                         # 4: string without closing quote
      | (<=|>=|=|<|>)                       # 5: operator
      | (\{)                                # 6: {
      | (\})                                # 7: }
    )?
    """,
    re.VERBOSE,
)

_KINDS = {
    2: TokenKind.WORD,
    3: TokenKind.STRING,
    4: TokenKind.BAD_STRING,
    5: TokenKind.OPERATOR,
    6: TokenKind.LBRACE,
    7: TokenKind.RBRACE,
}


def tokenize(text: str) -> list[Token]:
    """Split script text into tokens.

    Args:
        text: The whole file as text.

    Returns:
        All tokens in file order. The last one is always `TokenKind.EOF`.
    """
    tokens: list[Token] = []
    append = tokens.append
    match = _TOKEN_RE.match
    kinds = _KINDS
    pos = 0
    length = len(text)
    while True:
        m = match(text, pos)
        assert m is not None  # the pattern can match the empty string
        group = m.lastindex
        leading = m.group(1)
        if group is None or group == 1:
            # Only trivia left (or nothing at all): end of file.
            append(Token(TokenKind.EOF, "", m.end(), leading))
            if m.end() != length:  # pragma: no cover - the pattern covers every char
                raise AssertionError(f"lexer stuck at offset {m.end()}")
            return tokens
        start = m.start(group)
        append(Token(kinds[group], m.group(group), start, leading))
        pos = m.end()
