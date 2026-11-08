"""The schema must know everything vanilla 3.04 uses (skipped without game data)."""

import pytest

from vic2toolmod.check import check_project
from vic2toolmod.config import load_settings
from vic2toolmod.project import Project

GAME = load_settings().game_dir

# Real problems of vanilla 3.04 itself (see docs/schema.md).
KNOWN = {
    ("decisions/NationalUnification.txt", "ref.unknown-name"),  # event 11108 does not exist
    ("history/units/v2dd2.txt", "schema.unknown-key"),  # not a script file
    ("history/units/v2dd2.txt", "schema.wrong-operator"),
    ("history/units/v2dd2.txt", "syntax.operator-without-key"),
    ("interface/credits.txt", "syntax.operator-without-key"),  # plain text
    # flags used but never set: Host1O0lympiad (typo), botanical_expedition_in_progress
    # (set as a global flag, tested as a country flag), congo_reform_association_active,
    # yes_meeting_promised
    ("decisions/GreatPowers.txt", "ref.flag-never-set"),
    ("events/GreatPowers.txt", "ref.flag-never-set"),
    ("events/Olympics.txt", "ref.flag-never-set"),
    ("events/ReformJealousy.txt", "ref.flag-never-set"),
    ("events/Arabia event.txt", "loc.missing"),  # EVTDESC111011928_NEWS_* not defined
}


@pytest.mark.gamedata
@pytest.mark.skipif(GAME is None or not GAME.is_dir(), reason="game folder not configured")
def test_vanilla_is_fully_known():
    found = {
        (r.file.rel, d.code)
        for r in check_project(Project.open(GAME), only_mod=False)
        for d in r.diagnostics
    }
    assert found == KNOWN
