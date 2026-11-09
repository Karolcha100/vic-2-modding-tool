# GUI

A browser app (TypeScript + React + Monaco, built with Vite) served by the
engine's local server (`vic2toolmod/server`). Phase 5 MVP (K54 = D):

- **file tree** of the mod, by content (Events, Decisions, Reforms & parties,
  Modifiers, …) or by folder; mod files only or vanilla too;
- **code editor** (Monaco) with Paradox syntax colours, errors / warnings /
  notes underlined as you type, completion from the schema and the mod's names,
  hover with descriptions and localised names;
- **F12** go to definition, **Shift+F12** find usages (bottom panel),
  **F2** rename everywhere in the mod (changed files are left unsaved);
- **syntax tree** panel: the parsed file, the branch under the cursor
  expanded; clicking a node selects its text;
- **problems** of the open file, **Check mod** for the whole mod;
- **Ctrl+S** saves into the mod folder with a backup of the old file (K36);
  files changed by another editor reload automatically (K30);
- deep links: `…/?token=…&open=events/x.txt&line=12&mode=split&view=reforms`.
- **layout** (Phase 8): drag the borders of the file tree, the syntax tree,
  the bottom panel and (in Split) between code and blocks; double click a
  border for the default size. **Minimap** (the code overview next to the
  scroll bar) on / off above the editor. Sizes and the minimap are remembered
  in the browser. Close a file with its `×`, a middle click on the tab or
  **Alt+W** (Ctrl+W closes the browser tab).
- **another project** (K81 = A): the button with the mod's name in the header
  lists the mods in the game's `mod/` folder, the settings and recently opened
  ones, plus **Vanilla (read-only)** - the game's own files, where saving and
  "Create (write files)" are refused. Any other folder can be typed in.
  Recently opened mods are kept in `recent.json` next to the settings file.
- **icons** (T003): hovering an icon number (`icon = 1` in `crime.txt`,
  religions, national focuses, modifiers, `sprite` of pop types) shows the
  icon from the game's graphics (DDS / TGA, decoded by the engine); block
  cards show it next to the value. Numbers without an icon are errors.
- **right click** in the code: Go to definition, Find usages, Test trigger
  (Ctrl+Alt+T), templates, rename. The same menu (without the templates) on a
  card in the block view; there it looks up the card's value
  (`has_global_flag = x` → the flag `x`) or else its key.
- **blocks** (Phase 6b, K32 = B): the open file as nested cards built from the
  schema - key coloured by role (trigger / effect / scope), scope of each
  block, value editors (yes/no and enum lists, names from the mod's
  registries, numbers, text), `+ add` with only the keys allowed in that
  block (new keys get a sensible first value from the schema), `×` delete,
  problems on the card. Every change is a small text edit applied through the
  editor model, so Ctrl+Z works across code and blocks (K31). **Code / Blocks /
  Split** switch above the editor (K33 = C). Localisation keys (event titles,
  descriptions, option names) show their English text, editable with
  "save text" (K35 = A); literal text such as `"Unacceptable!"` is left alone.
  Event cards have a **preview** button (K6 D): the event window with its
  picture (`gfx/pictures/events/*.tga`, converted to PNG by the server),
  title, description and option names.
- **Reform window** view (K69): drag the issue boxes of `reforms_window`,
  automatic grid, boxes outside the window in red, preview and save.
- **Create** view (K70): new reform, new ideology (with pop support and
  governments copied from a template), parties for an ideology (K58), new
  event (free id, EVTNAME / EVTDESC / EVTOPT localisation), new decision.
- **New country** (K70 E): copies an existing country (the template) - tag in
  `common/countries.txt` (before `dynamic_tags = yes`), country file with the
  new colour and the parties renamed to the new tag, history without dated
  blocks / units / investments, name, adjective and party localisation,
  placeholder flags; capital, cultures, religion, government and
  civilisation can be changed. The country starts without provinces.
- **Templates** (K39 = B): **Create → From a template** fills a template's
  fields (free event ids proposed, known names offered for `ref:` fields) and
  appends the code to a mod file, with its localisation; in the editor
  **Insert template…** (Ctrl+Alt+I) puts it at the cursor (one undo step) and
  **Save selection as template…** (right click) makes your own template - mark
  parts of the code as fields with "Make field from the selected text".
  Template format: see `vic2toolmod/generators/templates.py`; your templates are
  kept in `~/.config/vic2toolmod/templates/` (`%APPDATA%\vic2toolmod\templates`
  on Windows).
- **Analyses** view: interactive pop promotion graph (K59; drag the pop
  types, click a pop type or an arrow for the modifiers and their conditions;
  with a pop type selected its outgoing arrows are red, incoming blue; click
  the background to clear),
  event chains around an event (who fires it, what it fires; missing and
  never-fired events, K6 C), mod vs vanilla with diffs (K6 H), pop statistics
  at the start (K6 I), localisation search and editing (K6 E), git changes of
  the mod folder (K37 = B).

## Running

```sh
cd frontend
npm ci --ignore-scripts     # dependencies, no install scripts (K47)
npm run build               # -> vic2toolmod/server/static_build/ (not in git, K49)
cd ..
.venv/bin/python -m vic2toolmod gui        # opens the browser
.venv/bin/python -m vic2toolmod install-desktop   # menu shortcut (K72 = B)
```

Development with live reload: start `python -m vic2toolmod gui --port 8799
--no-browser`, then `npm run dev` in `frontend/` and open
`http://localhost:5173/?token=<token printed by the server>` (Vite proxies
`/api` to port 8799).

## Dependencies (K47)

Exact versions with a lockfile, installed with `--ignore-scripts`, `npm audit`
clean: `react` / `react-dom` 18.3.1, `monaco-editor` 0.57.0 (with `dompurify`
overridden to 3.4.17, which fixes advisories in the version Monaco pins),
`vite` 8.3.5, `@vitejs/plugin-react` 6.1.2, `typescript` 6.0.3, React types.
Monaco is bundled locally (no CDN); only its core editor and editor features
are included, no other languages.

## Checking the GUI without a person

`frontend/scripts/snapshot.mjs` drives a headless Firefox over WebDriver BiDi
(no extra packages): open a URL, run steps (JavaScript, waits), print console
errors, save a screenshot. The page exposes `window.__vic2.editor` for such
steps.

```sh
firefox --headless --remote-debugging-port 9222 --profile /tmp/ffprofile &
node frontend/scripts/snapshot.mjs "http://127.0.0.1:8799/?token=…&open=events/a.txt" shot.png steps.json
```

## Known limits

- Monaco keeps one kind of line ending per file: a file mixing CRLF and LF is
  unified on save (the status bar says so when such a file is opened).
- Offsets are counted in UTF-16 units in the browser and in code points in the
  engine; they differ only for characters outside the Basic Multilingual Plane,
  which Windows-1252 files cannot contain.
- A server started from the menu keeps running after the browser tab is closed.
