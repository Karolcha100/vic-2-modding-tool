"""Lossless round-trip of the real game and mod files (skipped when not configured)."""

import pytest

from vic2toolmod.config import load_settings
from vic2toolmod.files import iter_script_files
from vic2toolmod.script.roundtrip import check_file

SETTINGS = load_settings()
ROOTS = [p for p in (SETTINGS.game_dir, *SETTINGS.mod_dirs) if p is not None and p.is_dir()]

pytestmark = [
    pytest.mark.gamedata,
    pytest.mark.skipif(not ROOTS, reason="set VIC2_GAME_DIR / VIC2_MOD_DIR or the settings file"),
]


def test_all_script_files_roundtrip():
    different = []
    count = 0
    for path in iter_script_files(ROOTS):
        count += 1
        result = check_file(path)
        if not result.ok:
            different.append((str(path), result.first_difference))
    assert count > 0
    assert different == []
