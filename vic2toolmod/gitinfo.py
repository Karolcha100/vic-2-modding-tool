"""Read-only git information about the mod folder (K37 = B: show what changed)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitStatus:
    """State of the mod's git repository.

    Attributes:
        repo: Whether the mod folder is a git repository.
        branch: Current branch (``""`` if unknown).
        changed: ``(status, path)`` from ``git status --porcelain`` (``M``, ``A``, ``??`` …).
        error: Message if git could not be run.
    """

    repo: bool
    branch: str = ""
    changed: tuple[tuple[str, str], ...] = ()
    error: str = ""


def _git(folder: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(folder), *args],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def status(folder: Path) -> GitStatus:
    """Branch and changed files of the repository in ``folder``."""
    try:
        inside = _git(folder, "rev-parse", "--is-inside-work-tree")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GitStatus(False, error=str(exc))
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return GitStatus(False)
    branch = _git(folder, "branch", "--show-current").stdout.strip()
    lines = _git(folder, "status", "--porcelain=v1", "--untracked-files=all").stdout.splitlines()
    changed = tuple((line[:2].strip() or "?", line[3:]) for line in lines if len(line) > 3)
    return GitStatus(True, branch, changed)


def diff(folder: Path, rel: str) -> str:
    """``git diff`` of one file (tracked files; new files are shown whole)."""
    out = _git(folder, "diff", "--", rel).stdout
    if out:
        return out
    path = folder / rel
    if path.is_file() and _git(folder, "ls-files", "--error-unmatch", "--", rel).returncode != 0:
        text = path.read_bytes().decode("latin-1")
        return "".join(f"+{line}\n" for line in text.splitlines())
    return ""
