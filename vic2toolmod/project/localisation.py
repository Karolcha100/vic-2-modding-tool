"""Localisation: ``localisation/*.csv`` files.

Each line is ``KEY;English;French;German;;Spanish;...;x`` in Windows-1252.
The game reads the files in alphabetical order of their names (mod and vanilla
together, a mod file replacing a vanilla file of the same name) and the
**first** definition of a key wins - that is why mods name their files
``00_...``. Lines starting with ``#`` and lines without a key are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from vic2toolmod import textio
from vic2toolmod.changes import FileChange
from vic2toolmod.project.layout import Project, ProjectFile

LANGUAGES = ("english", "french", "german", "polish", "spanish")
"""Column order after the key (the fourth column is unused by the game)."""


@dataclass(frozen=True, slots=True)
class LocEntry:
    """One localisation line.

    Attributes:
        key: The key, original spelling.
        texts: The columns after the key (``texts[0]`` is English).
        file: Relative path of the file.
        line: Line number (1-based).
    """

    key: str
    texts: tuple[str, ...]
    file: str
    line: int

    def text(self, language: str = "english") -> str:
        """Text in a language ('' if missing)."""
        i = LANGUAGES.index(language)
        return self.texts[i] if i < len(self.texts) else ""


@dataclass
class Localisation:
    """All localisation of a project.

    Attributes:
        entries: Lower-case key -> the entry the game uses (first definition).
        shadowed: Later definitions of keys that already had one (they have
            no effect in the game).
    """

    entries: dict[str, LocEntry] = field(default_factory=dict)
    shadowed: list[LocEntry] = field(default_factory=list)

    def get(self, key: str) -> LocEntry | None:
        """The entry of a key (any case), if defined."""
        return self.entries.get(key.lower())

    def __contains__(self, key: str) -> bool:
        return key.lower() in self.entries


def read_csv(file: ProjectFile) -> list[LocEntry]:
    """Read one localisation file."""
    text, _ = textio.decode(file.path.read_bytes())
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        parts = line.split(";")
        key = parts[0].strip()
        if key:
            out.append(LocEntry(key, tuple(parts[1:]), file.rel, n))
    return out


def load_localisation(project: Project) -> Localisation:
    """Read every visible ``localisation/*.csv`` in the game's order."""
    loc = Localisation()
    files = project.glob("localisation/*.csv")
    for f in sorted(files, key=lambda f: PurePosixPath(f.rel).name.lower()):
        for entry in read_csv(f):
            low = entry.key.lower()
            if low in loc.entries:
                loc.shadowed.append(entry)
            else:
                loc.entries[low] = entry
    return loc


def set_entry(
    project: Project,
    key: str,
    english: str,
    *,
    other: dict[str, str] | None = None,
    new_file: str = "localisation/00_vic2toolmod.csv",
) -> FileChange:
    """Plan adding or changing one localisation key in the mod (K35: edit text in place).

    If the mod already defines the key, that line is changed (other columns are
    kept unless given); otherwise a line is appended to ``new_file`` (created if
    needed). Untouched lines stay byte for byte; the file keeps its line breaks.

    Args:
        project: The project (its mod folder is written).
        key: The key.
        english: English text.
        other: Texts for other languages (``french``, ``german``, ``spanish``);
            missing ones get the English text for a new line.
        new_file: Where new keys go.

    Returns:
        The planned change (write it with `vic2toolmod.changes.write_changes`).
    """
    if project.mod_dir is None:
        raise ValueError("a mod folder is needed")
    other = other or {}
    if ";" in english or any(";" in t for t in other.values()):
        raise ValueError("localisation text cannot contain ';'")
    for f in sorted(
        project.glob("localisation/*.csv"), key=lambda f: PurePosixPath(f.rel).name.lower()
    ):
        if f.origin != "mod":
            continue
        for entry in read_csv(f):
            if entry.key.lower() != key.lower():
                continue
            text, encoding = textio.decode(f.path.read_bytes())
            lines = text.splitlines(keepends=True)
            raw = lines[entry.line - 1]
            body = raw.rstrip("\r\n")
            ending = raw[len(body) :]
            cols = body.split(";")
            cols += [""] * max(0, 6 - len(cols))
            cols[1] = english
            for lang, value in other.items():
                cols[1 + LANGUAGES.index(lang)] = value
            lines[entry.line - 1] = ";".join(cols) + ending
            return FileChange(f.rel, f.path, text, "".join(lines), encoding)
    path = project.mod_dir / new_file
    old = textio.decode(path.read_bytes())[0] if path.exists() else None
    nl = "\r\n" if old is None or "\r\n" in old else "\n"
    texts = [other.get(lang, english) if lang != "polish" else "" for lang in LANGUAGES]
    texts[0] = english
    line = ";".join([key, *texts]) + ";;;;;;;;;x" + nl
    base = old or ""
    if base and not base.endswith(("\n", "\r")):
        base += nl
    return FileChange(new_file, path, old, base + line)
