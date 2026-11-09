"""Speed of what the editor does on every key (plan Phase 8, section 1).

Skipped without game data. Uses the configured mod when there is one (RPM for
the author), otherwise vanilla alone.
"""

import gc
import time

import pytest

from vic2toolmod.config import load_settings
from vic2toolmod.workspace import Workspace

SETTINGS = load_settings()
GAME = SETTINGS.game_dir


@pytest.fixture(scope="module")
def ws():
    mods = [m for m in SETTINGS.mod_dirs if m.is_dir()]
    w = Workspace.open(GAME, mods[0] if mods else None)
    w.registries()
    gc.collect()
    gc.freeze()  # what the GUI server does after loading
    yield w
    gc.unfreeze()


def _best(fn, n=3):
    times = []
    for i in range(n):
        t = time.perf_counter()
        fn(i)
        times.append(time.perf_counter() - t)
    return min(times)


@pytest.mark.gamedata
@pytest.mark.skipif(GAME is None or not GAME.is_dir(), reason="game folder not configured")
def test_one_key_in_the_editor_is_fast(ws):
    rel = next(f.rel for f in ws.project.glob("events/*.txt"))
    text = ws.document(rel).text
    at = text.find("{") + 1

    def key(i):
        ws.set_text(rel, text[:at] + " is"[: i + 1] + text[at:])
        ws.check_file(rel)

    assert _best(key) < 0.15  # was 0.65-1.6 s on RPM before the incremental index
    ws.revert(rel)


@pytest.mark.gamedata
@pytest.mark.skipif(GAME is None or not GAME.is_dir(), reason="game folder not configured")
def test_checking_again_is_fast(ws):
    ws.check(only_mod=True)
    assert _best(lambda i: ws.check(only_mod=True), 2) < 0.5  # was 2.3 s on RPM
