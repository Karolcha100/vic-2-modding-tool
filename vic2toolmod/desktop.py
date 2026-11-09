"""Menu shortcut for the GUI on Linux (K72 = B): a ``.desktop`` file."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

ICON = Path(__file__).parent / "server" / "static" / "icon.svg"


def desktop_entry(python: str = sys.executable) -> str:
    """Text of the ``.desktop`` file that starts the GUI with this Python."""
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=vic2toolmod\n"
        "Comment=Victoria 2 modding tool\n"
        f"Exec={shlex.quote(python)} -m vic2toolmod gui\n"
        f"Icon={ICON}\n"
        "Terminal=false\n"
        "Categories=Development;Game;\n"
    )


def install_desktop(target_dir: Path | None = None) -> Path:
    """Write ``vic2toolmod.desktop`` into the user's applications folder.

    Args:
        target_dir: Folder to write to (default ``~/.local/share/applications``).

    Returns:
        The written file.
    """
    target_dir = target_dir or Path.home() / ".local" / "share" / "applications"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "vic2toolmod.desktop"
    path.write_text(desktop_entry(), encoding="utf-8")
    return path
