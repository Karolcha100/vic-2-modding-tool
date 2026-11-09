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

## Modifier groups (`analysis.modifier_groups`, T008)

Many modifiers of one block that differ only in one number are one step
function of that number:

```
modifier = { factor = 1.1  num_of_cities = 20 }
modifier = { factor = 1.1  num_of_cities = 30 }
modifier = { factor = 1.1  num_of_cities = 50 }
```

`find_groups` finds such groups in any file: the modifiers of one block
(`mean_time_to_happen`, `ai_chance`, pop weights, `group`, …) with one
`factor` each, the same other conditions and one number that changes
(`key = N`, or `NOT = { key = N }`, true below N). At least two modifiers
with two different numbers make a group. `scan` lists the groups of every
mod file (RPM: about 3 700 groups in 126 files, ~4 s).

How the factors of a block join (`combine`, with its reason in
`combine_note`; the GUI can switch it for the chart):

| Block | Factors | Why |
|---|---|---|
| `poptypes/*.txt` → `issues`, `ideologies` | multiply | Victoria 2 wiki (Folder/File overview): "Issue and Ideology modifiers are multipliers, all other seem to be additions"; no negative factors, 0 blocks |
| `poptypes/*.txt` → `promote_to`, other weights | add | the same wiki note; vanilla uses 494 negative factors in `promote_to` |
| `poptypes/*.txt` → `migration_target`, `country_migration_target` | multiply (uncertain) | the wiki's rule says add, the values (0.5, 1.5, 0) look like multipliers |
| `common/pop_types.txt` (promotion, migration … chances) | add | negative factors in vanilla |
| `common/ideologies.txt` → `add_/remove_*_reform` | add | negative factors in vanilla |
| everything else (`mean_time_to_happen`, `ai_chance`, rebels …) | multiply | |

The game's executable does not show this: the rule is in compiled code, not
in names or texts, so only a test in the game could confirm the unclear rows.

`rewrite` / `rewrite_edits` give a group new `(value, factor)` steps: the
first modifier is the pattern of the new ones (its layout, comments and other
conditions stay), the others are removed. Identical groups in other blocks or
files have the same `signature` and can be changed together.

GUI: in the **Blocks** view a group is one card (`modifier × 4`, the range,
the combined factor, a small chart, **Edit as function**; open it for the
single modifiers, K85 = A), **Analyses → Modifier groups** (every group of the mod; table, chart,
"make the steps from a function", identical copies, preview and write with a
backup) and **right click → Edit modifier group…** in the code editor
(the change goes into the editor, one undo step, not saved yet).
The function is the *combined* factor of the group at x: the same factor at
each step, a straight line between two values, or a formula of `x`
(`1.1 ^ ((x - 20) / 10)`, `1 + 0.02 * x`, `sqrt(x)`; `+ - * / ^`, `ln log exp
sqrt pow min max abs`); the tool computes each step's factor so that the
product (or sum) reaches it.
