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
- deep links: `…/?token=…&open=events/x.txt&line=12`.

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
