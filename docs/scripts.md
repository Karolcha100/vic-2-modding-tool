# Scripts: light Python for repeated jobs (T007)

A script is a small Python file that the tool runs on the open mod: replace a
text in many files, give a key a new value everywhere, list lines, or anything
else you can write in Python with the tool's engine at hand.

**Nothing is written while a script runs.** The script only *plans* changes;
you see them as a diff first and write them only on request ("Apply" in the
GUI, `--write` on the command line). Every changed file is copied to a backup
folder first (`~/.local/share/vic2toolmod/backups/<time>/`).

## Running a script

**GUI:** the **Scripts** button in the header. Choose a script, fill its
fields, press **Preview** (output and diff, nothing written), then
**Apply (write files)**. The code box shows the script; edit it and run it
straight away, or save it as your own script.

**Command line:**

```sh
# list the scripts and their fields
.venv/bin/python -m vic2toolmod run-script --list
# preview (prints the diff)
.venv/bin/python -m vic2toolmod run-script replace_text \
    -p files='events/501_*.txt' -p old=CT_regional_elects_ -p new=CT_ruling_elects_
# the same, written (with a backup)
.venv/bin/python -m vic2toolmod run-script replace_text -p ... --write
# your own script, or any .py file
.venv/bin/python -m vic2toolmod run-script own/my_script -p tag=ENG
.venv/bin/python -m vic2toolmod run-script ~/fix.py
```

`--mod` / `--game` choose other folders than the configured ones. A script
that fails (an exception) writes nothing; its error and line are shown.

## Built-in scripts

| Script | Fields | What it does |
|---|---|---|
| `replace_text` | `files`, `old`, `new`, `regex` | replaces a text (or a regular expression) in all matching files |
| `find_text` | `files`, `text`, `regex`, `game` | lists matching lines (`file:line: text`); changes nothing |
| `set_value` | `files`, `key`, `only_if`, `inside`, `value` | gives every `key = value` a new value, optionally only an old value or only inside a block (e.g. `months` inside `mean_time_to_happen`); comments and spacing stay |

## Writing a script

```python
#@ name: Rename a flag
#@ description: Rename a country flag in every event and decision.
#@ param: old | the flag's current name
#@ param: new | the new name
#@ param: whole:bool = yes | only whole names (not CT_x_2 when renaming CT_x)

import re

old = re.escape(params["old"])
pattern = rf"\b{old}\b" if params["whole"] else old
n = mod.replace(pattern, params["new"], files="*.txt", regex=True)
print(n, "replacement(s) in", len(mod.changes), "file(s)")
```

**Header** (lines at the top starting with `#@`):

- `#@ name: …` - the shown name; `#@ description: …` - one or two sentences;
- `#@ param: name[:type][ = default][ | help]` - a field. Types: `text` (the
  default), `int` (a whole number), `bool` (`yes` / `no` in the form, `True` /
  `False` in Python). The header ends at the first line of code.

**Names the script gets:**

- `params` - the field values (`params["old"]`, `params["whole"]` …);
- `mod` - the helpers below; `print()` goes to the output.

| `mod.` | What it does |
|---|---|
| `files(pattern="*.txt", only_mod=True)` | paths of matching files (`events/*.txt`; `*` also crosses folders; any case). `only_mod=False` adds the game files the mod does not replace |
| `read(rel)` | text of a file, with the changes the script already planned |
| `write(rel, text)` | plan new text for a file; a new file, or a game file, is created in the mod. Refused for a file with unsaved changes in the editor |
| `replace(old, new, files="*.txt", regex=False, only_mod=True)` | replace in all matching files, returns the count; with `regex`, Python regular expressions (`\1`, `\g<name>` in `new`) |
| `find(text, files="*.txt", regex=False, only_mod=True)` | matching lines: objects with `rel`, `line`, `text` |
| `document(rel)` | the parsed file (syntax tree, `vic2toolmod.script.cst`): `doc.walk()`, `assignment.key_text`, `scalar.value`, … |
| `names(kind)` | names defined in the project: `country`, `event`, `modifier`, `country_flag`, `variable`, … |
| `changes` | the changes planned so far (`.rel`, `.old_text`, `.new_text`) |
| `ws` | the whole engine (`vic2toolmod.workspace.Workspace`) |

Line breaks and the encoding of each file stay as they were (texts are
read with their own line breaks, e.g. `\r\n`). To change the code precisely
(only values, keeping comments), edit through the syntax tree as the built-in
`set_value` does: `vic2toolmod.edit.replace_token_text(scalar, "new")` gives a
text edit, `vic2toolmod.edit.apply_edits(doc.text, edits)` the new text.

## Where scripts are kept

- built-in: `vic2toolmod/pyscripts_data/` (read-only; edit one in the GUI and
  save it under your own name);
- yours: `~/.config/vic2toolmod/scripts/` (`%APPDATA%\vic2toolmod\scripts` on
  Windows), one `.py` file per script; "Save as my script" in the GUI writes
  there, and any `.py` file you put there is listed.

## Safety

A script is ordinary Python run with your rights, like any program: it can
read and write anything on the computer, not only through `mod`. Run only
scripts you wrote or read. The GUI server runs them only for requests with its
secret token (127.0.0.1 only). A script that never ends stops the GUI server:
close it and start it again.

The engine: `vic2toolmod/pyscripts.py`.
