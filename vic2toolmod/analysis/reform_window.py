"""Reform window editor (K60, K69 = A): layout of ``reforms_window``.

In ``interface/country_politics.gui`` the window ``reforms_window`` holds one
``windowType`` per issue, named after the issue (``slavery``, ``wage_reform``)
with a ``position`` (relative to the window) and a ``size``. An issue without
such an element does not appear in the game's reform screen, and the screen
cannot scroll, so every reform must fit in the window.

This module

* reads the layout (`read_layout`): window size, each issue's box, issues of
  ``political_reforms`` / ``social_reforms`` without a box, boxes that match
  no issue, boxes outside the window;
* computes an automatic grid for a category (`grid`);
* plans the changes (`plan_layout`): new positions as minimal edits, and new
  boxes for missing issues copied from a box of the same category.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from vic2toolmod.changes import FileChange
from vic2toolmod.edit import TextEdit, apply_edits, insert_after, set_value
from vic2toolmod.script.cst import Assignment, Block, Document, Node, Scalar
from vic2toolmod.workspace import Workspace

GUI_FILE = "interface/country_politics.gui"
WINDOW = "reforms_window"
SHOWN = ("political_reforms", "social_reforms")
"""Issue categories the reform screen of civilised countries shows."""


@dataclass
class Box:
    """One element of the reform window.

    Attributes:
        name: Element name (an issue name for issue boxes).
        x, y: Position relative to the window.
        w, h: Size (``0`` if the element has none).
        category: Issue category (``None`` if the name is no issue).
        line: 1-based line of the element in the ``.gui`` file.
        outside: Whether the box starts outside the window (not visible).
        clipped: Whether the box (with its declared size) sticks out of the window.
    """

    name: str
    x: int
    y: int
    w: int
    h: int
    category: str | None
    line: int
    outside: bool = False
    clipped: bool = False


@dataclass
class Layout:
    """The reform window as the game sees it."""

    file: str
    width: int
    height: int
    boxes: list[Box] = field(default_factory=list)
    missing: dict[str, list[str]] = field(default_factory=dict)
    """Category -> issues of that category without a box."""
    unknown: list[str] = field(default_factory=list)
    """Boxes (windowType) whose name is no issue."""


def _scalar(block: Block, key: str) -> str | None:
    a = block.find(key)
    return a.value.value if a is not None and isinstance(a.value, Scalar) else None


def _xy(block: Block, key: str) -> tuple[int, int]:
    a = block.find(key)
    if a is None or not isinstance(a.value, Block):
        return 0, 0
    vals = {}
    for k in ("x", "y"):
        v = _scalar(a.value, k)
        try:
            vals[k] = int(float(v)) if v is not None else 0
        except ValueError:
            vals[k] = 0
    return vals["x"], vals["y"]


def _find_window(items: list[Node], name: str) -> Assignment | None:
    stack = list(items)
    while stack:
        n = stack.pop()
        if isinstance(n, Assignment) and isinstance(n.value, Block):
            if _scalar(n.value, "name") == name:
                return n
            stack.extend(n.value.items)
    return None


def issue_categories(ws: Workspace) -> dict[str, list[str]]:
    """Category -> issues in ``common/issues.txt`` order."""
    out: dict[str, list[str]] = {}
    doc = ws.document("common/issues.txt")
    for cat in doc.items:
        if isinstance(cat, Assignment) and isinstance(cat.value, Block):
            out[cat.key_text] = [
                i.key_text
                for i in cat.value.items
                if isinstance(i, Assignment) and isinstance(i.value, Block)
            ]
    return out


def _window(ws: Workspace) -> tuple[Document, Assignment]:
    f = ws.file(GUI_FILE)
    if f is None:
        raise ValueError(f"{GUI_FILE} not found")
    doc = ws.document(f.rel)
    win = _find_window(doc.items, WINDOW)
    if win is None or not isinstance(win.value, Block):
        raise ValueError(f"window {WINDOW!r} not found in {GUI_FILE}")
    return doc, win


def read_layout(ws: Workspace) -> Layout:
    """Read the reform window and compare it with the issues."""
    doc, win = _window(ws)
    assert isinstance(win.value, Block)
    width, height = _xy(win.value, "size")
    cats = issue_categories(ws)
    category_of = {i: c for c, issues in cats.items() for i in issues}
    layout = Layout(GUI_FILE, width, height)
    for child in win.value.items:
        if not (isinstance(child, Assignment) and child.key_text.lower() == "windowtype"):
            continue
        assert isinstance(child.value, Block)
        name = _scalar(child.value, "name") or ""
        x, y = _xy(child.value, "position")
        w, h = _xy(child.value, "size")
        box = Box(name, x, y, w, h, category_of.get(name), doc.position(child.start)[0])
        box.outside = x < 0 or y < 0 or x >= width or y >= height
        box.clipped = not box.outside and (x + w > width or y + h > height)
        layout.boxes.append(box)
        if box.category is None:
            layout.unknown.append(name)
    present = {b.name for b in layout.boxes}
    for cat in SHOWN:
        missing = [i for i in cats.get(cat, []) if i not in present]
        if missing:
            layout.missing[cat] = missing
    return layout


def grid(
    issues: list[str],
    *,
    origin: tuple[int, int],
    columns: int,
    cell: tuple[int, int],
) -> dict[str, tuple[int, int]]:
    """Positions for issues laid out row by row in a grid.

    Args:
        issues: Issues in display order.
        origin: Top-left corner of the grid (window coordinates).
        columns: Number of columns.
        cell: Width and height of one cell (box spacing).
    """
    ox, oy = origin
    cw, ch = cell
    return {
        name: (ox + (n % columns) * cw, oy + (n // columns) * ch) for n, name in enumerate(issues)
    }


def plan_layout(
    ws: Workspace,
    positions: dict[str, tuple[int, int]],
    *,
    add_missing: bool = True,
) -> FileChange:
    """Plan the new layout as a change of the ``.gui`` file (in the mod).

    Args:
        ws: The workspace.
        positions: Issue (box name) -> new position. Missing issues listed
            here get a new box copied from a box of the same category.
        add_missing: Create boxes for issues in ``positions`` that have none.
    """
    if ws.project.mod_dir is None:
        raise ValueError("a mod folder is needed")
    doc, win = _window(ws)
    assert isinstance(win.value, Block)
    layout = read_layout(ws)
    by_name: dict[str, Assignment] = {}
    for child in win.value.items:
        if isinstance(child, Assignment) and isinstance(child.value, Block):
            name = _scalar(child.value, "name")
            if name:
                by_name[name] = child
    edits: list[TextEdit] = []
    for name, (x, y) in positions.items():
        box = by_name.get(name)
        if box is None:
            continue
        assert isinstance(box.value, Block)
        pos = box.value.find("position")
        if pos is not None:
            edits.append(set_value(doc, pos, [("x", str(x)), ("y", str(y))]))
    new_boxes: list[str] = []
    if add_missing:
        missing = {i: c for c, issues in layout.missing.items() for i in issues}
        for name, (x, y) in positions.items():
            cat = missing.get(name)
            if cat is None:
                continue
            template = next((b for b in layout.boxes if b.category == cat), None)
            if template is None:
                continue
            new_boxes.append(_clone(by_name[template.name], template.name, name, x, y))
    text = apply_edits(doc.text, edits)
    if new_boxes:
        doc2 = _reparse(text)
        win2 = _find_window(doc2.items, WINDOW)
        assert win2 is not None and isinstance(win2.value, Block)
        last = [c for c in win2.value.items if isinstance(c, Assignment)][-1]
        nl = "\r\n" if "\r\n" in text else "\n"
        insert = insert_after(doc2, last, [])
        indent = re.match(r"[ \t]*", text[text.rfind("\n", 0, last.start) + 1 :]).group()  # type: ignore[union-attr]
        blob = "".join(nl + indent + b.strip() + nl for b in new_boxes)
        text = apply_edits(text, [TextEdit(insert.start, insert.start, blob)])
    f = ws.file(GUI_FILE)
    assert f is not None
    return FileChange(f.rel, ws.project.mod_dir / f.rel, doc.text, text, ws.encoding(f.rel))


def _reparse(text: str) -> Document:
    from vic2toolmod.script.parser import parse_text

    return parse_text(text)


def _clone(box: Assignment, old: str, new: str, x: int, y: int) -> str:
    """Text of a copy of a box with another name and position (without comments above it)."""
    text = box.to_text()[len(box.key.leading) :].strip()
    text = re.sub(rf'(name\s*=\s*)"?{re.escape(old)}"?', rf'\1"{new}"', text, count=1)
    return re.sub(r"position\s*=\s*\{[^}]*\}", f"position = {{ x = {x} y = {y} }}", text, count=1)
