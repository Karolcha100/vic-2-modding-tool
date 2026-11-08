# Victoria 2 script syntax (as implemented by `vic2toolmod.script`)

This is the specification the parser follows. It is written so that the parser
can be re-implemented in another language (e.g. Rust) from this document plus
the fixtures in `tests/fixtures/script/`.

The same syntax ("Clausewitz script") is used by `.txt` files in `common/`,
`events/`, `decisions/`, `history/`, `inventions/`, `technologies/`, `units/`,
`poptypes/`, `map/` (e.g. `region.txt`, `default.map`), interface files
`.gfx` / `.gui`, and launcher `.mod` files. It is **not** used by
`localisation/*.csv`, `map/*.csv` or `common/defines.lua`.

## 1. Bytes and characters

- Files are read as **Windows-1252**, unless they start with a UTF-8 byte order
  mark (then UTF-8) or contain non-ASCII bytes that form valid UTF-8 (then
  UTF-8 without BOM). The game itself always reads Windows-1252.
- The five bytes Windows-1252 leaves undefined (`0x81 0x8D 0x8F 0x90 0x9D`)
  map to the code points with the same value (U+0081 …), so every byte
  sequence decodes and encodes back identically. They occur in real mods.
- Line endings are kept as they are: `\r\n`, `\n` and a lone `\r` each count
  as one line break for line numbers. Files mix them (in vanilla 3.04 plus
  three mods, 5 068 of 17 976 files use LF only).
- Columns are counted in characters from 1; a tab is one column.

## 2. Tokens

The input is split into tokens. Before each token there may be **trivia**:

| Trivia | Pattern |
|---|---|
| whitespace | one or more of space, tab, `\r`, `\n`, form feed, vertical tab |
| comment | `#` up to (not including) the end of the line |

Trivia belongs to the token that follows it (its *leading trivia*). The trivia
at the end of the file belongs to a final `EOF` token with empty text.

Tokens, tried in this order at each position:

| Kind | Pattern | Notes |
|---|---|---|
| `WORD` | one or more characters that are not whitespace and not any of `= { } " # < >` | keys and unquoted values: `yes`, `USA`, `-0.5`, `.01`, `1836.1.1`, `123`, `any_pop`, `@var`, `'1836.1.1'` |
| `STRING` | `"` … `"` | anything except `"` inside, **including line breaks and `#`**; no escape sequences |
| `BAD_STRING` | `"` up to the end of the line | only when no closing `"` exists anywhere later in the file |
| `OPERATOR` | `<=`, `>=`, `=`, `<`, `>` | longest match first |
| `LBRACE` | `{` | |
| `RBRACE` | `}` | |

Notes:

- No spaces are required around `=`, `{`, `}`: `a={b=c}` is six tokens plus EOF.
- `#` inside a string does not start a comment (`text = "#2"` in
  `interface/backend.gui`).
- Concatenating `leading + text` of all tokens (including EOF) gives back the
  input exactly. Every character is covered, so tokenizing never fails.

## 3. Grammar

```
file       = item* EOF
item       = assignment | value | error
assignment = key OPERATOR value
key        = WORD | STRING
value      = WORD | STRING | BAD_STRING | block
block      = LBRACE item* RBRACE
```

- A `value` that is not part of an assignment is a **loose value**: list items
  such as `color = { 120 30 200 }` or `cores = { GER AUS }`.
- A `block` may appear without a key (anonymous block), e.g. lists of
  coordinate blocks in interface files.
- Keys are compared case-insensitively by lookup helpers (`NOT` = `not`), as
  the game does; the tree keeps the original spelling.
- The syntax does not decide what keys mean, which operators are allowed for a
  key, or whether a loose value is allowed at a given place. That is the job of
  the schema (Phase 2).

## 4. Error recovery

The parser never stops. Each rule below produces an **error** diagnostic and a
tree that still contains every token:

| Situation | Tree | Diagnostic code |
|---|---|---|
| `}` with no open block | `ErrorNode[}]` | `syntax.unmatched-close-brace` |
| end of file with blocks still open | the blocks, without `rbrace` | `syntax.unclosed-brace` (at each open `{`) |
| `key =` followed by `}`, another operator or EOF | `Assignment` with `value = null` | `syntax.missing-value` |
| operator not preceded by a key | `ErrorNode[op]` | `syntax.operator-without-key` |
| string without closing quote | `BAD_STRING` value | `syntax.unterminated-string` |

When a file has a brace error, the parser also emits **warnings**
`syntax.brace-indentation` for every block whose closing `}` is the first thing
on its line and is indented differently (tab = 4 columns) from the line that
opens the block. The brace error itself is reported where the parser notices
it, which is often far from the real mistake; the warning usually points at it.
Example: in RPM's `history/units/J00_oob.txt` the error is reported at the
`army` on line 22, the warning at the `regiment` on line 29, which is the block
that really lacks its `}`.

## 5. Tree

| Node | Fields | Text |
|---|---|---|
| `Document` | `items`, `eof` | items, then the EOF token |
| `Assignment` | `key`, `operator`, `value` (may be null) | key, operator, value |
| `Scalar` | `token` | the token |
| `Block` | `lbrace`, `items`, `rbrace` (may be null) | `{`, items, `}` |
| `ErrorNode` | `tokens` | the tokens |

Printing a node = concatenating `leading + text` of its tokens in order.
Printing the `Document` gives the original file. Fixture JSON (`to_data`):

```json
{"type": "assignment", "key": "a", "op": "=", "value": {"type": "scalar", "text": "1"}}
{"type": "block", "items": [...], "closed": false}      // "closed" only when false
{"type": "error", "tokens": ["}"]}
```

Scalar and key texts keep their quotes (`"\"EVTNAME95260\""`).

## 6. Oddities seen in real data (vanilla 3.04, PDM, RPM, AoE Multiplayer Remake)

- `history/units/J00_oob.txt` in PDM and RPM: a `regiment` without `}` (line 29).
- `history/units/v2dd2.txt` (vanilla) and `interface/credits.txt` are not script
  files (HTML fragment, plain text); they produce syntax errors and that is fine.
- `common/defines.lua` is Lua (`key = value,`, `--` comments, `'1836.1.1'`
  strings) and needs its own reader.
- Two AoE files contain bytes undefined in Windows-1252.
