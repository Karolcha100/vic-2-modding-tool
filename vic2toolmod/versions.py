"""Versions of the mod: save the whole mod under a name, list, compare, go back (T025).

A *version* is the state of every file of the mod folder at one moment. Where
it is kept depends on the mod (K95 = C):

- **git** - the mod folder is a git repository (RPM is): a version is a commit
  of all changes (``git add -A``) with the name as its message; the list is
  the branch's history (commits made outside the tool are versions too). Only
  changes are stored; nothing is pushed.
- **copies** - no repository (or no git): a version is a zip of the whole mod
  folder in ``~/.local/share/vic2toolmod/versions/<mod>-<hash>/`` with an
  ``index.json`` of names and dates.

*Going to a version* (K96 = A) makes the files on disk what they were in that
version, as a new state: the current state is saved first (an automatic
version) when it differs from the last one, so nothing is lost and going
"forward" again is going to another version of the list. In git this is
``git restore --source`` of the whole tree (files added later are removed)
and a commit; with copies the zip is unpacked over the folder (files that
were not in it are removed). ``.git`` is never touched.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
import zipfile
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: Marks the commits the tool makes (the GUI shows them as "saved here").
_TRAILER = "Saved-with: vic2toolmod"
_AUTO = "Automatic: before going to"


class VersionError(Exception):
    """A version cannot be saved / found / restored (the message says why)."""


@dataclass
class Version:
    """One saved version.

    Attributes:
        id: Commit hash or the zip's stem.
        name: First line of the message / the name given.
        description: The rest of the message.
        date: ISO time.
        files: Files changed since the previous version (git) or files in the copy.
        auto: Saved automatically before going to another version.
        current: The files on disk are this version (the newest one with no changes since).
    """

    id: str
    name: str
    description: str = ""
    date: str = ""
    files: int = 0
    auto: bool = False
    current: bool = False


@dataclass
class Info:
    """How the mod's versions are kept and the list (newest first)."""

    kind: str  # "git" | "copies"
    where: str
    versions: list[Version] = field(default_factory=list)
    changed: int = 0  # files changed since the newest version
    note: str = ""


def _git(folder: Path, *args: str, check: bool = True) -> str:
    try:
        r = subprocess.run(
            # files go in and out byte for byte (the game reads them as they are)
            ["git", "-C", str(folder), "-c", "core.autocrlf=false", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VersionError(f"git: {exc}") from exc
    if check and r.returncode != 0:
        raise VersionError(f"git {args[0]}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout


def uses_git(folder: Path) -> bool:
    """The mod folder is the top of a git repository and git runs."""
    try:
        top = _git(folder, "rev-parse", "--show-toplevel", check=False).strip()
    except VersionError:
        return False
    return bool(top) and Path(top).resolve() == folder.resolve()


class GitVersions:
    """Versions as commits of the mod's own repository."""

    kind = "git"

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def _changed(self) -> list[str]:
        out = _git(self.folder, "status", "--porcelain=v1", "--untracked-files=all")
        return [line[3:] for line in out.splitlines() if len(line) > 3]

    def info(self, limit: int = 200) -> Info:
        """The list of versions (newest first) and how many files changed since the newest."""
        branch = _git(self.folder, "branch", "--show-current", check=False).strip()
        has_head = _git(self.folder, "rev-parse", "--verify", "-q", "HEAD", check=False).strip()
        versions: list[Version] = []
        if has_head:
            out = _git(
                self.folder,
                "log",
                f"-n{limit}",
                "--shortstat",
                "--format=%x1e%H%x1f%aI%x1f%s%x1f%b%x1f",
            )
            for chunk in out.split("\x1e")[1:]:
                parts = chunk.split("\x1f")
                h, date, subject, body = parts[0], parts[1], parts[2], parts[3]
                stat = parts[4] if len(parts) > 4 else ""
                files = int(stat.split()[0]) if stat.split() and stat.split()[0].isdigit() else 0
                desc = "\n".join(
                    line for line in body.strip().splitlines() if line.strip() != _TRAILER
                ).strip()
                versions.append(
                    Version(h, subject, desc, date, files, auto=subject.startswith(_AUTO))
                )
        changed = len(self._changed())
        if versions and not changed:
            versions[0].current = True
        return Info("git", f"git repository of the mod (branch {branch or '?'})", versions, changed)

    def save(self, name: str, description: str = "") -> Version:
        """Save every change of the mod as a new version (a commit)."""
        if not self._changed():
            raise VersionError("nothing changed since the last version")
        _git(self.folder, "add", "-A")
        message = name.strip() + "\n\n" + (description.strip() + "\n\n" if description else "")
        _git(self.folder, "commit", "-q", "-m", message + _TRAILER)
        return self.info(1).versions[0]

    def files(self, vid: str) -> list[tuple[str, str]]:
        """``(status, path)`` changed by a version (against the one before it)."""
        out = _git(self.folder, "show", "--name-status", "--format=", "--no-renames", vid)
        return [_status_line(line) for line in out.splitlines() if "\t" in line]

    def compare(self, vid: str) -> list[tuple[str, str]]:
        """``(status, path)`` that differ between a version and the files now."""
        out = _git(self.folder, "diff", "--name-status", "--no-renames", vid)
        found = [_status_line(line) for line in out.splitlines() if "\t" in line]
        untracked = _git(self.folder, "ls-files", "--others", "--exclude-standard")
        return found + [("A", p) for p in untracked.splitlines() if p]

    def restore(self, vid: str, name: str) -> Version | None:
        """Make the files what they were in version ``vid`` (current state saved first).

        Returns the new version that records it, or None when nothing changed.
        """
        if self._changed():
            self.save(f"{_AUTO} {name}")
        # the whole tree as in that version; files it did not have are removed
        _git(self.folder, "restore", f"--source={vid}", "--staged", "--worktree", "--", ":/")
        if not self._changed():
            return None
        short = vid[:8]
        _git(self.folder, "add", "-A")
        msg = f"Went to the version: {name} ({short})\n\n{_TRAILER}"
        _git(self.folder, "commit", "-q", "-m", msg)
        return self.info(1).versions[0]


def _status_line(line: str) -> tuple[str, str]:
    status, _, path = line.partition("\t")
    return status[:1], path


def _mod_files(folder: Path) -> dict[str, Path]:
    """Every file of the mod folder by its relative path, ``.git`` left out."""
    out: dict[str, Path] = {}
    for p in folder.rglob("*"):
        rel = p.relative_to(folder).as_posix()
        if p.is_file() and not rel.startswith(".git/") and rel != ".git":
            out[rel] = p
    return out


def _crc(path: Path) -> int:
    crc = 0
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            crc = zlib.crc32(chunk, crc)
    return crc


def versions_root() -> Path:
    """``~/.local/share/vic2toolmod/versions`` (next to the backups)."""
    return Path.home() / ".local" / "share" / "vic2toolmod" / "versions"


class CopyVersions:
    """Versions as zip copies of the mod folder (for mods without git)."""

    kind = "copies"

    def __init__(self, folder: Path, root: Path | None = None) -> None:
        self.folder = folder
        key = hashlib.sha1(str(folder.resolve()).encode(), usedforsecurity=False).hexdigest()[:8]
        self.dir = (root or versions_root()) / f"{folder.name}-{key}"

    def _index(self) -> list[dict[str, Any]]:
        p = self.dir / "index.json"
        if not p.exists():
            return []
        data: list[dict[str, Any]] = json.loads(p.read_text(encoding="utf-8"))
        return data

    def _write_index(self, items: list[dict[str, Any]]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "index.json").write_text(json.dumps(items, indent=1), encoding="utf-8")

    def _zip(self, vid: str) -> Path:
        """The zip of a version (a "went to" version shares the zip it went to)."""
        for i in self._index():
            if i["id"] == vid:
                return self.dir / f"{i.get('zip') or vid}.zip"
        raise VersionError(f"no version {vid}")

    def _differs(self, vid: str) -> list[tuple[str, str]]:
        with zipfile.ZipFile(self._zip(vid)) as z:
            saved = {i.filename: (i.CRC, i.file_size) for i in z.infolist() if not i.is_dir()}
        now = _mod_files(self.folder)
        out: list[tuple[str, str]] = []
        for rel, p in sorted(now.items()):
            if rel not in saved:
                out.append(("A", rel))
            elif p.stat().st_size != saved[rel][1] or _crc(p) != saved[rel][0]:
                out.append(("M", rel))
        out += [("D", rel) for rel in sorted(saved) if rel not in now]
        return out

    def info(self, limit: int = 200) -> Info:
        """The list of versions (newest first) and how many files changed since the newest."""
        items = list(reversed(self._index()))[:limit]
        versions = [
            Version(**{k: v for k, v in i.items() if k not in ("current", "zip")}) for i in items
        ]
        changed = len(self._differs(versions[0].id)) if versions else len(_mod_files(self.folder))
        if versions and not changed:
            versions[0].current = True
        note = "" if versions else "no version yet"
        return Info("copies", str(self.dir), versions, changed, note)

    def save(self, name: str, description: str = "", auto: bool = False) -> Version:
        """Save the whole mod folder as a new version (a zip)."""
        items = self._index()
        if items and not self._differs(items[-1]["id"]):
            raise VersionError("nothing changed since the last version")
        self.dir.mkdir(parents=True, exist_ok=True)
        vid = time.strftime("%Y%m%d-%H%M%S")
        while (self.dir / f"{vid}.zip").exists():
            vid += "a"
        files = _mod_files(self.folder)
        tmp = self.dir / f"{vid}.zip.part"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for rel, p in sorted(files.items()):
                z.write(p, rel)
        tmp.rename(self.dir / f"{vid}.zip")
        v = Version(
            vid,
            name.strip(),
            description.strip(),
            time.strftime("%Y-%m-%dT%H:%M:%S"),
            len(files),
            auto=auto,
        )
        self._write_index([*items, asdict(v)])
        return v

    def files(self, vid: str) -> list[tuple[str, str]]:
        """Files of a version that differ from the version before it."""
        items = self._index()
        ids = [i["id"] for i in items]
        if vid not in ids:
            raise VersionError(f"no version {vid}")
        with zipfile.ZipFile(self._zip(vid)) as z:
            new = {i.filename: i.CRC for i in z.infolist() if not i.is_dir()}
        k = ids.index(vid)
        if k == 0:
            return [("A", rel) for rel in sorted(new)]
        with zipfile.ZipFile(self._zip(ids[k - 1])) as z:
            old = {i.filename: i.CRC for i in z.infolist() if not i.is_dir()}
        out = [("A" if r not in old else "M", r) for r in sorted(new) if old.get(r) != new[r]]
        return out + [("D", r) for r in sorted(old) if r not in new]

    def compare(self, vid: str) -> list[tuple[str, str]]:
        """``(status, path)`` that differ between a version and the files now."""
        return self._differs(vid)

    def restore(self, vid: str, name: str) -> Version | None:
        """Make the files what they were in version ``vid`` (current state saved first).

        Returns the new version that records it, or None when nothing changed.
        """
        source = self._zip(vid)
        items = self._index()
        if not items or self._differs(items[-1]["id"]):
            self.save(f"{_AUTO} {name}", auto=True)
        if not self._differs(vid):
            return None
        with zipfile.ZipFile(source) as z:
            keep = {i.filename for i in z.infolist() if not i.is_dir()}
            for rel, p in _mod_files(self.folder).items():
                if rel not in keep:
                    p.unlink()
            z.extractall(self.folder)
        # the state now is that version: record it, so the list shows where the files are
        v = Version(
            time.strftime("%Y%m%d-%H%M%S") + "r",
            f"Went to the version: {name}",
            "",
            time.strftime("%Y-%m-%dT%H:%M:%S"),
            len(keep),
        )
        self._write_index([*self._index(), {**asdict(v), "zip": source.stem}])
        return v


def store(folder: Path, root: Path | None = None) -> GitVersions | CopyVersions:
    """The way this mod's versions are kept: git when the mod is a repository, else copies."""
    return GitVersions(folder) if uses_git(folder) else CopyVersions(folder, root)
