"""Census of keys actually used in game and mod files.

Walks every script file, normalises dynamic keys (numbers, dates, quoted
strings) and counts how often each *key path* appears, per file category.
Used to write and check the schema: whatever vanilla uses is valid.
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from vic2toolmod.files import iter_script_files
from vic2toolmod.script.cst import Assignment, Block, Node, Scalar
from vic2toolmod.script.parser import parse_file

_INT = re.compile(r"-?\d+")
_DATE = re.compile(r"\d+\.\d+\.\d+")
_FLOAT = re.compile(r"-?\d*\.\d+")

#: Top-level folders whose files are grouped by sub-folder rather than by file.
_GROUP_BY_DIR = {"events", "decisions", "units", "poptypes", "technologies", "inventions", "news"}


def category_of(path: Path, root: Path) -> str:
    """File category used in the census, e.g. ``events/*`` or ``common/issues.txt``.

    Args:
        path: The file.
        root: The game or mod folder it belongs to.
    """
    parts = path.relative_to(root).parts
    if len(parts) == 1:
        return parts[0]
    top = parts[0].lower()
    if top in _GROUP_BY_DIR:
        return f"{top}/*"
    if top == "history":
        return f"history/{parts[1].lower()}/*" if len(parts) > 2 else "/".join(parts)
    if top == "common" and len(parts) > 2:
        return f"common/{parts[1].lower()}/*"
    if top == "interface":
        return f"interface/*{path.suffix.lower()}"
    return "/".join(p.lower() for p in parts)


def normalise_key(key: str) -> str:
    """Replace dynamic keys by placeholders: ``<int>``, ``<date>``, ``<float>``, ``<string>``."""
    if key.startswith('"'):
        return "<string>"
    if _DATE.fullmatch(key):
        return "<date>"
    if _INT.fullmatch(key):
        return "<int>"
    if _FLOAT.fullmatch(key):
        return "<float>"
    return key.lower()


def value_kind(value: Node | None) -> str:
    """``block``, ``int``, ``float``, ``date``, ``yes/no``, ``string``, ``word`` or ``missing``."""
    if value is None:
        return "missing"
    if isinstance(value, Block):
        return "block"
    assert isinstance(value, Scalar)
    text = value.text
    if value.quoted:
        return "string"
    if text.lower() in ("yes", "no"):
        return "yes/no"
    if _DATE.fullmatch(text):
        return "date"
    if _INT.fullmatch(text):
        return "int"
    if _FLOAT.fullmatch(text):
        return "float"
    return "word"


@dataclass
class PathStats:
    """Statistics of one key path in one category."""

    count: int = 0
    files: set[str] = field(default_factory=set)
    kinds: Counter[str] = field(default_factory=Counter)
    values: Counter[str] = field(default_factory=Counter)
    example: str = ""


@dataclass
class Census:
    """Counts of key paths per category.

    Attributes:
        max_depth: Paths deeper than this are cut (the rest is counted under ``…``).
        stats: ``(category, path) -> PathStats``; ``path`` is keys joined by `` > ``.
        loose_values: ``(category, parent path) -> number of loose values``.
    """

    max_depth: int = 6
    stats: dict[tuple[str, str], PathStats] = field(default_factory=lambda: defaultdict(PathStats))
    loose_values: Counter[tuple[str, str]] = field(default_factory=Counter)

    def add_file(self, path: Path, root: Path) -> None:
        """Parse a file and add its key paths."""
        category = category_of(path, root)
        doc, _ = parse_file(path)
        rel = str(path.relative_to(root))
        stack: list[tuple[list[Node], tuple[str, ...]]] = [(doc.items, ())]
        while stack:
            items, prefix = stack.pop()
            for item in items:
                if isinstance(item, Assignment):
                    key = normalise_key(item.key.text)
                    keys = (*prefix, key) if len(prefix) < self.max_depth else (*prefix, "…")
                    st = self.stats[(category, " > ".join(keys))]
                    st.count += 1
                    st.files.add(rel)
                    kind = value_kind(item.value)
                    st.kinds[kind] += 1
                    if isinstance(item.value, Scalar) and len(st.values) < 200:
                        st.values[item.value.text] += 1
                    if not st.example:
                        st.example = f"{rel}:{doc.position(item.start)[0]}"
                    if isinstance(item.value, Block) and len(prefix) < self.max_depth:
                        stack.append((item.value.items, keys))
                elif isinstance(item, Scalar):
                    self.loose_values[(category, " > ".join(prefix))] += 1
                elif isinstance(item, Block):
                    stack.append((item.items, (*prefix, "{}")))

    def add_roots(self, roots: Iterable[Path], exclude: Iterable[Path] = ()) -> int:
        """Add every script file under the given game / mod folders.

        Args:
            roots: Folders; each file's category is computed relative to its root.
            exclude: Folders to skip (e.g. the game's ``mod`` folder).

        Returns:
            Number of files added.
        """
        excluded = [Path(e) for e in exclude]
        n = 0
        for root in roots:
            for path in iter_script_files([root]):
                if any(path.is_relative_to(e) for e in excluded):
                    continue
                self.add_file(path, root)
                n += 1
        return n

    def write_csv(self, out: TextIO, max_depth: int | None = None) -> None:
        """Write the census as CSV (sorted by category and path)."""
        writer = csv.writer(out)
        writer.writerow(
            ["category", "path", "depth", "count", "files", "kinds", "top_values", "example"]
        )
        for (category, path), st in sorted(self.stats.items()):
            depth = path.count(" > ") + 1
            if max_depth is not None and depth > max_depth:
                continue
            kinds = " ".join(f"{k}:{v}" for k, v in st.kinds.most_common())
            values = " ".join(v for v, _ in st.values.most_common(5))
            writer.writerow(
                [category, path, depth, st.count, len(st.files), kinds, values, st.example]
            )
