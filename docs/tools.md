# Tools built on the engine

All commands: `python -m vic2toolmod <command> --help`. Folders default to the
settings (`~/.config/vic2toolmod/config.toml`).

| Command | Module | What it does |
|---|---|---|
| `parse FILE [--json]` | `script` | syntax tree and syntax errors of one file |
| `roundtrip [PATH...]` | `script.roundtrip` | checks that every script file is written back byte for byte |
| `errors [PATH...]` | `script` | syntax errors only |
| `check [MOD] [--vanilla] [--summary]` | `check`, `workspace` | syntax + schema + names of a mod (`docs/schema.md`) |
| `events [--json FILE]` | `analysis.events` | event chains: who fires which event; events fired but missing; triggered-only events nothing fires (K6 C) |
| `poptypes [--json FILE] [--registry R]` | `analysis.poptypes` | which reforms / techs / inventions change which pop weights; promotion graph (K59) |
| `diff-vanilla [--file REL]` | `analysis.overview` | mod files that are new, changed (+/- lines), identical copies, or hide vanilla (K6 H) |
| `stats` | `analysis.overview` | pops at the start by owner, culture, religion, type (K6 I) |
| `generate-parties IDEOLOGY ... [--write]` | `generators.parties` | adds a party of an ideology to many countries with localisation; dry run shows a diff (K58) |
| `gui [--port N] [--no-browser]` | `server` | local server for the GUI; the API is listed at the top of `vic2toolmod/server/app.py` |

## Trigger tester (`analysis.trigger_tester`, K53)

`TriggerTester(schema, doc).facts(block)` lists the conditions of a trigger
block as facts with stable ids (`"3.1"` = second item inside the fourth item);
`evaluate(block, answers)` takes the real values (`{"0": "USA", "3.1": "0.62"}`
or `True` / `False`) and returns `Result(value, failed, unknown)`, where
`failed` are the facts that decided a false result. Numbers compare as "at
least" unless the schema says otherwise, `NOT` is "none of", scope changes
(`any_pop`, `ENG = { }`) are asked as one yes/no question. `weight(block,
answers)` computes MTTH / `ai_chance` / pop weights: base value times the
factors of the modifiers whose conditions hold. Exposed in the API as
`POST /api/trigger`.

## Party generator (`generators.parties`, K58)

```
python -m vic2toolmod generate-parties christian_democrat \
    --copy-from conservative --set religious_policy=moralism \
    --culture-groups germanic,italian --civilized yes \
    --loc "{adj} Christian Democrats"            # add --write to save
```

Countries are chosen by tags, culture groups of their primary culture and
civilized status; only countries that already have parties and no party of
the ideology get one. Policies are copied from the country's party of the
first `--copy-from` ideology it has, then `--set` values are applied; every
party issue of the mod must end up with a value. The party is inserted after
the country's last party; English names go to
`localisation/00_vic2toolmod_parties.csv` (`{adj}` = `TAG_ADJ`). Writing makes
a backup of changed files in `~/.local/share/vic2toolmod/backups/`.

## Localisation writer (`project.localisation.set_entry`, K35)

Adds a key to `localisation/00_vic2toolmod.csv` or changes the line where the
mod defines it; other lines and columns stay as they are.
