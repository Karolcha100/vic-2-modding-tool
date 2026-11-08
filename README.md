# vic2toolmod

An engine (and, later, a browser GUI) for modding **Victoria 2** (3.04). The goal is to
edit mod files either as code or as blocks, with completion of names from the whole mod
(tags, ideologies, reforms, units, event ids, …) and live error reporting.

Status:

- **Phase 1 done** — lossless parser for Paradox script (`.txt`, `.gfx`, `.gui`, `.mod`,
  `.map`); all 17 976 script files of vanilla 3.04 and three mods round-trip byte for byte.
- **Phase 2 done** — schema of the scripting language (triggers, effects, scopes,
  modifiers, structure of every file type) and a checker; the whole of vanilla 3.04 is
  known to the schema except its five real problems.
- Phase 3 (project index) in progress.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Tell the tool where the game and your mod are, in `~/.config/vic2toolmod/config.toml`:

```toml
game_dir = "/home/me/.steam/steam/steamapps/common/Victoria 2"
mod_dirs = ["/home/me/Victoria 2 mods/MyMod"]
```

(or set `VIC2_GAME_DIR` / `VIC2_MOD_DIR`).

## Command line

```sh
.venv/bin/python -m vic2toolmod parse events/MyEvents.txt    # tree + syntax errors
.venv/bin/python -m vic2toolmod parse --json file.txt        # tree as JSON
.venv/bin/python -m vic2toolmod errors path/to/mod           # all syntax errors
.venv/bin/python -m vic2toolmod roundtrip                     # lossless check of configured folders
.venv/bin/python -m vic2toolmod check path/to/mod             # schema + names check of a mod
.venv/bin/python -m vic2toolmod check --vanilla --summary     # the game itself, counts only
```

## As a library

```python
from vic2toolmod.script import parse_file

doc, encoding = parse_file("events/MyEvents.txt")
for event in doc.assignments("country_event"):
    print(event.value.find("id").value.text)
for d in doc.diagnostics:
    print(doc.position(d.start), d.code, d.message)
assert doc.to_text() == doc.text
```

## Development

```sh
.venv/bin/python -m pytest          # tests (game-data tests need the settings above)
.venv/bin/ruff check vic2toolmod tests
.venv/bin/mypy
```

Documentation: [`docs/architecture.md`](docs/architecture.md),
[`docs/script-syntax.md`](docs/script-syntax.md), [`docs/schema.md`](docs/schema.md).

The schema uses data from [cwtools-vic2-config](https://github.com/cwtools/cwtools-vic2-config)
(MIT licence) and the [Victoria 2 wiki](https://vic2.paradoxwikis.com/Modifier_effects).
