# Editing and language services

## Edits (`vic2toolmod.edit`)

The text is the source of truth (K31). Operations take the parsed `Document`
and return a `TextEdit(start, end, new_text)`; `apply_edits` applies several
non-overlapping edits. Everything outside the edited ranges stays byte for byte.

| Operation | Result |
|---|---|
| `set_value(doc, assignment, value)` | replaces the value (a scalar, or a whole new block) |
| `rename_key(assignment, key)` | replaces the key |
| `replace_token_text(node, text)` | replaces one scalar / key token |
| `delete(doc, node)` | removes the node; when it is alone on its line(s) the whole line goes; comments above stay, a trailing comment stays |
| `insert(doc, block_or_doc, items, index=None)` | inserts `key = value` items at the end or before item `index` |

New content is given in Python form: `[("key", "value"), ("block", [("a", "1")]),
("color", ["1", "2", "3"])]`. It is written in the style of the file (K15):

- indentation unit detected from the file (tab, or the most common space step);
- the file's line break (`\r\n` if the file has it);
- each key on its own line, except short blocks of plain values (up to three
  pairs, 80 columns) which stay on one line: `limit = { is_primary_culture = yes }`;
- into a block written on one line (`trigger = { war = no }`) items are added
  on the same line.

`Buffer(text)` is an editor buffer: `apply(edits)` and `replace_all(text)` are
undoable steps; `undo()`, `redo()`; `document` is the parsed current text.

## Language services (`vic2toolmod.services.LanguageService`)

Built on a `Workspace`; positions are character offsets in the file's current
text (editor buffer if set).

| Method | What it gives |
|---|---|
| `complete(rel, offset)` | keys allowed in the block (fields of the rule, commands of the trigger / effect context valid in the current scope, modifier keys, names for dynamic keys), or values after `key =` (`yes`/`no`, enum values, names from registries incl. `THIS`/`FROM`, localisation keys); filtered by the word before the cursor |
| `hover(rel, offset)` | for a key: kind (trigger / effect / scope change), scopes, value type, source, description; for a name: its English localisation and where it is defined |
| `definition(rel, offset)` | `Definition(name, file, line)` of the name under the cursor |
| `references(rel, offset)` | every usage of that name in the project |
| `rename(rel, offset, new)` | edits per file renaming the usages and the definition |

How it knows what is allowed: the validator records, for each block, its rule
or command context and scope (`Validator.block_info`) and, for each assignment,
what its value should be (`Validator.value_info`); every reference to a named
thing is recorded in `Validator.references`.

Limitation: Paradox syntax ignores line breaks, so a half-typed `key =`
followed by more text on the next lines takes that text as its value (`war =`
then `tag = E` reads as `war = tag`). Completion still works at the end of the
half-typed line.
