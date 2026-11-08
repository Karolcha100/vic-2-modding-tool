r"""User settings: where the game and the mods are.

Settings live in a TOML file in the user's configuration directory
(``~/.config/vic2toolmod/config.toml`` on Linux, ``%APPDATA%\vic2toolmod\config.toml``
on Windows). Environment variables override the file, which is handy for tests:

* ``VIC2_GAME_DIR`` - the Victoria 2 installation (vanilla 3.04);
* ``VIC2_MOD_DIR`` - one or more mod folders, separated by ``os.pathsep``.

Example file::

    game_dir = "/home/me/.steam/steam/steamapps/common/Victoria 2"
    mod_dirs = ["/home/me/Pulpit/Vic2-MODs/RPM"]
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def config_path() -> Path:
    """Location of the settings file for the current platform."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "vic2toolmod" / "config.toml"


@dataclass(frozen=True)
class Settings:
    """Resolved settings.

    Attributes:
        game_dir: Victoria 2 installation, if known.
        mod_dirs: Mod folders, possibly empty.
    """

    game_dir: Path | None = None
    mod_dirs: tuple[Path, ...] = field(default_factory=tuple)


def load_settings(path: Path | None = None) -> Settings:
    """Read the settings file (if any) and apply environment overrides.

    Args:
        path: Settings file to read; `config_path` when omitted.

    Returns:
        The settings. Missing values stay ``None`` / empty.
    """
    path = path or config_path()
    data: dict[str, object] = {}
    if path.is_file():
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    game = os.environ.get("VIC2_GAME_DIR") or data.get("game_dir")
    mods_env = os.environ.get("VIC2_MOD_DIR")
    mods: list[str]
    if mods_env:
        mods = [m for m in mods_env.split(os.pathsep) if m]
    else:
        raw = data.get("mod_dirs", [])
        mods = [str(m) for m in raw] if isinstance(raw, list) else []
    return Settings(
        game_dir=Path(str(game)).expanduser() if game else None,
        mod_dirs=tuple(Path(m).expanduser() for m in mods),
    )
