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

## The world from history (`analysis.world`, K75 B)

`World.read(ws, "1836.1.1")` reads what the history gives at a date:
countries (`history/countries`, dated blocks up to the date applied in order:
capital, cultures, religion, government, civilisation, prestige, literacy,
plurality, national value, school, ruling party and its ideology, upper house,
technologies and inventions, reform settings, flags, decisions), provinces
(owner, controller, cores, trade goods, life rating, terrain), alliances /
vassals / substates / unions of `history/diplomacy` active at the date, wars of
`history/wars` going on, continents, regions and culture groups.
`World.check(block, Scope(...))` evaluates a trigger block in a country or
province scope with three values: `True`, `False` or `None` with the reasons
(pops, money, relations, great power rank, modifiers … are not in the history;
there are no spheres or truces at the start of the game). Scopes: `TAG = { }`,
province ids, `owner`, `controller`, `capital_scope`, `any_owned_province`,
`any_core`, `all_core`, `overlord`, `any_country`, `war_countries`.
`World.answers(tester, block, tag)` gives the tester's facts that history
decides. API: `trigger/world` (answers for one country) and
`trigger/countries` (every country existing at the date: meets / unknown /
not); the GUI's trigger tester has "Fill from history" and "Which countries?".

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
(`key = N`, or `NOT = { key = N }`, true below N). Both spellings of one
variable in one block are one group (T023): every step has its own
`negated`, and the GUI shows each step's comparison (`≥ N`, or `< N` for
`NOT`) and lets it be switched. At least two modifiers with two different
steps make a group. `scan` lists the groups of every
mod file (RPM: about 3 700 groups in 126 files, ~4 s).

How the factors of a block join (`combine`, with its reason in
`combine_note`; the GUI can switch it for the chart):

| Block | Factors |
|---|---|
| `poptypes/*.txt` → `promote_to` | add |
| `common/pop_types.txt`: `promotion_chance`, `demotion_chance`, `migration_chance`, `colonialmigration_chance`, `emigration_chance`, `assimilation_chance`, `conversion_chance` | add |
| `common/ideologies.txt` → `add_/remove_*_reform` | add |
| `inventions/*.txt` → `chance` (percent a month) | add |
| `poptypes/*.txt` → `issues`, `ideologies`, `migration_target`, `country_migration_target` | multiply |
| `mean_time_to_happen`, `ai_chance`, `ai_will_do`, rebels (`spawn_chance`, `movement_evaluation`, `will_rise`), everything else | multiply |

Source: the rules of [Project Alice](https://github.com/schombert/Project-Alice)
(`docs/rules.md` and its source), the open-source reimplementation of
Victoria 2 whose authors worked the rules out from the game: "promotion and
demotion factors seem to be computed additively", "the product of the country
migration target modifiers", "the attraction modifier for each issue is
computed multiplicatively", "the invention chance modifier is computed
additively". Vanilla's own values agree: negative factors appear only in the
"add" blocks (494 in `promote_to`, 54 in `pop_types.txt`), `factor = 0` (a
block) only in the "multiply" ones, and `migration_target` starts from
`factor = 0.01`. The Victoria 2 wiki's note ("Issue and Ideology modifiers
are multipliers, all other seem to be additions") is right except for the two
migration targets.

`rewrite` / `rewrite_edits` give a group new `(value, factor)` steps: the
first modifier is the pattern of the new ones (its layout, comments and other
conditions stay), the others are removed. Identical groups in the same place of
other files (the keys from the top of the file, without event ids:
`promote_to/soldiers`, `emigration_chance/group`) have the same `signature`
and can be changed together; two groups of one file are never copies (T014).

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

## Meta relations of pops (`generators.meta`, T010)

A rule written once - "with conscription, every pop with `strata = poor`
promotes more to soldiers" - that the tool copies into every matching pop
file. The game has no rules or includes, so the copies are ordinary
`modifier = { … }` blocks between marker comments:

```
		# vic2toolmod meta: conscription_poor 1a2b3c4d
		modifier = { factor = 2 country = { military_service = two_year_draft } }
		# vic2toolmod meta end: conscription_poor
```

- **Rules** are kept in the mod, one file each: `vic2toolmod/meta/<name>.txt`
  (a folder the game does not read; K89 = B), in script syntax: `name`,
  `description`, `block`, `target`, `pop_types = { farmers labourers }` (none =
  all; an older `strata = { poor }` is still read),
  `group = yes/no` (the modifiers inside one `group = { }`), `modifiers = { … }`.
- **Blocks** (K90 = C): `promote_to`, `issues`, `ideologies` (with a target: the
  pop type, issue option or ideology; a missing target block is created with
  `factor = 0` for promotions, `1` otherwise), `migration_target`,
  `country_migration_target` in `poptypes/<pop>.txt`, and the chances of
  `common/pop_types.txt` (`promotion_chance` …). A pop never promotes to itself.
- **`plan`** brings every file in line with all rules: adds copies, updates them
  when a rule changed, removes copies of rules that no longer match or were
  deleted. The checksum after the start marker tells a copy the tool wrote
  from one changed by hand: such copies are kept and reported (`edited`)
  unless `force`. Nothing is written without a preview; writing makes a backup.
- **GUI:** Analyses → **Meta relations** (list, form with the pop types from the
  highest class down - a "source" tick and, for promotions, the "target" -, the modifiers' code in one
  place, groups of them edited as a function with the chart, preview, apply,
  delete) and dashed purple edges in **Pop promotion** (click one to edit its
  rule).

## Versions of the mod (`versions`, T025)

A version is the state of every file of the mod folder at one moment.
`store(folder)` picks how they are kept (K95 = C):

- `GitVersions` when the mod folder is the top of a git repository: a version
  is a commit of all changes (`git add -A`, message = the name, trailer
  `Saved-with: vic2toolmod`); the list is the branch's history, so commits
  made elsewhere are versions too. Git runs with `core.autocrlf=false`, so
  files go in and out byte for byte. Nothing is pushed.
- `CopyVersions` otherwise, in `~/.local/share/vic2toolmod/versions/<mod>-<hash>/`:
  per version a list of all files (`<id>.json`: path -> checksum, size and the
  version whose zip holds the content) and a zip of only the files changed
  since the version before (the first one holds the whole mod), plus an
  `index.json` of names and dates. A version made by going to another one
  has only the list. `Info.note` tells the GUI whether the versions reach
  GitHub (git remote) and, for copies, how much space they take (K95).

`restore(id, name)` (K96 = A) first saves the state now as an automatic
version when it differs from the newest one, then makes the files what they
were in that version (`git restore --source=<id> --staged --worktree -- :/`,
which also removes files the version did not have; with copies the zip is
unpacked from the zips the list points at and other files removed) and
records that as a new version. History only grows: going "forward" again is
going to another version of the list. `files(id)` lists what a version
changed, `compare(id)` what differs now.
API: `versions`, `versions/files`, `versions/save`, `versions/restore`.

## Province map (`analysis.provmap`, K75 A)

`read_bmp` reads `map/provinces.bmp` (uncompressed 24-bit; Paradox keeps north
in the first stored row, as `map/positions.txt` confirms). `id_image(ws,
scale)` gives it as PNG with every `scale`-th pixel, so province colours stay
exact; `info(ws, world)` the colours, names, owners and cores of the provinces
(`map/definition.csv`, `World`) and the countries' map colours. The browser
paints the map and finds the province under the mouse by its colour. API:
`map/image`, `map/info`.

