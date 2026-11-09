import { useEffect, useState } from "react";
import { api, spriteUrl, type BlockNode, type Diagnostic, type TextEdit } from "../api";
import { EventPreview } from "./EventPreview";

/**
 * Block view (K32 = B): the file as nested cards built from the schema.
 * Every change becomes a small text edit applied through the editor model,
 * so undo is shared with the code view (K31).
 */

interface Props {
  rel: string;
  version: number; // changes when the text changes -> reload
  diagnostics: Diagnostic[];
  apply: (edits: TextEdit[]) => void;
  sync: () => Promise<void>;
  select: (start: number, end: number) => void;
  /** Width in the split view (px); undefined = share the row with the code. */
  width?: number;
  /** Commands of the right-click menu (the same as in the code editor). */
  actions?: BlockActions;
}

export interface BlockActions {
  definition: (offset: number) => void;
  usages: (offset: number, word: string) => void;
  tester: (offset: number) => void;
}

interface Menu { x: number; y: number; node: BlockNode }

const ROLE_LABEL: Record<string, string> = {
  trigger: "trigger", effect: "effect", scope: "scope", field: "", dynamic: "name", unknown: "unknown",
};

/** Same rule as the engine (loc.missing): text with spaces etc. is shown literally by the game. */
const looksLikeKey = (raw: string) => {
  const v = raw.replace(/^"|"$/g, "");
  return /^[A-Za-z0-9_.\-]+$/.test(v) && (v === v.toUpperCase() || v.includes("_") || /\d/.test(v));
};

const nameCache = new Map<string, Promise<string[]>>();
const namesOf = (registry: string) => {
  if (!nameCache.has(registry)) nameCache.set(registry, api.names(registry).then((r) => r.names));
  return nameCache.get(registry)!;
};

export function Blocks({ rel, version, diagnostics, apply, sync, select, width, actions }: Props) {
  const [items, setItems] = useState<BlockNode[]>([]);
  const [error, setError] = useState("");
  const [menu, setMenu] = useState<Menu | null>(null);
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("click", close);
    window.addEventListener("keydown", key);
    return () => { window.removeEventListener("click", close); window.removeEventListener("keydown", key); };
  }, [menu]);

  useEffect(() => {
    let alive = true;
    const t = window.setTimeout(async () => {
      try {
        await sync();
        const r = await api.blocks(rel);
        if (alive) { setItems(r.items); setError(""); }
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    }, 450);
    return () => { alive = false; window.clearTimeout(t); };
  }, [rel, version]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (body: Record<string, unknown>) => {
    await sync();
    try {
      const r = await api.edit({ rel, ...body });
      apply(r.edits);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const ctx: Ctx = {
    run, select, diagnostics, rel,
    menu: actions ? (e, node) => { e.preventDefault(); e.stopPropagation(); setMenu({ x: e.clientX, y: e.clientY, node }); } : undefined,
  };
  const m = menu?.node;
  // A name to look up: the value when there is one (has_global_flag = x), else the key.
  const at = m ? (m.value_start ?? m.key_start ?? m.start) : 0;
  const word = m ? (m.value !== undefined && !m.block ? m.value : m.key ?? "") : "";
  return (
    <div className="blocks" style={width ? { flex: `0 0 ${width}px` } : undefined}>
      {menu && m && actions && (
        <div className="context-menu" style={{ left: menu.x, top: menu.y }} onClick={(e) => e.stopPropagation()}>
          <div className="row" onClick={() => { setMenu(null); actions.definition(at); }}>Go to definition <span className="muted">F12</span></div>
          <div className="row" onClick={() => { setMenu(null); actions.usages(at, word); }}>Find usages <span className="muted">Shift+F12</span></div>
          {m.block && m.context === "trigger" && m.lbrace !== undefined && (
            <div className="row" onClick={() => { setMenu(null); actions.tester(m.lbrace! + 1); }}>Test trigger <span className="muted">Ctrl+Alt+T</span></div>
          )}
          <div className="row" onClick={() => { setMenu(null); select(m.start, m.end); }}>Show in code</div>
        </div>
      )}
      {error && <div className="creator-error">{error}</div>}
      {items.map((n, i) => <Card key={`${n.start}-${i}`} node={n} ctx={ctx} depth={0} />)}
      <AddButton parent={-1} offset={1e9} ctx={ctx} />
    </div>
  );
}

interface Ctx {
  run: (body: Record<string, unknown>) => Promise<void>;
  select: (start: number, end: number) => void;
  diagnostics: Diagnostic[];
  rel: string;
  menu?: (e: React.MouseEvent, node: BlockNode) => void;
}

function problemsOf(node: BlockNode, ctx: Ctx) {
  const stop = node.block ? (node.lbrace ?? node.end) : node.end;
  return ctx.diagnostics.filter((d) => d.start >= node.start && d.start <= stop && d.severity !== "info");
}

function Card({ node, ctx, depth }: { node: BlockNode; ctx: Ctx; depth: number }) {
  const [open, setOpen] = useState(depth < 2);
  const [preview, setPreview] = useState(false);
  const isEvent = depth === 0 && /^(country|province)_event$/i.test(node.key ?? "");
  const problems = problemsOf(node, ctx);
  const cls = "card" + (problems.some((p) => p.severity === "error") ? " has-error" : problems.length ? " has-warning" : "");

  if (node.kind === "value" || node.kind === "error") {
    return <div className={"raw" + (node.kind === "error" ? " has-error" : "")} onClick={() => ctx.select(node.start, node.end)}>{node.value}</div>;
  }
  if (node.kind === "block") {
    return (
      <div className={cls}>
        <div className="card-head"><span className="muted">{"{ }"}</span></div>
        <div className="card-body">{node.children?.map((c, i) => <Card key={`${c.start}-${i}`} node={c} ctx={ctx} depth={depth + 1} />)}</div>
      </div>
    );
  }
  const title = problems.map((p) => p.message).join("\n") || node.doc || node.spec;
  return (
    <div className={cls}>
      <div className="card-head" title={title} onContextMenu={(e) => ctx.menu?.(e, node)}>
        {node.block && <span className="twisty" onClick={() => setOpen(!open)}>{open ? "▾" : "▸"}</span>}
        <span className={`card-key role-${node.role}`} onClick={() => ctx.select(node.start, node.end)}>{node.key}</span>
        {ROLE_LABEL[node.role ?? ""] && <span className="chip">{ROLE_LABEL[node.role ?? ""]}</span>}
        {node.block && node.scope && <span className="chip scope">{node.scope}</span>}
        {!node.block && node.value !== undefined && <ValueEditor node={node} ctx={ctx} />}
        {node.sprite && <img className="card-icon" src={spriteUrl(node.sprite[0], node.sprite[1])} alt="" title={`${node.sprite[0]}, icon ${node.sprite[1]}`} />}
        {problems.length > 0 && <span className="problem" title={title}>⚠ {problems[0].message}</span>}
        <span className="spacer" />
        {isEvent && <button className="mini" onClick={() => setPreview(true)}>preview</button>}
        <button className="mini" title="Delete" onClick={() => ctx.run({ op: "delete", start: node.start })}>×</button>
      </div>
      {preview && <EventPreview event={node} onClose={() => setPreview(false)} />}
      {node.block && open && (
        <div className="card-body">
          {node.children?.map((c, i) => <Card key={`${c.start}-${i}`} node={c} ctx={ctx} depth={depth + 1} />)}
          <AddButton parent={node.lbrace ?? -1} offset={node.rbrace ?? node.end} ctx={ctx} />
        </div>
      )}
    </div>
  );
}

function ValueEditor({ node, ctx }: { node: BlockNode; ctx: Ctx }) {
  const [value, setValue] = useState(node.value ?? "");
  const [names, setNames] = useState<string[]>([]);
  const [locText, setLocText] = useState(node.loc_text ?? "");
  const [savedText, setSavedText] = useState(node.loc_text ?? "");
  useEffect(() => {
    setValue(node.value ?? "");
    setLocText(node.loc_text ?? "");
    setSavedText(node.loc_text ?? "");
  }, [node.value, node.loc_text]);
  const commit = (v: string) => {
    if (v !== node.value && v.trim()) ctx.run({ op: "set", start: node.start, value: v });
  };
  const listId = `names-${node.registry}`;

  if (node.value_kind === "bool" || (node.value_kind === "enum" && node.choices?.length)) {
    return (
      <select className="value" value={value} onChange={(e) => { setValue(e.target.value); commit(e.target.value); }}>
        {!node.choices?.includes(value) && <option>{value}</option>}
        {node.choices?.map((c) => <option key={c}>{c}</option>)}
      </select>
    );
  }
  return (
    <>
      <input
        className={"value" + (node.value_kind === "number" ? " number" : "")}
        value={value}
        list={node.registry ? listId : undefined}
        onFocus={() => { if (node.registry && !names.length) namesOf(node.registry).then(setNames); }}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => commit(value)}
        onKeyDown={(e) => { if (e.key === "Enter") commit(value); }}
      />
      {node.registry && <datalist id={listId}>{names.slice(0, 2000).map((n) => <option key={n} value={n} />)}</datalist>}
      {node.value_kind === "loc" && looksLikeKey(node.value ?? "") && (
        <span className="loc">
          <input className="loc-text" value={locText} placeholder="(no text for this key)" onChange={(e) => setLocText(e.target.value)} />
          <button className="mini" disabled={locText === savedText}
            title="Save the English text into the localisation (K35)"
            onClick={async () => {
              const key = (node.value ?? "").replace(/^"|"$/g, "");
              if (!key) return;
              await api.localisation(key, locText, true);
              setSavedText(locText);
            }}>save text</button>
        </span>
      )}
    </>
  );
}

function AddButton({ parent, offset, ctx }: { parent: number; offset: number; ctx: Ctx }) {
  const [keys, setKeys] = useState<{ label: string; kind: string; detail: string }[] | null>(null);
  const [filter, setFilter] = useState("");
  if (keys === null) {
    return (
      <button className="mini add" onClick={async () => {
        const r = await api.complete(ctx.rel, offset);
        setKeys(r.items.filter((c) => c.kind !== "value"));
      }}>+ add</button>
    );
  }
  const shown = keys.filter((k) => k.label.toLowerCase().includes(filter.toLowerCase())).slice(0, 60);
  return (
    <div className="add-menu">
      <input autoFocus placeholder="key…" value={filter} onChange={(e) => setFilter(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Escape") setKeys(null); }} />
      <div className="add-list">
        {shown.map((k) => (
          <div key={k.label} className="row" title={k.detail} onClick={async () => {
            setKeys(null); setFilter("");
            await ctx.run({ op: "insert", parent, key: k.label, value: "auto" });
          }}>{k.label} <span className="muted">{k.kind}</span></div>
        ))}
        {!shown.length && <div className="row muted">nothing allowed here matches</div>}
      </div>
      <button className="mini" onClick={() => setKeys(null)}>cancel</button>
    </div>
  );
}
