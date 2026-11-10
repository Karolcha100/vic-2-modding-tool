import { useCallback, useEffect, useRef, useState } from "react";
import { api, applyEdits, sayBye, type Diagnostic, type FileEntry, type ModGroup, type OutlineNode, type Usage } from "./api";
import { hooks, LANGUAGE, monaco, uriOf } from "./monacoSetup";
import { FileTree } from "./components/FileTree";
import { Outline } from "./components/Outline";
import { ReformWindow } from "./components/ReformWindow";
import { Creators } from "./components/Creators";
import { Blocks } from "./components/Blocks";
import { Analyses } from "./components/Analyses";
import { FormatMod } from "./components/FormatMod";
import { GroupEditor } from "./components/ModGroups";
import { inTextField, navGet, navSet, undoKey, undoTarget, useNav, useNavModal } from "./nav";
import { Scripts } from "./components/Scripts";
import { Tester } from "./components/Tester";
import { TemplateSave, TemplateUse } from "./components/Templates";
import type { Fact } from "./api";
import { Splitter, useStored } from "./components/Layout";
import { ProjectPicker } from "./components/ProjectPicker";
import { GuiEditor } from "./components/GuiEditor";

interface OpenFile {
  rel: string;
  model: monaco.editor.ITextModel;
  saved: string; // text on disk (as last loaded / saved)
  synced: string; // text the server last received
  diagnostics: Diagnostic[];
  encoding: string;
  mixedEol: boolean;
}

type Bottom =
  | { kind: "problems" }
  | { kind: "usages"; title: string; usages: Usage[] }
  | { kind: "mod"; files: { rel: string; diagnostics: Diagnostic[] }[] }
  | { kind: "tester"; rel: string; offset: number; facts: Fact[] };

const SEVERITY = {
  error: monaco.MarkerSeverity.Error,
  warning: monaco.MarkerSeverity.Warning,
  info: monaco.MarkerSeverity.Info,
};

const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;

/** Diagnostic codes hidden unless "show hidden notes" is on (K88 = B). */
const HIDDEN_CODES = new Set(["schema.scope-alice"]);

export function App() {
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [modDir, setModDir] = useState<string | null>(null);
  const [readOnly, setReadOnly] = useState(false);
  const [picker, openPicker, closePicker] = useNavModal<true>("picker");
  const [formatting, openFormat, closeFormat] = useNavModal<true>("format");
  const [open, setOpen] = useState<OpenFile[]>([]);
  const [current, setCurrent] = useState<string | null>(null);
  const [outline, setOutline] = useState<OutlineNode[]>([]);
  const [cursor, setCursor] = useState(0);
  const [bottom, setBottom] = useState<Bottom>({ kind: "problems" });
  const [status, setStatus] = useState("Loading…");
  /** The server: fine, running older code than is on disk, restarting, or gone. */
  const [memory, setMemory] = useState<number | null>(null);
  const [server, setServer] = useState<"ok" | "stale" | "restarting" | "gone">("ok");
  // Views, modes, the open file and dialogs are steps of the browser's history:
  // mouse back / forward and Alt+Left / Alt+Right move through them (T012, nav.ts).
  const [mode, setMode] = useNav<"code" | "blocks" | "split">(
    "mode", (new URLSearchParams(location.search).get("mode") as "blocks" | "split" | null) ?? "code",
  );
  const [view, setView] = useNav<"code" | "reforms" | "interface" | "create" | "analyses" | "scripts">(
    "view", (new URLSearchParams(location.search).get("view") as "reforms" | "interface" | "create" | "analyses" | "scripts" | null) ?? "code",
  );
  const [navFile] = useNav<{ rel: string; line: number } | null>("file", null);
  const shown = useRef<{ rel: string; line: number } | null>(null); // what openFile shows / is opening
  const [mgModal, setMgModal, closeMgModal] = useNavModal<{ rel: string; group: ModGroup }>("modgroup");
  const [tplModal, setTplModal, closeTplModal] = useNavModal<{ kind: "insert" } | { kind: "save"; text: string; folder: string }>("template");
  const viewRef = useRef(view);
  viewRef.current = view;
  const [, force] = useState(0);
  // Panel sizes and the minimap, remembered in this browser (T005).
  // Scope notes Project Alice accepts (K88 = B): hidden unless asked for.
  const [showHidden, setShowHidden] = useStored("vic2.hiddenNotes", false);
  const hiddenRef = useRef(showHidden);
  hiddenRef.current = showHidden;
  const [leftW, setLeftW] = useStored("vic2.left", 280);
  const [rightW, setRightW] = useStored("vic2.right", 300);
  const [bottomH, setBottomH] = useStored("vic2.bottom", 180);
  const [blocksW, setBlocksW] = useStored("vic2.blocks", 0); // 0 = half of the editor row
  const [minimap, setMinimap] = useStored("vic2.minimap", true);
  // The syntax tree: hidden on request, and always outside the code view (T016).
  const [treeOn, setTreeOn] = useStored("vic2.tree", true);
  const treeShown = treeOn && view === "code";
  const host = useRef<HTMLDivElement>(null);
  const editor = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const files_ = useRef(new Map<string, OpenFile>());
  const timer = useRef<number | undefined>(undefined);
  const currentRef = useRef<string | null>(null); // `current` for callbacks created earlier
  currentRef.current = current;

  const rerender = () => force((n) => n + 1);
  const fileOf = (rel: string | null) => (rel ? files_.current.get(rel) : undefined);

  const markers = (f: OpenFile) =>
    monaco.editor.setModelMarkers(
      f.model,
      "vic2toolmod",
      f.diagnostics.filter((d) => hiddenRef.current || !HIDDEN_CODES.has(d.code)).map((d) => ({
        severity: SEVERITY[d.severity],
        message: `${d.message} [${d.code}]`,
        startLineNumber: d.line,
        startColumn: d.column,
        endLineNumber: d.end_line,
        endColumn: Math.max(d.end_column, d.column + 1),
      })),
    );

  const refreshOutline = useCallback(async (rel: string) => {
    try {
      setOutline((await api.outline(rel)).items);
    } catch {
      setOutline([]);
    }
  }, []);

  /** Send the editor text to the server (if changed) and update diagnostics. */
  const sync = useCallback(async (rel: string) => {
    const f = fileOf(rel);
    if (!f) return;
    const text = f.model.getValue();
    if (text === f.synced) return;
    f.synced = text;
    const report = await api.buffer(rel, text);
    f.diagnostics = report.diagnostics;
    markers(f);
    if (rel === currentRef.current) refreshOutline(rel);
    rerender();
  }, [refreshOutline]);

  hooks.sync = async (rel) => sync(rel);

  /** Open a file (loading it if needed) and optionally reveal a line; `record`: as a navigation step. */
  const openFile = useCallback(async (rel: string, line?: number, record = true) => {
    if (record) {
      // "Back" returns to where the cursor was, not only to the file.
      const here = currentRef.current;
      const at = editor.current?.getPosition()?.lineNumber;
      if (here && at && navGet<{ rel: string }>("file")?.rel === here) navSet({ file: { rel: here, line: at } }, "replace");
      navSet({ file: { rel, line: line ?? 0 } });
    }
    shown.current = { rel, line: line ?? 0 };
    let f = fileOf(rel);
    if (!f) {
      setStatus(`Opening ${rel}…`);
      const data = await api.file(rel);
      const crlf = (data.text.match(/\r\n/g) ?? []).length;
      const lf = (data.text.match(/\n/g) ?? []).length - crlf;
      const model = monaco.editor.createModel(data.text, LANGUAGE, uriOf(rel));
      f = { rel, model, saved: model.getValue(), synced: data.text, diagnostics: data.diagnostics, encoding: data.encoding, mixedEol: crlf > 0 && lf > 0 };
      files_.current.set(rel, f);
      markers(f);
      model.onDidChangeContent(() => {
        rerender();
        window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => sync(rel), 400);
      });
      setOpen([...files_.current.values()]);
      setStatus(`${rel} · ${data.encoding}${f.mixedEol ? " · mixed line endings will be unified on save" : ""}`);
    }
    editor.current?.setModel(f.model);
    setCurrent(rel);
    refreshOutline(rel);
    if (line) {
      editor.current?.revealLineInCenter(line);
      editor.current?.setPosition({ lineNumber: line, column: 1 });
    }
    editor.current?.focus();
  }, [refreshOutline, sync]);

  const save = useCallback(async (rel: string | null) => {
    const f = fileOf(rel);
    if (!f) return;
    try {
      const text = f.model.getValue();
      const r = await api.save(f.rel, text);
      f.saved = text;
      setStatus(`Saved ${f.rel}${r.backup ? ` (backup: ${r.backup})` : ""}`);
      rerender();
    } catch (e) {
      setStatus(`Not saved: ${(e as Error).message}`);
    }
  }, []);

  // -- navigation shared by the code editor and the block view --------------------------
  const definitionAt = useCallback(async (rel: string, offset: number) => {
    await sync(rel);
    const { definition } = await api.definition(rel, offset);
    if (definition) openFile(definition.file, definition.line);
    else setStatus("No definition here");
  }, [sync, openFile]);
  const usagesAt = useCallback(async (rel: string, offset: number, word: string) => {
    await sync(rel);
    setStatus("Finding usages…");
    const { usages } = await api.references(rel, offset);
    setBottom({ kind: "usages", title: `${usages.length} usages of ${word}`, usages });
    setStatus("");
  }, [sync]);
  const testerAt = useCallback(async (rel: string, offset: number) => {
    await sync(rel);
    try {
      const r = await api.trigger(rel, offset);
      setBottom({ kind: "tester", rel, offset, facts: r.facts });
    } catch (e) {
      setStatus(`Trigger tester: ${(e as Error).message}`);
    }
  }, [sync]);

  /** Insert text at the cursor, indented like the cursor's line (one undo step). */
  const insertAtCursor = (text: string) => {
    const ed = editor.current; const m = ed?.getModel(); const p = ed?.getPosition();
    if (!ed || !m || !p) return;
    const line = m.getLineContent(p.lineNumber);
    const indent = /^[\t ]*/.exec(line)![0];
    let body = text.replace(/\r\n/g, "\n").replace(/\n$/, "").split("\n").map((l, i) => (i && l ? indent + l : l)).join("\n");
    // Code before or after the cursor on this line: put the template on lines of its own.
    if (line.slice(0, p.column - 1).trim()) body = "\n" + indent + body;
    if (line.slice(p.column - 1).trim()) body += "\n" + indent;
    ed.pushUndoStop();
    ed.executeEdits("template", [{ range: new monaco.Range(p.lineNumber, p.column, p.lineNumber, p.column), text: body, forceMoveMarkers: true }]);
    ed.pushUndoStop();
    ed.focus();
  };

  useEffect(() => { editor.current?.updateOptions({ minimap: { enabled: minimap } }); }, [minimap]);

  // -- editor + actions ------------------------------------------------------------
  useEffect(() => {
    if (!host.current) return;
    const ed = monaco.editor.create(host.current, {
      automaticLayout: true,
      theme: dark ? "vs-dark" : "vs",
      fontSize: 13,
      minimap: { enabled: minimap },
      tabSize: 4,
      insertSpaces: false,
      renderWhitespace: "boundary",
    });
    editor.current = ed;
    // For scripted checks of the GUI (frontend/scripts/snapshot.mjs).
    (window as unknown as { __vic2: unknown }).__vic2 = { editor: ed, monaco };
    ed.onDidChangeCursorPosition((e: monaco.editor.ICursorPositionChangedEvent) => {
      const m = ed.getModel();
      if (m) setCursor(m.getOffsetAt(e.position));
    });
    const here = () => {
      const m = ed.getModel();
      const p = ed.getPosition();
      return m && p ? { rel: decodeURIComponent(m.uri.path.slice(1)), offset: m.getOffsetAt(p), m } : null;
    };
    // Redo also under Ctrl+Shift+Z (T012), next to Monaco's Ctrl+Y.
    ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyZ, () => ed.trigger("keyboard", "redo", null));
    ed.addAction({
      id: "vic2.save", label: "Save", keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS],
      run: () => { const h = here(); if (h) save(h.rel); },
    });
    ed.addAction({
      id: "vic2.definition", label: "Go to definition", keybindings: [monaco.KeyCode.F12], contextMenuGroupId: "navigation",
      run: () => { const h = here(); if (h) definitionAt(h.rel, h.offset); },
    });
    ed.addAction({
      id: "vic2.references", label: "Find usages", keybindings: [monaco.KeyMod.Shift | monaco.KeyCode.F12], contextMenuGroupId: "navigation",
      run: () => {
        const h = here(); if (!h) return;
        usagesAt(h.rel, h.offset, h.m.getWordAtPosition(ed.getPosition()!)?.word ?? "");
      },
    });
    ed.addAction({
      id: "vic2.tester", label: "Test trigger (K53)", keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyMod.Alt | monaco.KeyCode.KeyT],
      contextMenuGroupId: "navigation",
      run: () => { const h = here(); if (h) testerAt(h.rel, h.offset); },
    });
    ed.addAction({
      id: "vic2.close", label: "Close file", keybindings: [monaco.KeyMod.Alt | monaco.KeyCode.KeyW],
      run: () => { if (currentRef.current) closeRef.current(currentRef.current); },
    });
    ed.addAction({
      id: "vic2.template.insert", label: "Insert template…", keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyMod.Alt | monaco.KeyCode.KeyI],
      contextMenuGroupId: "1_modification",
      run: () => { if (here()) setTplModal({ kind: "insert" }); },
    });
    ed.addAction({
      id: "vic2.modgroup", label: "Edit modifier group…", contextMenuGroupId: "1_modification",
      run: async () => {
        const h = here(); if (!h) return;
        await sync(h.rel);
        const { groups } = await api.modGroups(h.rel);
        const inside = (g: ModGroup) => g.steps[0].start <= h.offset && h.offset <= g.steps[g.steps.length - 1].end;
        const g = groups.find((x) => x.steps.some((st) => st.start <= h.offset && h.offset <= st.end)) ?? groups.find(inside);
        if (g) setMgModal({ rel: h.rel, group: g });
        else setStatus("No modifier group here: put the cursor in one of several modifiers that differ only in one number");
      },
    });
    ed.addAction({
      id: "vic2.template.save", label: "Save selection as template…", contextMenuGroupId: "1_modification",
      run: () => {
        const h = here(); const sel = ed.getSelection();
        if (!h || !sel || sel.isEmpty()) { setStatus("Select the code for the template first"); return; }
        const whole = sel.setStartPosition(sel.startLineNumber, 1); // keep the first line's indentation for dedent
        setTplModal({ kind: "save", text: h.m.getValueInRange(whole), folder: h.rel.includes("/") ? h.rel.slice(0, h.rel.lastIndexOf("/")) : "" });
      },
    });
    ed.addAction({
      id: "vic2.rename", label: "Rename everywhere", keybindings: [monaco.KeyCode.F2], contextMenuGroupId: "1_modification",
      run: async () => {
        const h = here(); if (!h) return;
        const word = h.m.getWordAtPosition(ed.getPosition()!)?.word ?? "";
        const name = window.prompt(`Rename "${word}" everywhere in the mod to:`, word);
        if (!name || name === word) return;
        await sync(h.rel);
        const { edits } = await api.rename(h.rel, h.offset, name);
        for (const [rel, list] of Object.entries(edits)) {
          await openFile(rel);
          const f = fileOf(rel)!;
          f.model.setValue(applyEdits(f.model.getValue(), list));
        }
        await openFile(h.rel);
        setStatus(`Renamed in ${Object.keys(edits).length} files - not saved yet (Ctrl+S in each)`);
      },
    });
    return () => ed.dispose();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // -- project + polling for changes on disk (K30) -------------------------------------
  useEffect(() => {
    api.project().then((p) => {
      setFiles(p.files);
      setModDir(p.mod_dir);
      setReadOnly(!!p.read_only);
      setStatus(`${p.files.length} files · mod: ${p.mod_dir ?? "(none)"}`);
      // Deep link: ?token=…&open=events/x.txt&line=12
      const params = new URLSearchParams(location.search);
      const rel = params.get("open");
      if (rel) {
        const line = Number(params.get("line")) || undefined;
        navSet({ file: { rel, line: line ?? 0 } }, "replace");
        openFile(rel, line, false);
      }
    }).catch((e) => setStatus(`Cannot reach the engine: ${(e as Error).message}`));
    window.addEventListener("pagehide", sayBye);
    let misses = 0;
    const id = window.setInterval(async () => {
      let changed: string[];
      try {
        const r = await api.changed();
        changed = r.changed; misses = 0;
        setMemory(r.memory_mb);
        setServer((s) => (s === "restarting" ? s : r.stale ? "stale" : "ok"));
      } catch {
        if (++misses >= 2) setServer((s) => (s === "restarting" ? s : "gone"));
        return;
      }
      if (!changed.length) return;
      const p = await api.project();
      setFiles(p.files);
      for (const rel of changed) {
        const f = [...files_.current.values()].find((x) => x.rel.toLowerCase() === rel);
        if (f && f.model.getValue() === f.saved) {
          const data = await api.file(f.rel);
          if (data.text !== f.model.getValue()) {
            f.model.setValue(data.text);
            f.saved = f.model.getValue();
            f.synced = data.text;
            setStatus(`${f.rel} changed on disk - reloaded`);
          }
        }
      }
    }, 3000);
    return () => { window.clearInterval(id); window.removeEventListener("pagehide", sayBye); };
  }, []);

  // "Back" / "forward" changed the open file (or its line): show it without a new step.
  useEffect(() => {
    if (!navFile) return;
    const s = shown.current;
    if (s && s.rel === navFile.rel && s.line === navFile.line) return;
    openFile(navFile.rel, navFile.line || undefined, false);
  }, [navFile, openFile]);

  // Ctrl+Z / Ctrl+Shift+Z (Ctrl+Y) outside text fields: undo / redo in the shown view (T012).
  // In the code and block views that is the editor's own undo (shared by both).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const k = undoKey(e);
      if (!k || inTextField(e.target)) return;
      if (viewRef.current === "code") {
        const ed = editor.current;
        if (!ed?.getModel()) return;
        ed.trigger("keyboard", k === 1 ? "undo" : "redo", null);
      } else {
        const t = undoTarget();
        if (!t) return;
        if (k === 1) t.undo(); else t.redo();
      }
      e.preventDefault();
    };
    // Leaving the page with unsaved text (e.g. "back" past the first step) asks first.
    const onLeave = (e: BeforeUnloadEvent) => {
      if ([...files_.current.values()].some((f) => f.model.getValue() !== f.saved)) e.preventDefault();
    };
    const onStatusEvent = (e: Event) => setStatus((e as CustomEvent<string>).detail);
    window.addEventListener("vic2-status", onStatusEvent);
    window.addEventListener("keydown", onKey);
    window.addEventListener("beforeunload", onLeave);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("beforeunload", onLeave);
      window.removeEventListener("vic2-status", onStatusEvent);
    };
  }, []);

  // Restart the server on its new code (same address), then load the page again.
  const restartServer = async () => {
    if (dirty.size && !window.confirm(`${dirty.size} file(s) have unsaved changes that will be lost. Restart anyway?`)) return;
    setServer("restarting");
    try { await api.restart(); } catch { /* it may already be going down */ }
    for (let i = 0; i < 120; i++) {
      await new Promise((r) => window.setTimeout(r, 500));
      try { if (!(await api.ping()).stale) { location.reload(); return; } } catch { /* not up yet */ }
    }
    setServer("gone");
  };

  const cur = fileOf(current);
  const dirty = new Set(open.filter((f) => f.model.getValue() !== f.saved).map((f) => f.rel));
  const counts = (ds: Diagnostic[]) => ({
    e: ds.filter((d) => d.severity === "error").length,
    w: ds.filter((d) => d.severity === "warning").length,
    i: ds.filter((d) => d.severity === "info").length,
  });
  const shownDiagnostics = (cur?.diagnostics ?? []).filter((d) => showHidden || !HIDDEN_CODES.has(d.code));
  const hiddenCount = (cur?.diagnostics.length ?? 0) - shownDiagnostics.length;
  const c = counts(shownDiagnostics);

  /** Apply engine edits to the open file through Monaco (one undo step, K31). */
  const applyEdits_ = (edits: { start: number; end: number; new_text: string }[]) => {
    const f = fileOf(current);
    if (!f) return;
    const ops = edits.map((e) => {
      const a = f.model.getPositionAt(e.start);
      const b = f.model.getPositionAt(e.end);
      return { range: new monaco.Range(a.lineNumber, a.column, b.lineNumber, b.column), text: e.new_text };
    });
    f.model.pushStackElement();
    f.model.pushEditOperations([], ops, () => null);
    f.model.pushStackElement();
  };
  const selectRange = (start: number, end: number) => {
    const ed = editor.current;
    const m = ed?.getModel();
    if (!ed || !m) return;
    const a = m.getPositionAt(start);
    const b = m.getPositionAt(end);
    ed.setSelection(new monaco.Range(a.lineNumber, a.column, b.lineNumber, b.column));
    ed.revealRangeInCenter(new monaco.Range(a.lineNumber, a.column, b.lineNumber, b.column));
  };

  const selectNode = (n: OutlineNode) => {
    const ed = editor.current;
    const m = ed?.getModel();
    if (!ed || !m) return;
    const a = m.getPositionAt(n.start);
    const b = m.getPositionAt(n.end);
    ed.setSelection(new monaco.Range(a.lineNumber, a.column, b.lineNumber, b.column));
    ed.revealRangeInCenter(new monaco.Range(a.lineNumber, a.column, b.lineNumber, b.column));
  };

  const closeRef = useRef<(rel: string) => void>(() => undefined);
  const closeTab = (rel: string) => {
    const f = fileOf(rel);
    if (!f) return;
    if (f.model.getValue() !== f.saved && !window.confirm(`${rel} has unsaved changes. Close anyway?`)) return;
    api.revert(rel).catch(() => undefined);
    f.model.dispose();
    files_.current.delete(rel);
    const rest = [...files_.current.values()];
    setOpen(rest);
    if (current === rel) {
      if (rest.length) openFile(rest[rest.length - 1].rel);
      else { editor.current?.setModel(null); setCurrent(null); setOutline([]); }
    }
  };
  closeRef.current = closeTab;

  return (
    <div className="app" style={{ gridTemplateColumns: `${leftW}px minmax(0, 1fr) ${treeShown ? rightW : 0}px`, gridTemplateRows: `36px minmax(0, 1fr) ${bottomH}px 24px` }}>
      {server !== "ok" && (
        <div className={`server-bar ${server}`}>
          {server === "stale" && <>The tool was updated: this window still runs the old version. <button onClick={restartServer}>Restart now</button></>}
          {server === "restarting" && <>Restarting the server…</>}
          {server === "gone" && <>The server is not running any more. Start vic2toolmod again; unsaved text stays in this window until you close it.</>}
        </div>
      )}
      <header>
        <b>vic2toolmod</b>
        <button className="project-button" title="Open another mod or the game's own files" onClick={() => openPicker(true)}>
          {modDir ? modDir.split(/[\\/]/).filter(Boolean).pop() : "Vanilla"} ▾
        </button>
        {readOnly && <span className="chip">read-only</span>}
        <span className="muted small">{modDir ?? "the game's own files"}</span>
        <span className="spacer" />
        <button className={view === "code" ? "on" : ""} onClick={() => setView("code")}>Editor</button>
        <button className={view === "reforms" ? "on" : ""} onClick={() => setView("reforms")}>Reform window</button>
        <button className={view === "interface" ? "on" : ""} onClick={() => setView("interface")} title="Any window of interface/*.gui">Interface</button>
        <button className={view === "create" ? "on" : ""} onClick={() => setView("create")}>Create</button>
        <button className={view === "analyses" ? "on" : ""} onClick={() => setView("analyses")}>Analyses</button>
        <button className={view === "scripts" ? "on" : ""} onClick={() => setView("scripts")} title="Light Python scripts for repeated jobs">Scripts</button>
        <button onClick={() => save(current)} disabled={readOnly || !current || !dirty.has(current)}>Save (Ctrl+S)</button>
        <button onClick={() => openFormat(true)} disabled={readOnly} title="Format every file of the mod (preview first). One file: Shift+Alt+F in the editor">Format…</button>
        <button onClick={async () => { setStatus("Checking the whole mod…"); setBottom({ kind: "mod", files: (await api.check()).files }); setStatus(""); }}>Check mod</button>
      </header>
      <aside className="left">
        <FileTree files={files} current={current} dirty={dirty} onOpen={(rel) => openFile(rel)} />
        <Splitter edge="right" size={leftW} setSize={setLeftW} min={140} max={700} reset={280} />
      </aside>
      <main>
        {view === "analyses" && (
          <Analyses onStatus={setStatus} onOpen={(rel, line) => { setView("code"); openFile(rel, line); }} />
        )}
        {view === "scripts" && (
          <Scripts readOnly={readOnly} onStatus={setStatus} onOpen={(rel) => { setView("code"); openFile(rel); }} />
        )}
        {view === "create" && (
          <Creators onStatus={setStatus} files={files.map((f) => f.rel)} onOpen={(rel) => { setView("code"); openFile(rel); }} />
        )}
        {view === "interface" && (
          <GuiEditor files={files.map((f) => f.rel)} onStatus={setStatus} onOpen={(rel, line) => { setView("code"); openFile(rel, line); }} />
        )}
        {view === "reforms" && (
          <ReformWindow onStatus={setStatus} onOpen={(rel, line) => { setView("code"); openFile(rel, line); }} />
        )}
        <div className="tabs" style={view === "code" ? undefined : { display: "none" }}>
          <div className="mode-switch">
            {(["code", "blocks", "split"] as const).map((m) => (
              <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>{m === "code" ? "Code" : m === "blocks" ? "Blocks" : "Split"}</button>
            ))}
            <button className={minimap ? "on" : ""} title="Code overview next to the scroll bar" onClick={() => setMinimap(!minimap)}>Minimap</button>
            <button className={treeOn ? "on" : ""} title="The syntax tree on the right" onClick={() => setTreeOn(!treeOn)}>Syntax tree</button>
          </div>
          {open.map((f) => (
            <div key={f.rel} className={"tab" + (f.rel === current ? " active" : "")} onClick={() => openFile(f.rel)}
              onAuxClick={(e) => { if (e.button === 1) { e.preventDefault(); closeTab(f.rel); } }}
              title={`${f.rel}\nMiddle click or Alt+W closes it`}>
              {dirty.has(f.rel) ? "● " : ""}{f.rel.slice(f.rel.lastIndexOf("/") + 1)}
              <span className="close" title="Close (Alt+W)" onClick={(e) => { e.stopPropagation(); closeTab(f.rel); }}>×</span>
            </div>
          ))}
        </div>
        <div className="editor-row" style={view === "code" ? undefined : { display: "none" }}>
          <div className="editor" ref={host} style={mode === "blocks" ? { display: "none" } : undefined} />
          {mode === "split" && cur && (
            <Splitter edge="between" size={blocksW} setSize={setBlocksW} min={200} max={2000} reset={0}
              measure={(el) => el.nextElementSibling?.getBoundingClientRect().width ?? 0} />
          )}
          {mode !== "code" && cur && (
            <Blocks
              width={mode === "split" && blocksW ? blocksW : undefined}
              actions={{
                definition: (o) => definitionAt(cur.rel, o),
                usages: (o, w) => usagesAt(cur.rel, o, w),
                tester: (o) => testerAt(cur.rel, o),
                editGroup: (g) => setMgModal({ rel: cur.rel, group: g }),
              }}
              rel={cur.rel}
              version={cur.model.getVersionId()}
              diagnostics={cur.diagnostics}
              apply={applyEdits_}
              sync={() => sync(cur.rel)}
              select={(a, b) => { if (mode === "blocks") setMode("split"); selectRange(a, b); }}
            />
          )}
        </div>
        {!current && view === "code" && <div className="empty">Open a file from the tree on the left.</div>}
      </main>
      <aside className="right" style={treeShown ? undefined : { display: "none" }}>
        <Splitter edge="left" size={rightW} setSize={setRightW} min={40} max={800} reset={300} />
        <div className="panel-title">Syntax tree <span className="spacer" /><span className="link-like" title="Hide (the Syntax tree button above the code shows it again)" onClick={() => setTreeOn(false)}>×</span></div>
        <Outline items={outline} cursor={cursor} onSelect={selectNode} />
      </aside>
      <section className="bottom">
        <Splitter edge="top" size={bottomH} setSize={setBottomH} min={40} max={900} reset={180} />
        <div className="panel-title">
          <span className={bottom.kind === "problems" ? "on" : ""} onClick={() => setBottom({ kind: "problems" })}>
            This file: {c.e} errors, {c.w} warnings, {c.i} notes
          </span>
          {(hiddenCount > 0 || showHidden) && (
            <label className="hidden-notes" title="Scope notes for commands Project Alice (open-source Victoria 2) accepts in that scope (K88)">
              <input type="checkbox" checked={showHidden} onChange={(e) => {
                setShowHidden(e.target.checked);
                hiddenRef.current = e.target.checked;
                files_.current.forEach((f) => markers(f));
              }} />
              {showHidden ? "showing notes Project Alice accepts" : `${hiddenCount} hidden notes (Project Alice accepts)`}
            </label>
          )}
          {bottom.kind === "usages" && <span className="on">{bottom.title}</span>}
          {bottom.kind === "mod" && <span className="on">Whole mod: {bottom.files.length} files with problems</span>}
          {bottom.kind === "tester" && <span className="on">Trigger tester ({bottom.facts.length} facts)</span>}
        </div>
        <div className="bottom-list">
          {bottom.kind === "problems" && shownDiagnostics.map((d, i) => (
            <div key={i} className={`row ${d.severity}`} onClick={() => cur && openFile(cur.rel, d.line)}>
              <span className="sev">{d.severity}</span> {d.line}:{d.column} {d.message} <span className="muted">{d.code}</span>
            </div>
          ))}
          {bottom.kind === "tester" && (
            <Tester key={`${bottom.rel}:${bottom.offset}`} rel={bottom.rel} offset={bottom.offset} facts={bottom.facts}
              onOpen={(line) => openFile(bottom.rel, line)} />
          )}
          {bottom.kind === "usages" && bottom.usages.map((u, i) => (
            <div key={i} className="row" onClick={() => openFile(u.file, u.line)}>{u.file}:{u.line}:{u.column}</div>
          ))}
          {bottom.kind === "mod" && bottom.files.flatMap((f) => f.diagnostics.filter((d) => d.severity !== "info").map((d, i) => (
            <div key={f.rel + i} className={`row ${d.severity}`} onClick={() => openFile(f.rel, d.line)}>
              <span className="sev">{d.severity}</span> {f.rel}:{d.line} {d.message} <span className="muted">{d.code}</span>
            </div>
          )))}
        </div>
      </section>
      {picker && (
        <div className="preview-backdrop" onClick={closePicker}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <ProjectPicker dirty={dirty.size > 0} onClose={closePicker} />
          </div>
        </div>
      )}
      {formatting && (
        <div className="preview-backdrop" onClick={closeFormat}>
          <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
            <FormatMod onStatus={setStatus} onClose={closeFormat} />
          </div>
        </div>
      )}
      {mgModal && (
        <div className="preview-backdrop" onClick={closeMgModal}>
          <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
            <GroupEditor group={mgModal.group} applyLabel="Apply in the editor (not saved yet)" onCancel={closeMgModal}
              onApply={async (rows) => {
                const { rel, group } = mgModal;
                await sync(rel);
                const { edits } = await api.modGroupEdits(rel, group.id, rows);
                const m = fileOf(rel)?.model;
                if (!m) return;
                const ops = edits.map((e) => {
                  const a = m.getPositionAt(e.start), b = m.getPositionAt(e.end);
                  return { range: new monaco.Range(a.lineNumber, a.column, b.lineNumber, b.column), text: e.text };
                });
                m.pushStackElement(); m.pushEditOperations([], ops, () => null); m.pushStackElement();
                closeMgModal();
                setStatus(`Modifier group ${group.key}: ${rows.length} steps - not saved yet (Ctrl+Z undoes)`);
              }} />
          </div>
        </div>
      )}
      {tplModal && (
        <div className="preview-backdrop" onClick={closeTplModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            {tplModal.kind === "insert" ? (
              <TemplateUse mode="cursor" onStatus={setStatus} onClose={closeTplModal} onInsert={insertAtCursor} />
            ) : (
              <TemplateSave text={tplModal.text} folder={tplModal.folder} onStatus={setStatus} onClose={closeTplModal} />
            )}
          </div>
        </div>
      )}
      <footer><span className="footer-status">{status}</span>{memory !== null && <span title="Memory used by the vic2toolmod server (it stops when this window is closed)">server {(memory / 1024).toFixed(1)} GB</span>}</footer>
    </div>
  );
}
