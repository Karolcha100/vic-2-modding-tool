r"""Light formatting of script files (T011, K91 = A).

What changes, and nothing else:

- indentation: one tab per open ``{`` (a line starting with ``}`` one less);
- one space on each side of ``=`` (and of ``<``, ``>``, ``<=``, ``>=``);
- no spaces or tabs at the end of a line;
- at most one empty line in a row; none at the start or the end of the file.

Line breaks stay where they are, so ``color = { 1 2 3 }`` and short one-line
``modifier = { … }`` blocks stay on one line. Comments, strings and every
other space between tokens on a line stay as written; line breaks keep their
own kind (``\\r\\n`` or ``\\n``).

`format_text` checks its own result: the file read again must give the same
tokens and the same comments (but for spaces at their end), in the same order.
A file with unbalanced braces or an unclosed string is not formatted
(`FormatError`), because its block depth is not certain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from vic2toolmod.changes import FileChange
from vic2toolmod.script.lexer import tokenize
from vic2toolmod.script.tokens import Token, TokenKind
from vic2toolmod.textio import Encoding, decode
from vic2toolmod.workspace import Workspace

_PIECES = re.compile(r"(?P<nl>\r\n|\n|\r)|(?P<comment>#[^\r\n]*)|(?P<space>[ \t\f\v]+)")
_BREAK = re.compile(r"\r\n|\n|\r")
#: File suffixes the formatter is for (K92 = A).
SUFFIXES = (".txt", ".gui", ".gfx")


class FormatError(ValueError):
    """The file cannot be formatted safely."""


@dataclass(frozen=True)
class _Piece:
    kind: str  # "nl" | "comment" | "space"
    text: str


def _pieces(trivia: str) -> list[_Piece]:
    out = []
    pos = 0
    for m in _PIECES.finditer(trivia):
        if m.start() != pos:  # anything else in trivia (should not happen): keep as a comment
            out.append(_Piece("comment", trivia[pos : m.start()]))
        kind = m.lastgroup or "space"
        out.append(_Piece(kind, m.group()))
        pos = m.end()
    if pos != len(trivia):
        out.append(_Piece("comment", trivia[pos:]))
    return out


def format_text(text: str) -> str:
    """The text formatted (see the module docstring).

    Raises:
        FormatError: When the file has syntax errors or the result would not
            mean the same (a safety net; it should never happen).
    """
    tokens = tokenize(text)
    _check_braces(tokens)
    lines: list[tuple[str, str]] = []  # (line without its break, the break or "" at the end)
    content: list[str] = []  # the current line, without indentation
    line_depth = 0
    depth = 0
    pending = ""  # the original space before the next item on this line
    prev: Token | None = None  # the previous token on this line

    def add(item: str, item_depth: int, sep: str | None = None) -> None:
        nonlocal line_depth, pending
        if not content:
            line_depth = item_depth
        elif sep is not None:
            content.append(sep)
        elif pending:
            content.append(pending)
        content.append(item)
        pending = ""

    def end_line(nl: str) -> None:
        nonlocal pending, prev
        line = ("\t" * line_depth + "".join(content)).rstrip(" \t") if content else ""
        lines.append((line, nl))
        content.clear()
        pending = ""
        prev = None

    for tok in tokens:
        for p in _pieces(tok.leading):
            if p.kind == "nl":
                end_line(p.text)
            elif p.kind == "comment":
                add(p.text, depth)
            else:
                pending = p.text
        if tok.kind is TokenKind.EOF:
            break
        operator = prev is not None and TokenKind.OPERATOR in (tok.kind, prev.kind)
        tok_depth = depth - 1 if tok.kind is TokenKind.RBRACE else depth
        add(tok.text, tok_depth, " " if operator else None)
        if tok.kind is TokenKind.LBRACE:
            depth += 1
        elif tok.kind is TokenKind.RBRACE:
            depth = max(depth - 1, 0)
        prev = tok
    if content:
        end_line("")
    # empty lines: none at the start or the end of the file, at most one in a row
    out: list[str] = []
    empty = 0
    br = _line_break(lines)
    for line, nl in lines:
        if not line:
            empty += 1
            continue
        if out and empty:
            out.append(br)
        out.append(line + nl)
        empty = 0
    result = "".join(out)
    _same_meaning(tokens, result)
    return result


def _check_braces(tokens: list[Token]) -> None:
    """The block depth must be certain: braces balanced, no unclosed string."""
    depth = 0
    for t in tokens:
        if t.kind is TokenKind.BAD_STRING:
            raise FormatError("the file has a string without its closing quote: fix it first")
        if t.kind is TokenKind.LBRACE:
            depth += 1
        elif t.kind is TokenKind.RBRACE:
            depth -= 1
            if depth < 0:
                raise FormatError("the file has a '}' too many: fix it first")
    if depth:
        raise FormatError("the file has a '{' without its '}': fix it first")


def _line_break(lines: list[tuple[str, str]]) -> str:
    """The line break the file uses most (for the one empty line kept between blocks)."""
    crlf = sum(1 for _, nl in lines if nl == "\r\n")
    lf = sum(1 for _, nl in lines if nl == "\n")
    return "\r\n" if crlf >= lf and crlf else "\n"


def _same_meaning(old: list[Token], new: str) -> None:
    def key(tokens: list[Token]) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for t in tokens:
            out += [(0, c.rstrip(" \t")) for c in t.comments()]
            if t.kind is not TokenKind.EOF:
                out.append((int(t.kind), t.text))
        return out

    if key(old) != key(tokenize(new)):
        raise FormatError("formatting would change the meaning of the file (not formatted)")


# -- the whole mod -------------------------------------------------------------------------
@dataclass
class ModPlan:
    """Formatting of many files: the changes, changed lines per file, files left out.

    Attributes:
        changes: New texts of the files that change.
        lines: Changed lines per file (``rel`` -> count).
        skipped: Files not formatted and why (syntax error, unsaved editor text).
        same: How many files were already formatted.
    """

    changes: list[FileChange] = field(default_factory=list)
    lines: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    same: int = 0


def changed_lines(old: str, new: str) -> int:
    """How many lines formatting changed (it keeps line breaks, so lines pair up in order)."""
    a = _BREAK.split(old)
    b = _BREAK.split(new)
    removed = max(sum(1 for x in a if not x.strip()) - sum(1 for y in b if not y.strip()), 0)
    # lines of only spaces / tabs that stay become empty: changed too
    blanked = max(sum(1 for x in a if x and not x.strip()) - removed, 0)
    pairs = zip([x for x in a if x.strip()], [y for y in b if y.strip()], strict=False)
    return removed + blanked + sum(1 for x, y in pairs if x != y)


def _format_path(path: str) -> tuple[str, str | None, Encoding, str]:
    """(old text, new text or None, encoding, reason when not formatted)."""
    text, encoding = decode(Path(path).read_bytes())
    try:
        return text, format_text(text), encoding, ""
    except FormatError as exc:
        return text, None, encoding, str(exc)


def format_mod(ws: Workspace, rels: list[str] | None = None) -> ModPlan:
    """Format the mod's own script files (``.txt``, ``.gui``, ``.gfx``; never the game's).

    Args:
        ws: The project (a mod must be open).
        rels: Only these files (default: all of the mod's). RPM: ~6 s for all.

    Raises:
        ValueError: When no mod is open.
    """
    mod = ws.project.mod_dir
    if mod is None:
        raise ValueError("the game's own files are read-only: open a mod to format files")
    wanted = {r.lower() for r in rels} if rels is not None else None
    files = [
        f
        for f in ws.script_files(only_mod=True)
        if f.origin == "mod"
        and f.rel.lower().endswith(SUFFIXES)
        and (wanted is None or f.rel.lower() in wanted)
    ]
    plan = ModPlan()
    jobs = []
    for f in files:
        disk, _ = decode(f.path.read_bytes())
        if ws.has_unsaved(f.rel, disk):
            plan.skipped[f.rel] = "unsaved changes in the editor"
        else:
            jobs.append(f)
    for f in jobs:
        old, new, encoding, reason = _format_path(str(f.path))
        if new is None:
            plan.skipped[f.rel] = reason
        elif new == old:
            plan.same += 1
        else:
            plan.changes.append(FileChange(f.rel, f.path, old, new, encoding))
            plan.lines[f.rel] = changed_lines(old, new)
    return plan
