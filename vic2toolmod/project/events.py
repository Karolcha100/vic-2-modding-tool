"""Event ids: free ids for new events (K29)."""

from __future__ import annotations

import re

from vic2toolmod.project.registries import Registries

_RANGE = re.compile(r"events?\b[^\d\n]*?(\d+)\s*[-–]\s*(\d+)", re.IGNORECASE)
MAX_ID = 2**31 - 1
"""The game stores event ids as 32-bit numbers; larger ids are not safe."""


def declared_range(text: str) -> tuple[int, int] | None:
    """The id range a file declares in a comment, e.g. ``### Events 95260-95320 used``.

    Only comments before the first event are looked at.
    """
    head = text.split("_event", 1)[0]
    for line in head.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and (m := _RANGE.search(stripped)):
            lo, hi = int(m[1]), int(m[2])
            return (lo, hi) if lo <= hi else (hi, lo)
    return None


def used_ids(registries: Registries) -> set[int]:
    """All numeric event ids defined in the project (only those the game can store)."""
    return {int(k) for k in registries.names.get("event", {}) if k.isdigit() and int(k) <= MAX_ID}


def next_free_id(
    registries: Registries,
    file_text: str | None = None,
    taken: set[int] | frozenset[int] = frozenset(),
) -> int:
    """A free event id for a new event.

    With ``file_text`` whose header declares a range (``### Events 95260-95320
    used``), the lowest unused id in that range is returned. Otherwise (or when
    the range is full) the highest id in the project + 1. ``taken`` are ids
    already handed out but not yet written (several new events at once).
    """
    used = used_ids(registries) | taken
    if file_text is not None and (rng := declared_range(file_text)):
        for candidate in range(rng[0], rng[1] + 1):
            if candidate not in used:
                return candidate
    return max(used, default=0) + 1
