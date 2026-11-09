from pathlib import Path

import pytest

from vic2toolmod.edit import apply_edits
from vic2toolmod.services import LanguageService
from vic2toolmod.workspace import Workspace


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("latin-1"))


@pytest.fixture
def svc(tmp_path):
    g = tmp_path / "game"
    write(g / "common/countries.txt", 'ENG = "countries/UK.txt"\nFRA = "countries/France.txt"\n')
    write(g / "common/event_modifiers.txt", "my_mod = { badboy = 1 }\n")
    write(g / "poptypes/farmers.txt", "sprite = 1\n")
    write(g / "localisation/a.csv", "my_mod;My modifier;;;;;;;;;;;;;x\n")
    write(
        g / "events/a.txt",
        "country_event = { id = 1 trigger = { tag = ENG } "
        "option = { add_country_modifier = { name = my_mod duration = 10 } } }\n",
    )
    write(g / "events/b.txt", "country_event = { id = 2 trigger = { tag = ENG } }\n")
    return LanguageService(Workspace.open(g))


def offset(svc, rel, text, after=0):
    return svc.ws.document(rel).text.index(text) + after


def test_complete_commands_by_scope(svc):
    svc.ws.set_text("events/b.txt", "country_event = { id = 2 trigger = { any_pop = { mil } } }")
    labels = [c.label for c in svc.complete("events/b.txt", offset(svc, "events/b.txt", "mil", 3))]
    assert labels == ["militancy"]


def test_complete_values(svc):
    rel = "events/b.txt"
    svc.ws.set_text(rel, "country_event = { id = 2 trigger = { war =  } }")
    assert [c.label for c in svc.complete(rel, offset(svc, rel, "war =", 6))] == ["yes", "no"]
    svc.ws.set_text(rel, "country_event = { id = 2 trigger = { tag = E } }")
    assert [c.label for c in svc.complete(rel, offset(svc, rel, "= E", 3))] == ["ENG"]
    # "key = <nothing>" followed by more text: Paradox syntax reads "war = tag",
    # so completion at "E" is not for tag's value (documented limitation).


def test_complete_fields(svc):
    svc.ws.set_text("events/b.txt", "country_event = { id = 2  }")
    labels = {c.label for c in svc.complete("events/b.txt", offset(svc, "events/b.txt", "2 ", 2))}
    assert {"title", "option", "trigger"} <= labels and "id" not in labels


def test_hover_and_definition(svc):
    rel = "events/a.txt"
    h = svc.hover(rel, offset(svc, rel, "my_mod", 2))
    assert "My modifier" in h.text and "common/event_modifiers.txt:1" in h.text
    d = svc.definition(rel, offset(svc, rel, "ENG", 1))
    assert (d.file, d.line) == ("common/countries.txt", 1)
    assert "trigger" in svc.hover(rel, offset(svc, rel, "tag", 1)).text


def test_references_and_rename(svc):
    rel = "events/a.txt"
    refs = svc.references(rel, offset(svc, rel, "ENG", 1))
    assert sorted(u.file for u in refs) == ["events/a.txt", "events/b.txt"]
    edits = svc.rename(rel, offset(svc, rel, "ENG", 1), "GBR")
    assert set(edits) == {"events/a.txt", "events/b.txt", "common/countries.txt"}
    countries = svc.ws.document("common/countries.txt").text
    assert apply_edits(countries, edits["common/countries.txt"]).startswith(
        'GBR = "countries/UK.txt"'
    )


def test_hover_on_modifiers_this_and_undescribed_keys(svc):
    # T004: a modifier key in a modifier block is known (was "unknown here").
    rel = "common/event_modifiers.txt"
    h = svc.hover(rel, offset(svc, rel, "badboy", 1))
    assert "modifier" in h.text and "unknown" not in h.text
    # THIS / FROM blocks in triggers and effects.
    svc.ws.set_text("events/b.txt", "country_event = { id = 2 trigger = { FROM = { tag = ENG } } }")
    assert "FROM" in svc.hover("events/b.txt", offset(svc, "events/b.txt", "FROM", 1)).text
    # Unknown key (warned) vs. a key the schema does not describe (accepted unchecked).
    svc.ws.set_text("events/b.txt", "country_event = { id = 2 colour = red }")
    h = svc.hover("events/b.txt", offset(svc, "events/b.txt", "colour", 1))
    assert "unknown here" in h.text
