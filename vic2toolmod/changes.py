"""Planned changes to files: preview as a diff, write with a backup (K36 = C)."""

from __future__ import annotations

import difflib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from vic2toolmod import textio


@dataclass(frozen=True)
class FileChange:
    """New content for one file (``old_text`` is ``None`` for a new file).

    Attributes:
        rel: Relative path in the mod.
        path: Where the file will be written.
        old_text: Current text (``None`` if the file does not exist yet).
        new_text: Text after the change.
        encoding: Encoding to write.
    """

    rel: str
    path: Path
    old_text: str | None
    new_text: str
    encoding: textio.Encoding = textio.Encoding.CP1252


def diff(changes: list[FileChange], context: int = 2) -> str:
    """Unified diff of all changes (line breaks normalised for display)."""
    out: list[str] = []
    for c in changes:
        old = (c.old_text or "").replace("\r\n", "\n").splitlines(keepends=True)
        new = c.new_text.replace("\r\n", "\n").splitlines(keepends=True)
        out += difflib.unified_diff(
            old,
            new,
            f"a/{c.rel}" if c.old_text is not None else "/dev/null",
            f"b/{c.rel}",
            n=context,
        )
    return "".join(out)


def backup_dir() -> Path:
    """Folder for backups: ``~/.local/share/vic2toolmod/backups/<timestamp>``."""
    return (
        Path.home()
        / ".local"
        / "share"
        / "vic2toolmod"
        / "backups"
        / time.strftime("%Y%m%d-%H%M%S")
    )


def write_changes(changes: list[FileChange], backup: bool = True) -> Path | None:
    """Write the files; existing ones are copied to a backup folder first.

    All texts are encoded before anything is written, so an encoding error
    (e.g. a Polish letter in a Windows-1252 file) changes nothing.

    Returns:
        The backup folder, if any file was backed up.
    """
    encoded = [(c, textio.encode(c.new_text, c.encoding)) for c in changes]
    target = backup_dir() if backup else None
    used = False
    for c, data in encoded:
        if target is not None and c.path.exists():
            dest = target / c.rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(c.path, dest)
            used = True
        c.path.parent.mkdir(parents=True, exist_ok=True)
        c.path.write_bytes(data)
    return target if used else None
