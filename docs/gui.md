# GUI

A browser app (TypeScript + React + Monaco, built with Vite) served by the
engine's local server (`vic2toolmod/server`). Phase 5 MVP (K54 = D):

- **file tree** of the mod, by content (Events, Decisions, Governments,
  ideologies & issues, Countries & parties, Modifiers, …) or by folder; mod
  files only or vanilla too;
- **code editor** (Monaco) with Paradox syntax colours, errors / warnings /
  notes underlined as you type, completion from the schema and the mod's names,
  hover with descriptions and localised names: over a trigger or effect it
  shows what it does, where it may be used, the value in words, how it compares,
  an example and the syntax (the same text as `docs/commands.md`; T006);
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
- **icons** (T003, T006): hovering an icon number (`icon = 1` in `crime.txt`,
  religions, national focuses, modifiers, `sprite` of pop types, unit types,
  rebel types) shows the icon from the game's graphics (DDS / TGA, decoded by
  the engine); block cards show it next to the value. Numbers without an icon
  are errors. **Pictures** named by `picture = …` in events, decisions and
  leaders are shown the same way; a missing picture file is a warning.
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
- **Reform window** view (K69, K80 A): drag the issue boxes of
  `reforms_window`, automatic grid, boxes outside the window in red, preview
  and save. Every element of the window is drawn - issue boxes with their icon,
  name and one row per option (from `reform_option_window`, so a new option of
  an issue shows up by itself), labels - as outlines with names, or with
  **Real graphics**: the game's pictures, the politics panel behind the window
  too. A box's size is what it shows (its elements and option rows), not its
  declared `size`.
- **Interface** view (K80 B): any window of `interface/*.gui` - choose the
  file and the window; elements drawn as outlines or with **Real graphics**;
  click an element (on the canvas or in the element list) to select it, drag to
  move it, drag its corner square to resize it, or type x / y / w / h. Preview
  the changes and save (with a backup); a missing `position` / `size` block is
  added. Positions are relative to the parent and its `orientation`.
- **Create** view (K70): new reform, new ideology (with pop support and
  governments copied from a template), parties for an ideology (K58), new
  event (free id, EVTNAME / EVTDESC / EVTOPT localisation), new decision.
- **New country** (K70 E): copies an existing country (the template) - tag in
  `common/countries.txt` (before `dynamic_tags = yes`), country file with the
  new colour and the parties renamed to the new tag, history without dated
  blocks / units / investments, name, adjective and party localisation,
  placeholder flags; capital, cultures, religion, government and
  civilisation can be changed. **Provinces** (K76 = C): the listed ones get
  `add_core = TAG` in their `history/provinces` file (the country can be
  released there); with **the country exists from the start** it also owns and
  controls them (`owner` / `controller`, taken from the old owner; the notes
  name the old owners and provinces whose dated blocks change the owner later).
  **Choose on the map…** opens the province map (owners' colours at the start
  date, borders, chosen provinces in gold): hover shows the province, its owner
  and cores, a click adds or drops it; Ctrl + wheel zooms.
- **Templates** (K39 = B): **Create → From a template** fills a template's
  fields (free event ids proposed, known names offered for `ref:` fields) and
  appends the code to a mod file, with its localisation; in the editor
  **Insert template…** (Ctrl+Alt+I) puts it at the cursor (one undo step) and
  **Save selection as template…** (right click) makes your own template - mark
  parts of the code as fields with "Make field from the selected text".
  Template format: see `vic2toolmod/generators/templates.py`; your templates are
  kept in `~/.config/vic2toolmod/templates/` (`%APPDATA%\vic2toolmod\templates`
  on Windows).
- **Modifier groups** (T008): modifiers of one block that differ only in one
  number (`num_of_cities = 20 / 30 / 50 …`) as one curve - **right click →
  Edit modifier group…** in the code, one card per group in **Blocks** (with
  a small chart and "Edit as function"), or **Analyses → Modifier groups** for
  every group of the mod. Table of steps, chart of the combined factor (now /
  new), new steps from a function (same factor each step, a straight line, a
  formula of `x`), identical copies changed together. See
  [`tools.md`](tools.md#modifier-groups-analysismodifier_groups-t008).
- **Scripts** view (T007): light Python scripts for repeated jobs (replace a
  text in many files, set a value everywhere, find lines, your own ones);
  fields, an editable code box, **Preview** (output + diff, nothing written)
  and **Apply** (write with a backup). See [`scripts.md`](scripts.md).
- **Meta relations** (T010): Analyses → Meta relations - a rule written once
  (block, target, pop types by strata / name, modifiers in one code box,
  groups edited as a function) copied into every matching pop file between
  marker comments; dashed edges in Pop promotion. See
  [`tools.md`](tools.md#meta-relations-of-pops-generatorsmeta-t010).
- **Formatting** (T011, `vic2toolmod/format.py`): light - indentation (a tab
  per open `{`), one space around `=`, no spaces at line ends, at most one
  empty line in a row, a `{` alone after `key =` joins it (`key = {`); other
  line breaks, comments and strings stay, so one-line blocks stay one-line. **Shift+Alt+F** (or "Format Document" in the editor's
  menu) formats the open file as one undo step, not saved. **Format…** in the
  header formats every `.txt` / `.gui` / `.gfx` file of the mod: files and
  changed lines per folder (folders can be left out), the diff of any file,
  then **Write** with a backup. A file that would not mean exactly the same
  afterwards (tokens and comments are compared), or has unbalanced braces, or
  has unsaved text in the editor, is left out. Commit the mod before, and the
  formatting on its own.
- **Window views** (T015): containers (`windowType` without a picture) are
  outlined, selected and hit as big as what they hold, not their declared
  size; **Ctrl + mouse wheel** (or − / + / Fit) zooms the Reform window and
  Interface drawings; **Hide panel** hides the side panel; in Interface every
  element has a "shown" tick (remembered per window). Tab panels of one window
  lie on top of each other (the game shows one at a time): until you choose,
  only the one with the most sub-windows (in `country_politics`: the reforms
  page) is drawn. In `country_politics.gui` the issue boxes show the issue's
  name and its option rows, as in the Reform window view; texts on real
  pictures get an outline so they stay readable.
- **Bigger windows** (K94, T017): **Resize window…** in Interface gives the
  window a new size (keeping its centre) and stretches its pictures with it.
  **Elements inside**: *keep them where they are* (default: the same place
  from the window's top-left corner; the new room is at the right and the
  bottom), *nearest edge* (elements whose spans overlap along an axis form a
  band that moves as one piece to its nearest edge; panels as big as the
  window grow with it) or *middle* (everything moves by half the growth).
  Elements the game ties to an edge (close button) move by themselves.
  **Pictures of the window** (backgrounds nearly as big as it) are stretched
  by the same amount with their frame kept: by default (`auto`) one even
  column and row just before the window's right / bottom edge are repeated,
  so the panels drawn there get longer and everything left of / above them
  keeps its place; four numbers (px kept at the left, top, right, bottom)
  choose the frame by hand. The drawing shows the stretched pictures at once;
  **Save** writes each as a new file (`gfx/interface/vic2toolmod/<name>_<w>x<h>.dds`)
  and a new sprite (`interface/vic2toolmod_stretched.gfx`) and points only
  that element at it (textures such as `main_bg.dds` are shared by many
  windows), then the window's new size. One Ctrl+Z undoes the size, the moves
  and the stretching. **stretch picture…** does the same for any selected
  element with a picture, with a preview.
- **Map** (K97 A, Analyses → Map): the province map at a start date coloured
  by owner, culture or religion (most pops; colours of `common/cultures.txt` /
  `religion.txt`), trade goods, terrain, continent or pop count, with a legend;
  **Show where it holds** colours by a trigger checked in each province or in
  its owner (yes / no / not known from history). A click shows the province:
  owner, cores, history values, pops, neighbours (clickable) and **Open** its
  history file.
- **Versions** (T025): the whole mod saved under a name (**Save version**),
  the list of versions (what each changed, **Compare with now**) and **Go to
  this version**, which makes the files on disk what they were then; the
  state now is saved first as an automatic version, so nothing is lost. Kept
  as commits of the mod's git repository when it has one (nothing is
  pushed; the view says whether the repository is connected to GitHub),
  else as copies of the changed files (`vic2toolmod.versions`, see
  `docs/tools.md`).
  Refused while the editor has unsaved files.
- **Panels** (T019): side lists (Modifier groups, Meta relations, Pop promotion,
  Event chains, Vs vanilla, Git, Interface / Reform window panels, Format)
  are widened by dragging their inner border; the width is remembered.
  Modifier groups can be narrowed to one folder (file type) or one file.
- **Graphs** (T018): Ctrl + mouse wheel zooms around the pointer, dragging the
  background moves the view, a double click on the background shows all;
  dragging a node moves it without selecting it.
- **Blocks** (T020): value fields are as wide as their text; long values and
  localisation texts (event titles, descriptions) get a field over the whole
  width of the card, on several lines (Enter still commits; values stay one line).
- **Syntax tree** (T016): **Syntax tree** above the code shows / hides it, and it
  is hidden outside the code view; any branch can be folded, also the one with
  the cursor.
- **Undo and navigation** (T012): Ctrl+Z undoes and Ctrl+Shift+Z (or Ctrl+Y)
  redoes everywhere - in the code and blocks (one shared history) and in the
  Interface and Reform window views (moves and sizes, one step per drag);
  text fields keep their own undo. The **mouse's back / forward buttons** and
  Alt+Left / Alt+Right go through the views, open files (back to the line you
  were on), tabs, chosen items (script, modifier group, interface window) and
  dialogs ("back" closes a dialog), like in a web browser. Leaving the page
  with unsaved text asks first.
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

**One server, gone with the window** (T009, `vic2toolmod/server/lifecycle.py`):

- the server stops a few seconds after the last browser tab of the GUI is
  closed (a reload is fine), or after 3 minutes without any request when the
  browser was killed; `gui --stay` keeps it running;
- a second plain `gui` (the menu shortcut) does not start another server: it
  opens a tab on the running one (`gui-server.json` next to the settings file
  says where it is). If the tool's code changed meanwhile, it stops the old
  server and starts a new one;
- when the tool's code changes while the GUI is open, a bar offers
  **Restart now**: the server starts again on its new code at the same
  address and the page reloads (unsaved text is lost - you are asked first);
- the footer shows the server's memory (Linux).

Development with live reload: start `python -m vic2toolmod gui --port 8799
--no-browser --stay`, then `npm run dev` in `frontend/` and open
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
