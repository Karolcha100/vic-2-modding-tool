"""Elements of the game's interface windows (``interface/*.gui``), K80.

A ``.gui`` file nests ``windowType`` blocks holding elements such as
``iconType`` (a picture), ``instantTextBoxType`` (a text), ``guiButtonType``,
``listboxType``, ``checkboxType`` … Each has a ``name``, a ``position``
relative to its parent and often a ``size``; pictures name a sprite of
``interface/*.gfx``. This module reads a window as a tree of `Element` so the
GUI can draw it: as outlines with names and texts, or with the real pictures.

Positions are relative to the parent; ``orientation`` moves the origin to a
corner or the centre of the parent (`ANCHORS`), as the game does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from vic2toolmod.script.cst import Assignment, Block, Document, Node, Scalar
from vic2toolmod.workspace import Workspace

#: Orientation -> fraction of the parent's size where the child's origin is.
ANCHORS: dict[str, tuple[float, float]] = {
    "upper_left": (0, 0),
    "upper_right": (1, 0),
    "lower_left": (0, 1),
    "lower_right": (1, 1),
    "center": (0.5, 0.5),
    "centre": (0.5, 0.5),
    "center_up": (0.5, 0),
    "center_down": (0.5, 1),
    "center_left": (0, 0.5),
    "center_right": (1, 0.5),
}

_SPRITE_KEYS = ("spritetype", "quadtexturesprite", "background")


@dataclass
class Element:
    """One element of a window.

    Attributes:
        kind: Block key in lower case (``windowtype``, ``icontype`` …).
        name: ``name`` of the element.
        x, y: ``position`` relative to the parent (before the orientation).
        w, h: ``size`` (0 when not given; pictures then have their sprite's size).
        orientation: Lower-case ``orientation`` (``upper_left`` when absent).
        sprite: Sprite name (``spriteType`` / ``quadTextureSprite`` / ``background``).
        text: Text or localisation key (``text`` / ``buttonText``).
        font: Font name.
        max_w, max_h: ``maxWidth`` / ``maxHeight`` of text boxes.
        format: Text alignment (``left``, ``centre``, ``right``).
        line: Line in the ``.gui`` file.
        children: Nested elements.
    """

    kind: str
    name: str
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    orientation: str = "upper_left"
    sprite: str = ""
    text: str = ""
    font: str = ""
    max_w: int = 0
    max_h: int = 0
    format: str = ""
    line: int = 0
    children: list[Element] = field(default_factory=list)


def _scalar(block: Block, key: str) -> str:
    for a in block.assignments():
        if a.key_text.lower() == key and isinstance(a.value, Scalar):
            return a.value.value
    return ""


def _int(text: str) -> int:
    try:
        return int(float(text))
    except ValueError:
        return 0


def _xy(block: Block, key: str) -> tuple[int, int]:
    for a in block.assignments():
        if a.key_text.lower() == key and isinstance(a.value, Block):
            return _int(_scalar(a.value, "x")), _int(_scalar(a.value, "y"))
    return 0, 0


def element(doc: Document, node: Assignment) -> Element:
    """The element an assignment such as ``iconType = { … }`` describes."""
    assert isinstance(node.value, Block)
    b = node.value
    x, y = _xy(b, "position")
    w, h = _xy(b, "size")
    sprite = next((v for k in _SPRITE_KEYS if (v := _scalar(b, k))), "")
    e = Element(
        kind=node.key_text.lower(),
        name=_scalar(b, "name"),
        x=x,
        y=y,
        w=w,
        h=h,
        orientation=(_scalar(b, "orientation") or "upper_left").lower(),
        sprite=sprite,
        text=_scalar(b, "text") or _scalar(b, "buttontext"),
        font=_scalar(b, "font") or _scalar(b, "buttonfont"),
        max_w=_int(_scalar(b, "maxwidth")),
        max_h=_int(_scalar(b, "maxheight")),
        format=_scalar(b, "format").lower(),
        line=doc.position(node.start)[0],
    )
    for child in b.items:
        if isinstance(child, Assignment) and isinstance(child.value, Block):
            if child.key_text.lower() in ("position", "size", "bordersize"):
                continue
            e.children.append(element(doc, child))
    return e


def find(doc: Document, name: str, kind: str = "windowtype") -> Assignment | None:
    """The first block of a kind with the given name, anywhere in a document."""
    stack: list[Node] = list(reversed(doc.items))
    while stack:
        n = stack.pop()
        if isinstance(n, Assignment) and isinstance(n.value, Block):
            if n.key_text.lower() == kind and _scalar(n.value, "name") == name:
                return n
            stack.extend(reversed(n.value.items))
    return None


def backdrop(ws: Workspace, rel: str, name: str) -> list[Element]:
    """Pictures of the window that holds window ``name`` (its background).

    Positions are made relative to window ``name`` (the parent's pictures are
    drawn behind it in the game, e.g. the politics panel behind the reforms).
    """
    f = ws.file(rel)
    if f is None:
        return []
    doc = ws.document(f.rel)
    stack: list[tuple[Node, Assignment | None]] = [(n, None) for n in reversed(doc.items)]
    while stack:
        n, parent = stack.pop()
        if not (isinstance(n, Assignment) and isinstance(n.value, Block)):
            continue
        if n.key_text.lower() == "windowtype" and _scalar(n.value, "name") == name:
            if parent is None:
                return []
            assert isinstance(parent.value, Block)
            x, y = _xy(n.value, "position")
            out = []
            for c in parent.value.items:
                if (
                    isinstance(c, Assignment)
                    and isinstance(c.value, Block)
                    and c.key_text.lower() == "icontype"
                ):
                    e = element(doc, c)
                    e.x -= x
                    e.y -= y
                    out.append(e)
            return out
        is_window = n.key_text.lower() == "windowtype"
        stack.extend((c, n if is_window else parent) for c in reversed(n.value.items))
    return []


def read_window(ws: Workspace, rel: str, name: str) -> Element:
    """A window of a ``.gui`` file as a tree.

    Raises:
        ValueError: If the file or the window does not exist.
    """
    f = ws.file(rel)
    if f is None:
        raise ValueError(f"{rel} not found")
    doc = ws.document(f.rel)
    node = find(doc, name)
    if node is None:
        raise ValueError(f"window {name!r} not found in {rel}")
    return element(doc, node)


def sprites_of(e: Element) -> set[str]:
    """Every sprite name used in a tree."""
    out = {e.sprite} if e.sprite else set()
    for c in e.children:
        out |= sprites_of(c)
    return out


def texture_size(path: Path) -> tuple[int, int] | None:
    """Width and height of a DDS or Targa file from its header (``None`` if unknown)."""
    try:
        with path.open("rb") as fh:
            head = fh.read(20)
    except OSError:
        return None
    if head[:4] == b"DDS " and len(head) >= 20:
        return int.from_bytes(head[16:20], "little"), int.from_bytes(head[12:16], "little")
    if len(head) >= 16 and head[2] in (2, 10):
        return int.from_bytes(head[12:14], "little"), int.from_bytes(head[14:16], "little")
    return None
