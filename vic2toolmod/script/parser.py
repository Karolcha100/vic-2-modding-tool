"""Build a `Document` tree from script text, recovering from syntax errors.

Grammar (informal)::

    file       = item* EOF
    item       = assignment | value | ERROR
    assignment = key OPERATOR value
    key        = WORD | STRING
    value      = WORD | STRING | block
    block      = "{" item* "}"

Recovery rules - the parser never stops early:

* ``}`` without a matching ``{`` becomes an `ErrorNode`;
* a block still open at the end of the file is closed implicitly;
* ``key =`` followed by ``}``, another operator or the end of the file becomes
  an `Assignment` without a value;
* an operator that does not follow a key becomes an `ErrorNode`;
* a string without its closing quote ends at the end of its line.

Each of these produces an error `Diagnostic`. The parser is iterative (an
explicit stack instead of recursion), so deeply nested or broken files cannot
exhaust the Python call stack.
"""

from __future__ import annotations

from pathlib import Path

from vic2toolmod import textio
from vic2toolmod.script.cst import Assignment, Block, Document, ErrorNode, Node, Scalar
from vic2toolmod.script.diagnostics import Diagnostic, Severity
from vic2toolmod.script.lexer import tokenize
from vic2toolmod.script.tokens import Token, TokenKind

_W = TokenKind.WORD
_S = TokenKind.STRING
_BS = TokenKind.BAD_STRING
_OP = TokenKind.OPERATOR
_LB = TokenKind.LBRACE
_RB = TokenKind.RBRACE
_VALUE_KINDS = (_W, _S, _BS)


def _error(code: str, message: str, token: Token, end: int | None = None) -> Diagnostic:
    return Diagnostic(Severity.ERROR, code, message, token.start, token.end if end is None else end)


def _unterminated(token: Token) -> Diagnostic:
    return _error("syntax.unterminated-string", "string has no closing quote", token)


def parse_text(text: str) -> Document:
    """Parse script text.

    Args:
        text: The whole file as text.

    Returns:
        The document tree with its syntax diagnostics. ``doc.to_text() == text``
        always holds.
    """
    tokens = tokenize(text)
    diagnostics: list[Diagnostic] = []
    top: list[Node] = []
    # Stack of open blocks; ``items`` is the list new nodes are appended to.
    stack: list[Block] = []
    items = top
    i = 0
    n = len(tokens)
    while True:
        tok = tokens[i]
        kind = tok.kind
        if kind in _VALUE_KINDS:
            if kind is _BS:
                diagnostics.append(_unterminated(tok))
            nxt = tokens[i + 1]
            if nxt.kind is _OP and kind is not _BS:
                after = tokens[i + 2]  # exists: the last token is EOF, never an operator
                if after.kind in _VALUE_KINDS:
                    if after.kind is _BS:
                        diagnostics.append(_unterminated(after))
                    items.append(Assignment(tok, nxt, Scalar(after)))
                    i += 3
                elif after.kind is _LB:
                    block = Block(after)
                    items.append(Assignment(tok, nxt, block))
                    stack.append(block)
                    items = block.items
                    i += 3
                else:
                    diagnostics.append(
                        _error(
                            "syntax.missing-value",
                            f"'{tok.text} {nxt.text}' has no value",
                            tok,
                            nxt.end,
                        )
                    )
                    items.append(Assignment(tok, nxt, None))
                    i += 2
            else:
                items.append(Scalar(tok))
                i += 1
        elif kind is _LB:
            block = Block(tok)
            items.append(block)
            stack.append(block)
            items = block.items
            i += 1
        elif kind is _RB:
            if stack:
                stack.pop().rbrace = tok
                items = stack[-1].items if stack else top
            else:
                diagnostics.append(
                    _error("syntax.unmatched-close-brace", "'}' without a matching '{'", tok)
                )
                items.append(ErrorNode([tok]))
            i += 1
        elif kind is _OP:
            diagnostics.append(
                _error("syntax.operator-without-key", f"'{tok.text}' does not follow a key", tok)
            )
            items.append(ErrorNode([tok]))
            i += 1
        else:  # EOF
            for block in stack:
                diagnostics.append(
                    _error("syntax.unclosed-brace", "'{' is never closed", block.lbrace)
                )
            assert i == n - 1
            if any(d.code in _BRACE_ERRORS for d in diagnostics):
                diagnostics.extend(_indent_hints(text, top))
            diagnostics.sort(key=lambda d: d.start)
            return Document(text=text, items=top, eof=tok, diagnostics=diagnostics)


_BRACE_ERRORS = frozenset({"syntax.unclosed-brace", "syntax.unmatched-close-brace"})
_TAB_WIDTH = 4


def _indent_of_line(text: str, offset: int) -> tuple[int, bool]:
    """Indentation width of the line containing ``offset``.

    Returns:
        The width (a tab counts as `_TAB_WIDTH`) and whether ``offset`` is the
        first non-blank character of its line.
    """
    line_start = max(text.rfind("\n", 0, offset), text.rfind("\r", 0, offset)) + 1
    width = 0
    pos = line_start
    while pos < offset and text[pos] in " \t":
        width += _TAB_WIDTH if text[pos] == "\t" else 1
        pos += 1
    return width, pos == offset


def _indent_hints(text: str, top: list[Node]) -> list[Diagnostic]:
    """Point at blocks whose ``}`` is indented differently from their opening line.

    A missing or extra brace is reported where the parser notices it, which
    is often far from the real mistake (a missing ``}`` in the middle of a
    file shows up as an unclosed block at its start). The block whose closing
    brace is indented differently from the line that opened it is usually
    the real culprit. Only used for files that already have brace errors.
    """
    hints: list[Diagnostic] = []
    stack: list[Node] = list(reversed(top))
    while stack:
        node = stack.pop()
        if isinstance(node, Assignment) and isinstance(node.value, Block):
            opener, block = node.key, node.value
        elif isinstance(node, Block):
            opener, block = node.lbrace, node
        else:
            continue
        stack.extend(reversed(block.items))
        if block.rbrace is None:
            continue
        open_indent, _ = _indent_of_line(text, opener.start)
        close_indent, close_first = _indent_of_line(text, block.rbrace.start)
        if close_first and close_indent != open_indent:
            close_line = text.count("\n", 0, block.rbrace.start) + 1
            hints.append(
                Diagnostic(
                    Severity.WARNING,
                    "syntax.brace-indentation",
                    f"possible cause of the brace error: this block's '}}' (line {close_line}) "
                    "is indented differently from the line that opens it",
                    opener.start,
                    block.lbrace.end,
                )
            )
    return hints


def parse_file(path: str | Path) -> tuple[Document, textio.Encoding]:
    """Read (losslessly) and parse a file.

    Args:
        path: File to parse.

    Returns:
        The document and the file's encoding, needed to write it back with
        `vic2toolmod.textio.write_source`.
    """
    source = textio.read_source(path)
    return parse_text(source.text), source.encoding
