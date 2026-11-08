# Project index: files, names, references

## Visible files (`vic2toolmod.project.layout`)

`Project(game_dir, mod_dir)` lists the files the game sees: vanilla overlaid
with the mod. A mod file replaces the vanilla file with the same relative path
(compared case-insensitively); `replace_path = "folder"` in the mod's `.mod`
file hides vanilla files directly in that folder. The game's own `mod/` folder
is never part of vanilla. `Project.open` finds the `.mod` file next to the mod
folder or in the game's `mod/` folder.

## Registries (`vic2toolmod.project.registries`)

`build_registries(project)` returns `Registries`: registry -> lower-case name
-> `Definition(name, file, line)` (first definition wins; later ones are kept
in `duplicates`).

| Registry | Source |
|---|---|
| `country` | keys of `common/countries.txt` |
| `culture`, `culture_group` | `common/cultures.txt` (group = { culture = { } }) |
| `religion`, `religion_group` | `common/religion.txt` |
| `ideology`, `ideology_group` | `common/ideologies.txt` |
| `issue_category`, `issue`, `issue_option` | `common/issues.txt` (category = { issue = { option = { } } }) |
| `government`, `building`, `cb_type`, `rebel_type`, `national_value`, `production_type` | top-level keys of their `common/` file |
| `goods`, `goods_group`, `trait`, `trait_type`, `national_focus`, `focus_group` | two-level files in `common/` |
| `modifier` | event, static and triggered modifiers, national values, crimes |
| `technology`, `invention`, `unit` | top-level keys in `technologies/`, `inventions/`, `units/` |
| `pop_type` | file names in `poptypes/` |
| `province` | `map/definition.csv` and `history/provinces/*/NNN - Name.txt` |
| `region`, `continent`, `terrain` | `map/region.txt`, `map/continent.txt`, `map/terrain.txt` categories |
| `event`, `decision` | event ids in `events/`, decision names in `decisions/` |
| `country_flag`, `global_flag`, `province_flag`, `variable` | defined by being set (`set_country_flag = x`, `set_variable = { which = x }`), K28; tests are in `Registries.tested` |
| `localisation` | `localisation/*.csv` (see below) |

`Registries.has(registry, name)` answers `True` / `False`, or `None` for a
registry that does not exist - the validator then does not report anything.

## Localisation (`vic2toolmod.project.localisation`)

`KEY;English;French;German;;Spanish;...;x` lines in Windows-1252. Files are read
in alphabetical order of their names and the **first** definition of a key
wins (mods name files `00_...`); later definitions are in `shadowed`. Values
that do not look like keys (`"Unacceptable!"`, `"Some text"`) are shown by the
game as they are, so `loc.missing` is only reported for values with an
underscore, a digit, or in capitals.

## Other readers

- `vic2toolmod.project.defines.read_defines` - `common/defines.lua` as a nested
  dict of `DefineValue(text, value, line)`.
- `vic2toolmod.project.events.next_free_id` - a free event id: the lowest
  unused id in the range a file declares in a header comment
  (`### Events 95260-95320 used`), else the highest id + 1 (K29).

## Workspace (`vic2toolmod.workspace`)

The single entry point for tools and the GUI:

- `document(rel)` - parsed file, cached by size and modification time (a file
  changed on disk is re-read on the next call);
- `set_text(rel, text)` / `revert(rel)` - editor content instead of the file;
- `registries()`, `definition(registry, name)`, `usages(registry, name)`;
- `check_file(rel)`, `check(only_mod=True)` - diagnostics (syntax, schema,
  names, duplicate event ids), filtered by the mod's `vic2toolmod.toml`.

`usages` needs every file checked once (about 5 s for vanilla + RPM); after
that it is a lookup.
