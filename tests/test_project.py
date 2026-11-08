from vic2toolmod.project import Project, build_registries, read_mod_file


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="latin-1")


def make_game(tmp_path):
    game = tmp_path / "game"
    write(game / "common/countries.txt", 'ENG = "countries/UK.txt"\nFRA = "countries/France.txt"\n')
    write(
        game / "common/cultures.txt",
        "germanic = { unit = x north_german = { color = { 1 2 3 } } }\n",
    )
    write(game / "events/a.txt", "country_event = { id = 10 }\n")
    write(game / "events/b.txt", "country_event = { id = 20 }\n")
    write(game / "poptypes/farmers.txt", "sprite = 1\n")
    write(game / "common/issues.txt", "party_issues = { trade_policy = { free_trade = { } } }\n")
    write(game / "mod/x.txt", "ignored = yes\n")
    return game


def test_overlay_and_replace_path(tmp_path):
    game = make_game(tmp_path)
    mod = tmp_path / "game" / "mod" / "My"
    write(mod / "events/a.txt", "country_event = { id = 11 }\n")
    write(mod / "events/c.txt", "country_event = { id = 30 }\n")
    write(
        tmp_path / "game" / "mod" / "My.mod",
        'name = "My"\npath = "mod/My"\nreplace_path = "events"\n',
    )
    project = Project.open(game, mod)
    assert project.replace_paths == ("events",)
    files = project.files()
    assert files["events/a.txt"].origin == "mod"
    assert "events/b.txt" not in files  # hidden by replace_path
    assert "mod/x.txt" not in files
    assert files["common/countries.txt"].origin == "game"
    regs = build_registries(project)
    assert regs.has("event", "11") and regs.has("event", "30") and not regs.has("event", "20")


def test_registries(tmp_path):
    regs = build_registries(Project.open(make_game(tmp_path)))
    assert regs.has("country", "eng") and regs.has("country", "FRA")
    assert regs.has("culture", "north_german") and regs.has("culture_group", "germanic")
    assert regs.has("pop_type", "farmers")
    assert regs.has("issue", "trade_policy") and regs.has("issue_option", "free_trade")
    assert regs.has("planet", "x") is None
    d = regs.get("event", "20")
    assert d.file == "events/b.txt" and d.line == 1


def test_read_mod_file(tmp_path):
    path = tmp_path / "m.mod"
    path.write_text(
        'name = "M"\npath = "mod/M"\nuser_dir = "M"\nreplace_path = "history/pops"\n'
        'dependencies = { "Base" }\n'
    )
    m = read_mod_file(path)
    assert (m.name, m.path, m.replace_paths, m.dependencies) == (
        "M",
        "mod/M",
        ("history/pops",),
        ("Base",),
    )
