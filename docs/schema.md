# Schema of the Victoria 2 scripting language

The schema says what may be written where: which triggers, effects and
modifiers exist, in which scopes, with which values, and how every kind of
file is structured. It is **data** (YAML in `vic2toolmod/schema/data/`), read
by `vic2toolmod.schema.load_schema`, so it can be reused unchanged by a port of
the engine to another language.

## 1. Files

```
vic2toolmod/schema/data/
  enums.yaml               enums: name -> list of values
  modifiers.yaml           modifiers: key -> {value, source}
  commands/core.yaml       logic, scope changes, random effects, dynamic keys (hand-written)
  commands/manual.yaml     commands added by hand (source: vanilla / author / manual)
  commands/triggers.yaml   imported from CWTools, curated
  commands/effects.yaml    imported from CWTools, curated
  commands/scopes.yaml     imported from CWTools (scope changes not in core.yaml)
  files/*.yaml             file types and structural rules
```

### Sources

Every command and modifier has `source`:

| source | meaning |
|---|---|
| `cwtools` | imported once from [cwtools-vic2-config](https://github.com/cwtools/cwtools-vic2-config) (MIT), commit `b8992c0` (2020-01-31), by `tools/import_cwtools.py`, then corrected by hand |
| `vanilla` | missing elsewhere, added because vanilla 3.04 uses it |
| `author` | from the author's command lists (`Vic2-File-Reader/possible_commands`) |
| `wiki` | from https://vic2.paradoxwikis.com/Modifier_effects (placeholders such as `(strata)_(level)_needs` expanded) |
| `manual` | written by hand |

`vanilla_scopes` (on commands) lists scopes in which vanilla uses a command
although its other sources do not allow it; `game_scopes` lists scopes
confirmed by testing in the game. These come from
`tools/learn_from_vanilla.py`, which also adds modifier keys used by vanilla.

**Rule of thumb: vanilla is valid.** `tests/test_check_gamedata.py` checks that
the whole vanilla 3.04 produces only its five known real problems.

## 2. Value specifications

Used for command values, field values and pattern values.

| YAML | meaning |
|---|---|
| `bool` | `yes` / `no` |
| `int`, `float` | numbers; `int[0..3]`, `float[-1..1]` with bounds |
| `date` | `year.month.day` |
| `scalar` | any word or string |
| `localisation` | a localisation key (checked in Phase 3) |
| `any` | anything, also a block |
| `enum:NAME` | one of the values in `enums.yaml` |
| `ref:NAME` | a name from a registry (`ref:country`, `ref:culture`, `ref:event` …). Without a project index only the shape is checked (a country is a tag or `THIS`/`FROM`/…, a province a number); with it, unknown names give `ref.unknown-name` |
| `{block: trigger}` / `{block: effect}` | a block of commands; `{block: same}` = same context as the surrounding block |
| `{fields: {key: spec, ...}, other: warn}` | a block with fixed keys |
| `{rule: NAME}` | a block described by a named rule |
| `{list: TYPE, min: N, max: N}` | a block of loose values (`color = { 1 2 3 }`) |
| `[spec, spec]` | one of several; the first that fits is used (put keywords such as `bool` before `ref:country`, because `yes` looks like a tag) |

A field is either a value specification or a mapping with the specification
plus properties: `required`, `multiple` (may repeat), `push_scope` (scope
inside), `doc`.

## 3. Commands (`commands/*.yaml`)

Sections `trigger`, `effect` and `both` (both contexts) map a name to an entry
or a list of alternatives:

```yaml
trigger:
  has_country_flag:
    scopes: [country]          # where it may be used ("any" = everywhere)
    vanilla_scopes: [province] # also used there by vanilla
    value: ref:country_flag
    compare: eq                # eq / gte / lte / block - for the trigger tester (K53)
    doc: True if the country has the flag.
    source: cwtools
both:
  any_core:
    scopes: [country, province]
    push_scope: {country: province, province: country}   # depends on the scope it is used in
    value: {block: same}
```

Alternatives (a list) are chosen by: scalar vs block value, then the current
scope, then whether the value passes the type check (e.g. `is_culture_group`
takes a tag in country scope and a culture group in pop scope).

### Names confirmed by the game program; names the game does not know

`commands/game.yaml` holds commands with `source: game`: names found in
`v2game.exe` (`strings v2game.exe | grep -x NAME`) - the program keeps the
names of every trigger, effect and modifier it understands, so a name that is
there is known to the game even when vanilla never uses it (K78). The program
says nothing about scopes or syntax; those come from mods that use the name.

A `not_in_game` section maps names that mods use but the game does not know
to a hint; using one is an error (`schema.not-in-game`):

```yaml
not_in_game:
  is_subject: 'a Hearts of Iron IV trigger; in Victoria 2 use is_vassal or is_substate'
```

### Descriptions

Every command and modifier has a description (T004; a test keeps it so):
`doc` on the entry, or, for commands imported without one, the `docs` section
of `commands/docs.yaml` (a string for both contexts, or `{trigger: …, effect:
…}`). `modifiers.yaml` entries carry `doc` too. Texts marked "meaning not
verified" come from the name or the wiki, not from a test in the game.

### Dynamic keys

`core.yaml` has a `dynamic` list for keys that are names from the mod, tried
in order when a key is no command:

```yaml
dynamic:
  - {key: tag, push_scope: country}          # ENG = { ... }
  - {key: int, push_scope: province}         # 123 = { ... }
  - {key: ref:region, push_scope: state}     # ENG_123 = { ... }
  - {key: ref:pop_type, push_scope: pop}     # aristocrats = { ... }
  - {key: ref:goods, value: float}           # cotton = 500
```

`ref:` keys need the project's registries; without them they never match.

## 4. Structural rules (`files/*.yaml`)

```yaml
file_types:
  events: {paths: ["events/*.txt"], rule: events_file, scope: country}

rules:
  event:
    fields:
      id: {value: int, required: true}
      option: {rule: event_option, multiple: true}
      trigger: {block: trigger}
    patterns:                 # dynamic keys: int, float, date, tag, any, ref:NAME
      - {key: date, rule: event}
    other: warn               # warn | trigger | effect | modifier | any
    values: int               # type of loose values allowed (none if omitted)
```

`paths` are globs relative to the game / mod folder, matched case-insensitively;
the first matching file type wins. `other` decides what happens to keys that
are neither fields nor patterns: `warn` (unknown-key warning), `trigger` /
`effect` (they are commands, e.g. in an event option), `modifier` (they are
modifier keys), `any` (accepted silently - used for files whose structure is
not described yet: interface, some map files, units' stats).

## 5. Diagnostics

| Code | Level | Meaning |
|---|---|---|
| `schema.unknown-key` | warning | key not known in this place |
| `schema.not-in-game` | error | a name mods use but the game does not know (`not_in_game`) |
| `schema.wrong-context` | error | effect in a trigger block or vice versa |
| `schema.wrong-scope` | info | command not known to work in the current scope (the game is lenient; K66). Scopes confirmed in the game go to `game_scopes` |
| `schema.wrong-value` | error | value of the wrong type |
| `schema.missing-field` | error | required key missing |
| `schema.duplicate-key` | warning | key that may appear once appears again |
| `schema.wrong-operator` | warning | Victoria 2 only understands `=` |
| `schema.unexpected-value` | warning | loose value or block where none is allowed |
| `ref.unknown-name` | warning | a name that is not defined in the mod or the game |
| `ref.flag-never-set` | warning | a flag / variable used (tested, cleared) but never set anywhere (K28) |
| `loc.missing` | warning | a localisation key without a definition (values that do not look like keys, e.g. `"Unacceptable!"`, are shown literally by the game and not reported) |

Per mod, codes or messages can be ignored in `vic2toolmod.toml` in the mod
folder (see `vic2toolmod.check`).

## 6. Known gaps

- Interface files (`.gui`, `.gfx`) and some map files are accepted without
  checks (`any_file`); they will be described with the reform window editor (K60).
- `news/`, `tutorial/`, `battleplans/`, `launcher/` files have no file type.
- Scopes come from CWTools plus vanilla usage; the game is lenient and some
  combinations it accepts may still be reported as `schema.wrong-scope`.
- Vanilla's own real problems stay reported (`tests/test_check_gamedata.py`):
  event `11108` does not exist (`decisions/NationalUnification.txt`);
  `history/units/v2dd2.txt` and `interface/credits.txt` are not script files;
  flags used but never set - `Host1O0lympiad` (a typo: letter O instead of a zero), `botanical_expedition_in_progress` (set as a global flag, tested as a
  country flag), `congo_reform_association_active`, `yes_meeting_promised`;
  missing localisation `EVTDESC111011928_NEWS_*`.
