"""Finding script files in game and mod folders."""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from pathlib import Path

SCRIPT_SUFFIXES = frozenset({".txt", ".gfx", ".gui", ".mod", ".map"})
"""File suffixes that use Paradox script syntax (``.lua`` and ``.csv`` do not)."""


def iter_script_files(
    paths: Iterable[str | Path], suffixes: frozenset[str] = SCRIPT_SUFFIXES
) -> Iterator[Path]:
    """Yield script files under the given files / folders, sorted per folder.

    Symbolic links to folders are followed (the game's ``mod/RPM`` may be a
    link), but every real folder is visited only once.

    Args:
        paths: Files or folders to search.
        suffixes: Lower-case suffixes to accept.

    Yields:
        Paths of matching files.
    """
    seen: set[str] = set()
    for root in paths:
        root = Path(root)
        if root.is_file():
            yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
            real = os.path.realpath(dirpath)
            if real in seen:
                dirnames[:] = []
                continue
            seen.add(real)
            dirnames.sort()
            for name in sorted(filenames):
                if os.path.splitext(name)[1].lower() in suffixes:
                    yield Path(dirpath) / name
