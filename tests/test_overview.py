from pathlib import Path

from vic2toolmod.analysis.overview import compare_with_vanilla, pop_stats, vanilla_diff
from vic2toolmod.changes import write_changes
from vic2toolmod.project import Project
from vic2toolmod.project.localisation import load_localisation, set_entry
from vic2toolmod.workspace import Workspace


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("latin-1"))


def make(tmp_path):
    g, m = tmp_path / "game", tmp_path / "mod"
    write(g / "events/a.txt", "country_event = { id = 1 }\n")
    write(g / "events/b.txt", "country_event = { id = 2 }\n")
    write(g / "decisions/x.txt", "political_decisions = { }\n")
    write(m / "events/a.txt", "country_event = { id = 1 }\n")
    write(m / "events/b.txt", "country_event = { id = 2 }\ncountry_event = { id = 3 }\n")
    write(m / "events/c.txt", "country_event = { id = 4 }\n")
    write(tmp_path / "mod.mod", 'name = "M"\nreplace_path = "decisions"\n')
    write(g / "history/provinces/europe/1 - A.txt", "owner = ENG\n")
    write(
        g / "history/pops/1836.1.1/x.txt",
        "1 = { farmers = { culture = british religion = protestant size = 100 } "
        "clerks = { culture = scottish religion = protestant size = 50.5 } }\n",
    )
    return Project.open(g, m)


def test_compare_with_vanilla(tmp_path):
    project = make(tmp_path)
    diffs = {d.rel: (d.status, d.added, d.removed) for d in compare_with_vanilla(project)}
    assert diffs == {
        "events/a.txt": ("same", 0, 0),
        "events/b.txt": ("changed", 1, 0),
        "events/c.txt": ("new", 0, 0),
        "decisions/x.txt": ("hidden", 0, 0),
    }
    assert "+country_event = { id = 3 }" in vanilla_diff(project, "events/b.txt")


def test_pop_stats(tmp_path):
    s = pop_stats(Workspace(make(tmp_path)))
    assert (s.date, s.total) == ("1836.1.1", 150.5)
    assert s.by_culture == {"british": 100, "scottish": 50.5}
    assert s.by_owner == {"ENG": 150.5}
    assert s.by_type["clerks"] == 50.5


def test_set_localisation_entry(tmp_path):
    project = make(tmp_path)
    change = set_entry(project, "MY_KEY", "Hello")
    assert (
        change.old_text is None
        and change.new_text == "MY_KEY;Hello;Hello;Hello;;Hello;;;;;;;;;x\r\n"
    )
    write_changes([change], backup=False)
    project = Project.open(project.game_dir, project.mod_dir)
    change = set_entry(project, "my_key", "Hi", other={"german": "Hallo"})
    assert change.new_text == "MY_KEY;Hi;Hello;Hallo;;Hello;;;;;;;;;x\r\n"
    write_changes([change], backup=False)
    loc = load_localisation(Project.open(project.game_dir, project.mod_dir))
    assert loc.get("MY_KEY").text("german") == "Hallo"
