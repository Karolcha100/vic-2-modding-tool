# Architecture

`vic2toolmod` is an engine for editing Victoria 2 (3.04) mods; a browser GUI
(TypeScript + React + Monaco) will be built on top of it once the engine is
done. This document describes the layers and the decisions behind them. It is
kept up to date with the code, and is meant to be enough to port the engine to
another language.

## Layers

```
 6. language services   completion, hover, go to definition, find usages   (Phase 4)
 5. editing             tree operations -> minimal text edits, undo/redo   (Phase 4)
 4. validation          unknown keys, wrong types / scopes, missing refs   (Phase 2-3)
 3. project index       vanilla + mod, registries of names, definitions/uses (Phase 3)
 2. schema             what the language allows, as YAML data            (Phase 2)
 1. syntax              lossless text <-> tree, syntax errors              (Phase 1, done)
 0. text I/O            lossless bytes <-> text                            (Phase 1, done)
```

Each layer only uses the layers below it. The GUI will talk to the engine
through an API (possibly LSP later), never to the files directly.

## Principles

1. **Text is the source of truth.** The tree is derived from the text; the GUI's
   block view edits the text through small, precise edits. Nothing the user
   wrote (comments, layout, unknown constructs) is ever lost.
2. **Lossless.** Reading and writing an unchanged file gives the same bytes.
   This is tested on all 17 976 script files of vanilla 3.04 and three mods.
3. **Never give up on bad input.** Editors show half-written files all the
   time. The parser always returns a full tree plus diagnostics.
4. **Knowledge is data, not code.** Syntax knows nothing about the game.
   Commands, scopes and value types will live in YAML schema files
   (imported once from CWTools' `cwtools-vic2-config`, MIT), so that adding a
   command is a data change and the schema can be reused by a port.
5. **Language-neutral test data.** Fixtures are plain files + JSON.

## Packages and modules

| Module | Responsibility |
|---|---|
| `vic2toolmod.textio` | encoding detection, lossless Windows-1252 / UTF-8 decode and encode, `read_source` / `write_source` |
| `vic2toolmod.script.tokens` | `Token` (kind, text, offset, leading trivia), `TokenKind` |
| `vic2toolmod.script.lexer` | `tokenize(text)` - one compiled regular expression, linear time |
| `vic2toolmod.script.cst` | tree nodes: `Document`, `Assignment`, `Scalar`, `Block`, `ErrorNode`; iteration, lookup, positions |
| `vic2toolmod.script.parser` | `parse_text`, `parse_file`; iterative, error-recovering; indentation hints |
| `vic2toolmod.script.diagnostics` | `Diagnostic`, `Severity`, `LineIndex` (offset -> line/column) |
| `vic2toolmod.script.printer` | `to_text`, `to_data` (fixture JSON), `outline` (CLI view) |
| `vic2toolmod.script.roundtrip` | `check_file` - the lossless check used by CLI and tests |
| `vic2toolmod.files` | finding script files (follows symlinks, visits each folder once) |
| `vic2toolmod.config` | user settings (`~/.config/vic2toolmod/config.toml`, env overrides) |
| `vic2toolmod.cli` | `python -m vic2toolmod parse / roundtrip / errors` |

## Data flow (Phase 1)

```
bytes --textio.decode--> str --lexer--> [Token] --parser--> Document (+ diagnostics)
Document --to_text--> str --textio.encode--> bytes   (identical when unchanged)
```

Positions are character offsets into the decoded text. Line/column numbers are
computed on demand with `LineIndex`.

## Implementation notes

- **No recursion** in the lexer, parser, token iteration or `walk`, so nesting
  depth is unlimited (tested with 50 000 levels).
- **Performance** (Python 3.14, one core): about 15 MB/s for tokenizing +
  parsing; all of RPM (4 672 files, 16.5 MB) in 1.1 s, vanilla + three mods
  (59 MB) in 4 s. A cache will come with the project index if needed.
- **Tokens own their leading trivia.** Comments are therefore available next
  to the node they precede (useful for showing them on blocks), and removing
  a node removes the comments above it.

## Settings

`~/.config/vic2toolmod/config.toml` (Windows: `%APPDATA%\vic2toolmod\config.toml`):

```toml
game_dir = "/home/me/.steam/steam/steamapps/common/Victoria 2"
mod_dirs = ["/home/me/Pulpit/Vic2-MODs/RPM"]
```

`VIC2_GAME_DIR` and `VIC2_MOD_DIR` (separated by `os.pathsep`) override it.
The game-data tests (`tests/test_gamedata.py`) use these settings and are
skipped without them.
