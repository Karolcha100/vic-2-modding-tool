"""Output forms of a tree: original text, language-neutral data, readable outline."""

from __future__ import annotations

from typing import Any

from vic2toolmod.script.cst import Assignment, Block, Document, ErrorNode, Node, Scalar


def to_text(node: Node) -> str:
    """Print a node (or a whole `Document`) back to text, losslessly."""
    return node.to_text()


def to_data(node: Node) -> Any:
    """Convert a tree to plain JSON-compatible data.

    The format is independent of Python and is used by the test fixtures in
    ``tests/fixtures/script/`` (so that a port to another language can reuse
    them). Trivia and positions are left out; see ``docs/script-syntax.md``.
    """
    if isinstance(node, Document):
        return [to_data(item) for item in node.items]
    if isinstance(node, Assignment):
        return {
            "type": "assignment",
            "key": node.key.text,
            "op": node.operator.text,
            "value": None if node.value is None else to_data(node.value),
        }
    if isinstance(node, Scalar):
        return {"type": "scalar", "text": node.text}
    if isinstance(node, Block):
        data: dict[str, Any] = {"type": "block", "items": [to_data(i) for i in node.items]}
        if node.rbrace is None:
            data["closed"] = False
        return data
    if isinstance(node, ErrorNode):
        return {"type": "error", "tokens": [t.text for t in node.error_tokens]}
    raise TypeError(f"unknown node {node!r}")  # pragma: no cover


def diagnostics_data(doc: Document) -> list[dict[str, Any]]:
    """Diagnostics of a document as JSON-compatible data with line/column."""
    out = []
    for d in doc.diagnostics:
        line, col = doc.position(d.start)
        out.append({"severity": d.severity.value, "code": d.code, "line": line, "column": col})
    return out


def outline(doc: Document, indent: str = "  ") -> str:
    """A compact, human-readable outline of the tree (one node per line)."""
    lines: list[str] = []
    # Iterative walk: (items, next index, depth) frames instead of recursion.
    stack: list[tuple[list[Node], int, int]] = [(doc.items, 0, 0)]
    while stack:
        items, index, depth = stack.pop()
        if index >= len(items):
            continue
        stack.append((items, index + 1, depth))
        item = items[index]
        pad = indent * depth
        line_no = doc.position(item.start)[0]
        if isinstance(item, Assignment):
            head = f"{pad}{item.key.text} {item.operator.text}"
            if isinstance(item.value, Block):
                closed = "" if item.value.rbrace else "  !! unclosed"
                lines.append(f"{line_no:>6}  {head} {{{closed}")
                stack.append((item.value.items, 0, depth + 1))
            elif item.value is None:
                lines.append(f"{line_no:>6}  {head}  !! missing value")
            else:
                lines.append(f"{line_no:>6}  {head} {item.value.text}")
        elif isinstance(item, Block):
            closed = "" if item.rbrace else "  !! unclosed"
            lines.append(f"{line_no:>6}  {pad}{{{closed}")
            stack.append((item.items, 0, depth + 1))
        elif isinstance(item, Scalar):
            lines.append(f"{line_no:>6}  {pad}{item.text}")
        elif isinstance(item, ErrorNode):
            texts = " ".join(t.text for t in item.error_tokens)
            lines.append(f"{line_no:>6}  {pad}!! {texts}")
    return "\n".join(lines)
