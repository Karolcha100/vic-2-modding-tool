"""Which files the game sees: vanilla overlaid with a mod.

Rules of Victoria 2 (3.04):

* a mod file with the same relative path as a vanilla file replaces it;
* ``replace_path = "events"`` in the ``.mod`` file hides every vanilla file in
  that folder (not in sub-folders); the mod's own files there stay;
* everything else in vanilla stays visible.

Relative paths are compared case-insensitively (the game runs on Windows).
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from vic2toolmod.script.cst import Assignment, Scalar
from vic2toolmod.script.parser import parse_file


@dataclass(frozen=True)
class ModFile:
    """Contents of a launcher ``.mod`` file.

    Attributes:
        name: Display name.
        path: Mod folder relative to the game folder (``mod/RPM``).
        user_dir: Folder for saves and settings.
        replace_paths: Folders whose vanilla files are hidden.
        dependencies: Names of mods this one builds on.
    """

    name: str = ""
    path: str = ""
    user_dir: str = ""
    replace_paths: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()


def read_mod_file(path: str | Path) -> ModFile:
    """Read a ``.mod`` file (Paradox syntax)."""
    doc, _ = parse_file(path)
    values: dict[str, list[str]] = {}
    for item in doc.items:
        if not isinstance(item, Assignment) or item.value is None:
            continue
        bucket = values.setdefault(item.key_text.lower(), [])
        if isinstance(item.value, Scalar):
            bucket.append(item.value.value)
        else:
            bucket.extend(i.value for i in item.value.items if isinstance(i, Scalar))

    def one(key: str) -> str:
        return values.get(key, [""])[0]

    return ModFile(
        name=one("name"),
        path=one("path"),
        user_dir=one("user_dir"),
        replace_paths=tuple(
            p.replace("\\", "/").strip("/") for p in values.get("replace_path", [])
        ),
        dependencies=tuple(values.get("dependencies", [])),
    )


@dataclass(frozen=True)
class ProjectFile:
    """One file as the game sees it.

    Attributes:
        rel: Relative path with ``/`` separators, original spelling.
        path: Real location on disk.
        origin: ``"game"`` or ``"mod"``.
    """

    rel: str
    path: Path
    origin: str


def _walk(root: Path, skip_top: frozenset[str] = frozenset()) -> Iterator[tuple[str, Path]]:
    """Files under ``root`` (sorted); ``skip_top``: lower-case top folders to leave out."""
    seen: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if real in seen:
            dirnames[:] = []
            continue
        seen.add(real)
        top = dirpath == str(root)
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and not (top and d.lower() in skip_top)
        )
        rel_dir = Path(dirpath).relative_to(root)
        for name in sorted(filenames):
            yield PurePosixPath(*rel_dir.parts, name).as_posix(), Path(dirpath) / name


@dataclass
class Project:
    """A mod on top of the base game.

    Attributes:
        game_dir: Victoria 2 installation (vanilla), or ``None`` for a mod alone.
        mod_dir: The mod folder, or ``None`` for vanilla alone.
        replace_paths: Folders whose vanilla files are hidden (from the ``.mod`` file).
    """

    game_dir: Path | None
    mod_dir: Path | None = None
    replace_paths: tuple[str, ...] = ()
    _files: dict[str, ProjectFile] | None = field(default=None, repr=False)
    _globs: tuple[dict[str, ProjectFile], dict[str, list[ProjectFile]]] | None = field(
        default=None, repr=False
    )

    @classmethod
    def open(cls, game_dir: Path | None, mod_dir: Path | None = None) -> Project:
        """Create a project, reading ``replace_path`` from the mod's ``.mod`` file.

        The ``.mod`` file is looked for next to the mod folder (``mod/RPM.mod``
        for ``mod/RPM``) and in the game's ``mod`` folder.
        """
        replace: tuple[str, ...] = ()
        if mod_dir is not None:
            candidates = [mod_dir.parent / f"{mod_dir.name}.mod"]
            if game_dir is not None:
                candidates.append(game_dir / "mod" / f"{mod_dir.name}.mod")
            for c in candidates:
                if c.is_file():
                    replace = read_mod_file(c).replace_paths
                    break
        return cls(game_dir, mod_dir, replace)

    def files(self) -> dict[str, ProjectFile]:
        """All visible files, keyed by lower-case relative path."""
        if self._files is not None:
            return self._files
        files: dict[str, ProjectFile] = {}
        hidden = {p.lower() for p in self.replace_paths}
        if self.game_dir is not None:
            # mod/ holds the mods (often symlinks): never part of the game itself
            for rel, path in _walk(self.game_dir, frozenset({"mod"})):
                low = rel.lower()
                if low.startswith("mod/"):
                    continue
                if str(PurePosixPath(low).parent) in hidden:
                    continue
                files[low] = ProjectFile(rel, path, "game")
        if self.mod_dir is not None:
            for rel, path in _walk(self.mod_dir):
                files[rel.lower()] = ProjectFile(rel, path, "mod")
        self._files = files
        return files

    def glob(self, pattern: str) -> list[ProjectFile]:
        """Visible files matching a glob such as ``events/*.txt`` (case-insensitive).

        Results are remembered until the file list is read again.
        """
        files = self.files()
        cache = self._globs
        if cache is None or cache[0] is not files:
            cache = self._globs = (files, {})
        pat = pattern.lower()
        found = cache[1].get(pat)
        if found is None:
            found = cache[1][pat] = [
                f for low, f in sorted(files.items()) if fnmatch.fnmatchcase(low, pat)
            ]
        return list(found)

    def mod_files_on_disk(self) -> dict[str, tuple[int, int]]:
        """``lower-case rel -> (size, mtime_ns)`` of the mod folder's files, read now.

        Used to notice changes made outside the editor; the game folder is not
        watched (it changes only when the game is updated).
        """
        out: dict[str, tuple[int, int]] = {}
        if self.mod_dir is None:
            return out
        for rel, path in _walk(self.mod_dir):
            try:
                st = path.stat()
            except OSError:
                continue
            out[rel.lower()] = (st.st_size, st.st_mtime_ns)
        return out

    def file(self, rel: str) -> ProjectFile | None:
        """The visible file at a relative path, if any."""
        return self.files().get(rel.replace("\\", "/").lower())
