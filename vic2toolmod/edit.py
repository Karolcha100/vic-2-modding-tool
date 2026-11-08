"""Editing a file through its tree, as small text edits (K31: text is the source of truth).

Operations never change a `Document`; they return `TextEdit` objects that
replace exact character ranges of the text. Applying them and parsing again
gives the new tree. Everything outside the edited ranges - comments, blank
lines, the author's layout - stays byte for byte.

New code is written in the style of the file (K15): the indentation unit
(tab or spaces) is detected from the file, each key goes on its own line, and
short blocks of plain values stay on one line (``NOT = { war = yes }``).

`Buffer` keeps a text with undo / redo, for an editor.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Union

from vic2toolmod.script.cst import Assignment, Block, Document, Node, Scalar
from vic2toolmod.script.parser import parse_text

#: Python form of new script content: ``[(key, value), ...]`` where a value is
#: a string (written as is), a list of pairs (a block) or a list of strings
#: (loose values, e.g. ``color = { 1 2 3 }``).
Value = Union[str, "Items", list[str]]
Items = Sequence[tuple[str, Value]]

INLINE_LIMIT = 80
_LEADING_WS = re.compile(r"[ \t]*")


@dataclass(frozen=True, slots=True)
class TextEdit:
    """Replace ``text[start:end]`` by ``new_text``."""

    start: int
    end: int
    new_text: str


def apply_edits(text: str, edits: Iterable[TextEdit]) -> str:
    """Apply non-overlapping edits to a text.

    Raises:
        ValueError: If two edits overlap.
    """
    ordered = sorted(edits, key=lambda e: (e.start, e.end))
    for a, b in zip(ordered, ordered[1:], strict=False):
        if b.start < a.end:
            raise ValueError(f"overlapping edits at {a.start}-{a.end} and {b.start}-{b.end}")
    out = []
    pos = 0
    for e in ordered:
        out.append(text[pos : e.start])
        out.append(e.new_text)
        pos = e.end
    out.append(text[pos:])
    return "".join(out)


# -- style of the file ---------------------------------------------------------
def indent_unit(text: str) -> str:
    """The indentation unit of a file: a tab, or the most common space step."""
    tabs = spaces = 0
    steps: dict[int, int] = {}
    for line in text.splitlines():
        ws = _LEADING_WS.match(line).group()  # type: ignore[union-attr]
        if not ws or not line.strip():
            continue
        if ws.startswith("\t"):
            tabs += 1
        else:
            spaces += 1
            steps[len(ws)] = steps.get(len(ws), 0) + 1
    if tabs >= spaces:
        return "\t"
    smallest = min(steps, default=4)
    return " " * max(1, smallest)


def newline_of(text: str) -> str:
    r"""The line break the file uses (``\r\n`` if any line has it)."""
    return "\r\n" if "\r\n" in text else "\n"


def _line_start(text: str, offset: int) -> int:
    return max(text.rfind("\n", 0, offset), text.rfind("\r", 0, offset)) + 1


def _line_indent(text: str, offset: int) -> str:
    start = _line_start(text, offset)
    return _LEADING_WS.match(text, start).group()  # type: ignore[union-attr]


# -- rendering new content -----------------------------------------------------
def render_value(value: Value, unit: str, depth: int, nl: str) -> str:
    """Script text of a value at a given depth (the line it starts on is ``depth``)."""
    if isinstance(value, str):
        return value
    if not value:
        return "{ }"
    if all(isinstance(v, str) for v in value):  # loose values
        return "{ " + " ".join(value) + " }"  # type: ignore[arg-type]
    pairs: Items = value  # type: ignore[assignment]
    simple = all(isinstance(v, str) for _, v in pairs)
    inline = "{ " + " ".join(f"{k} = {v}" for k, v in pairs) + " }"
    if simple and len(pairs) <= 3 and len(inline) + depth * 4 <= INLINE_LIMIT:
        return inline
    inner = unit * (depth + 1)
    lines = [f"{inner}{k} = {render_value(v, unit, depth + 1, nl)}" for k, v in pairs]
    return "{" + nl + nl.join(lines) + nl + unit * depth + "}"


def render_items(items: Items, unit: str, depth: int, nl: str) -> str:
    """Several ``key = value`` lines at a depth, each with its indentation and line break."""
    pad = unit * depth
    return "".join(f"{pad}{k} = {render_value(v, unit, depth, nl)}{nl}" for k, v in items)


# -- operations ------------------------------------------------------------------
def set_value(doc: Document, assignment: Assignment, value: Value) -> TextEdit:
    """Replace the value of an assignment (a scalar or a whole block)."""
    if assignment.value is None:
        return TextEdit(
            assignment.operator.end, assignment.operator.end, " " + _render(doc, assignment, value)
        )
    v = assignment.value
    return TextEdit(v.start, v.end, _render(doc, assignment, value))


def _render(doc: Document, anchor: Node, value: Value) -> str:
    unit = indent_unit(doc.text)
    depth = _depth(doc, anchor, unit)
    return render_value(value, unit, depth, newline_of(doc.text))


def _depth(doc: Document, node: Node, unit: str) -> int:
    indent = _line_indent(doc.text, node.start)
    if unit == "\t":
        return indent.count("\t") + indent.count(" ") // 4
    return len(indent.expandtabs(4)) // max(1, len(unit))


def rename_key(assignment: Assignment, new_key: str) -> TextEdit:
    """Change the key of an assignment."""
    return TextEdit(assignment.key.start, assignment.key.end, new_key)


def replace_token_text(node: Scalar | Assignment, new_text: str) -> TextEdit:
    """Replace the text of a scalar (or of an assignment's key)."""
    tok = node.token if isinstance(node, Scalar) else node.key
    return TextEdit(tok.start, tok.end, new_text)


def delete(doc: Document, node: Node) -> TextEdit:
    """Remove a node. When it is alone on its line(s), the whole line goes.

    Comments on the lines above the node stay.
    """
    text = doc.text
    start, end = node.start, node.end
    ls = _line_start(text, start)
    alone_before = not text[ls:start].strip()
    m = re.compile(r"[ \t]*(#[^\r\n]*)?(\r\n|\n|\r|$)").match(text, end)
    alone_after = m is not None
    if alone_before and alone_after:
        assert m is not None
        if m.group(1):  # keep a trailing comment: delete only the node
            return TextEdit(start, end, "")
        return TextEdit(ls, m.end(), "")
    # Inline: also remove one space before the node.
    if start > 0 and text[start - 1] == " ":
        start -= 1
    return TextEdit(start, end, "")


def insert(
    doc: Document, parent: Block | Document, items: Items, index: int | None = None
) -> TextEdit:
    """Insert new ``key = value`` items into a block (or the file top level).

    Args:
        doc: The document.
        parent: Where to insert.
        items: New content.
        index: Position among the parent's items (default: at the end).
    """
    text = doc.text
    unit = indent_unit(text)
    nl = newline_of(text)
    children = parent.items
    index = len(children) if index is None else index
    if isinstance(parent, Document):
        depth = 0
        if index < len(children):
            at = _line_start(text, children[index].start)
            return TextEdit(at, at, render_items(items, unit, depth, nl))
        tail = text.rstrip(" \t")
        prefix = "" if not tail or tail.endswith(("\n", "\r")) else nl
        return TextEdit(len(text), len(text), prefix + render_items(items, unit, depth, nl))
    depth = _depth(doc, parent, unit) + 1
    if index < len(children):
        anchor = children[index]
        if _line_start(text, anchor.start) != _line_start(text, parent.lbrace.start):
            at = _line_start(text, anchor.start)
            return TextEdit(at, at, render_items(items, unit, depth, nl))
        rendered = " ".join(f"{k} = {render_value(v, unit, depth, nl)}" for k, v in items)
        return TextEdit(anchor.start, anchor.start, rendered + " ")
    # At the end: before the closing brace.
    if parent.rbrace is None:
        return TextEdit(len(text), len(text), nl + render_items(items, unit, depth, nl))
    rb = parent.rbrace.start
    same_line = _line_start(text, rb) == _line_start(text, parent.lbrace.start)
    if same_line:
        # "{ a = 1 }" -> "{ a = 1 b = 2 }"; empty "{ }" too
        rendered = " ".join(f"{k} = {render_value(v, unit, depth, nl)}" for k, v in items)
        before = text[rb - 1] if rb > 0 else ""
        return TextEdit(rb, rb, ("" if before == " " else " ") + rendered + " ")
    at = _line_start(text, rb)
    return TextEdit(at, at, render_items(items, unit, depth, nl))


# -- buffer with undo / redo ---------------------------------------------------------
@dataclass
class Buffer:
    """Text of one file in an editor, with undo and redo.

    Attributes:
        text: Current text.
    """

    text: str
    _undo: list[str] = field(default_factory=list, repr=False)
    _redo: list[str] = field(default_factory=list, repr=False)
    _doc: Document | None = field(default=None, repr=False)

    @property
    def document(self) -> Document:
        """The current text, parsed (cached until the next change)."""
        if self._doc is None or self._doc.text != self.text:
            self._doc = parse_text(self.text)
        return self._doc

    def apply(self, edits: TextEdit | Iterable[TextEdit]) -> Document:
        """Apply edits as one undoable step and return the new document."""
        batch = [edits] if isinstance(edits, TextEdit) else list(edits)
        new = apply_edits(self.text, batch)
        if new != self.text:
            self._undo.append(self.text)
            self._redo.clear()
            self.text = new
        return self.document

    def replace_all(self, text: str) -> Document:
        """Replace the whole text (typing in the code view) as one undoable step."""
        return self.apply(TextEdit(0, len(self.text), text))

    def undo(self) -> bool:
        """Go one step back; ``False`` if there is nothing to undo."""
        if not self._undo:
            return False
        self._redo.append(self.text)
        self.text = self._undo.pop()
        return True

    def redo(self) -> bool:
        """Repeat an undone step; ``False`` if there is nothing to redo."""
        if not self._redo:
            return False
        self._undo.append(self.text)
        self.text = self._redo.pop()
        return True
