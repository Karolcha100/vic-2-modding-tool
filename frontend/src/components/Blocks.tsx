import { useEffect, useState } from "react";
import { api, type BlockNode, type Diagnostic, type TextEdit } from "../api";

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
}

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

export function Blocks({ rel, version, diagnostics, apply, sync, select }: Props) {
  const [items, setItems] = useState<BlockNode[]>([]);
  const [error, setError] = useState("");

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

  const ctx: Ctx = { run, select, diagnostics, rel };
  return (
    <div className="blocks">
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
}

function problemsOf(node: BlockNode, ctx: Ctx) {
  const stop = node.block ? (node.lbrace ?? node.end) : node.end;
  return ctx.diagnostics.filter((d) => d.start >= node.start && d.start <= stop && d.severity !== "info");
}

function Card({ node, ctx, depth }: { node: BlockNode; ctx: Ctx; depth: number }) {
  const [open, setOpen] = useState(depth < 2);
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
      <div className="card-head" title={title}>
        {node.block && <span className="twisty" onClick={() => setOpen(!open)}>{open ? "▾" : "▸"}</span>}
        <span className={`card-key role-${node.role}`} onClick={() => ctx.select(node.start, node.end)}>{node.key}</span>
        {ROLE_LABEL[node.role ?? ""] && <span className="chip">{ROLE_LABEL[node.role ?? ""]}</span>}
        {node.block && node.scope && <span className="chip scope">{node.scope}</span>}
        {!node.block && node.value !== undefined && <ValueEditor node={node} ctx={ctx} />}
        {problems.length > 0 && <span className="problem" title={title}>⚠ {problems[0].message}</span>}
        <span className="spacer" />
        <button className="mini" title="Delete" onClick={() => ctx.run({ op: "delete", start: node.start })}>×</button>
      </div>
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
