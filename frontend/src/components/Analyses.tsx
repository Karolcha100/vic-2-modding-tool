import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Graph, type GEdge, type GNode } from "./Graph";

/** Analyses of the mod: pop promotion graph (K59), event chains (K6 C), vs vanilla (K6 H),
 *  statistics (K6 I), localisation editor (K6 E), git changes (K37 = B). */

type Tab = "promotion" | "events" | "vanilla" | "stats" | "localisation" | "git";

interface Props {
  onOpen: (rel: string, line?: number) => void;
  onStatus: (text: string) => void;
}

export function Analyses({ onOpen, onStatus }: Props) {
  const [tab, setTab] = useState<Tab>("promotion");
  const tabs: [Tab, string][] = [
    ["promotion", "Pop promotion"], ["events", "Event chains"], ["vanilla", "Vs vanilla"],
    ["stats", "Statistics"], ["localisation", "Localisation"], ["git", "Git changes"],
  ];
  return (
    <div className="analyses">
      <div className="rw-tools">
        <b>Analyses</b>
        {tabs.map(([t, label]) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{label}</button>)}
      </div>
      <div className="analyses-body">
        {tab === "promotion" && <Promotion onOpen={onOpen} />}
        {tab === "events" && <Events onOpen={onOpen} />}
        {tab === "vanilla" && <Vanilla />}
        {tab === "stats" && <Stats />}
        {tab === "localisation" && <Localisation onStatus={onStatus} onOpen={onOpen} />}
        {tab === "git" && <Git />}
      </div>
    </div>
  );
}

// -- pop promotion (K59) -------------------------------------------------------------------
interface PromoEdge { source: string; target: string; base: number | null; file: string; line: number;
  modifiers: { factor: number | null; conditions: string; refs: [string, string][]; line: number }[] }

function Promotion({ onOpen }: { onOpen: Props["onOpen"] }) {
  const [data, setData] = useState<{ nodes: { id: string }[]; edges: PromoEdge[] } | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [edgeKey, setEdgeKey] = useState<string | null>(null);
  useEffect(() => { api.poptypesGraph().then(setData).catch(() => undefined); }, []);
  const nodes: GNode[] = useMemo(() => (data?.nodes ?? []).map((n) => ({ id: n.id, label: n.id })), [data]);
  const edges: GEdge[] = useMemo(() => (data?.edges ?? []).map((e, i) => ({
    key: String(i), source: e.source, target: e.target,
    width: 1 + Math.min(4, (e.modifiers.length || 1) / 4),
    label: `${e.source} → ${e.target}: base ${e.base ?? "?"}, ${e.modifiers.length} modifiers`,
  })), [data]);
  if (!data) return <div className="muted pad">Loading the pop types…</div>;
  const edge = edgeKey !== null ? data.edges[Number(edgeKey)] : null;
  const list = edge ? [edge] : data.edges.filter((e) => sel && (e.source === sel || e.target === sel));
  return (
    <div className="split-view">
      <Graph shape="circle" nodes={nodes} edges={edges} selected={sel} onNode={(id) => { setSel(id); setEdgeKey(null); }} onEdge={setEdgeKey} />
      <div className="side-list">
        <div className="panel-title">{edge ? `${edge.source} → ${edge.target}` : sel ? `Promotions of ${sel}` : "Click a pop type or an arrow"}</div>
        {list.map((e) => (
          <div key={`${e.source}-${e.target}-${e.line}`} className="weight">
            <div className="row" onClick={() => onOpen(e.file, e.line)}><b>{e.source} → {e.target}</b> base {e.base ?? "?"} <span className="muted">{e.file}:{e.line}</span></div>
            {e.modifiers.map((m, i) => (
              <div key={i} className="row small" onClick={() => onOpen(e.file, m.line)} title={m.refs.map((r) => r.join(":")).join(", ")}>
                ×{m.factor ?? "?"} <span className="muted">{m.conditions}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

// -- event chains (K6 C) -------------------------------------------------------------------
interface ENode { id: string; type: string; event_id?: string; title?: string; file?: string; line?: number; missing?: boolean; orphan?: boolean }
interface EEdge { source: string; target: string; via: string; file: string; line: number }

function Events({ onOpen }: { onOpen: Props["onOpen"] }) {
  const [data, setData] = useState<{ nodes: ENode[]; edges: EEdge[] } | null>(null);
  const [query, setQuery] = useState("");
  const [focus, setFocus] = useState<string | null>(null);
  useEffect(() => { api.eventsGraph().then(setData).catch(() => undefined); }, []);
  const byId = useMemo(() => new Map((data?.nodes ?? []).map((n) => [n.id, n])), [data]);
  const sub = useMemo(() => {
    if (!data || !focus) return { nodes: [] as GNode[], edges: [] as GEdge[] };
    const keep = new Set([focus]);
    for (let depth = 0; depth < 2; depth++) {
      for (const e of data.edges) {
        if (keep.has(e.source) || keep.has(e.target)) { keep.add(e.source); keep.add(e.target); }
      }
      if (keep.size > 60) break;
    }
    const color = (n: ENode) => n.missing ? "#e53935" : n.type !== "event" ? "#b0662f" : n.orphan ? "#888" : "#4f7cc9";
    return {
      nodes: [...keep].map((id) => byId.get(id)).filter(Boolean).map((n) => ({
        id: n!.id, label: n!.type === "event" ? n!.event_id ?? n!.id : n!.id.split(":")[1] ?? n!.id,
        color: color(n!), title: `${n!.id}${n!.title ? ` - ${n!.title}` : ""}${n!.missing ? " (MISSING)" : ""}`,
      })),
      edges: data.edges.filter((e) => keep.has(e.source) && keep.has(e.target)).map((e, i) => ({
        key: String(i), source: e.source, target: e.target, label: e.via,
      })),
    };
  }, [data, focus, byId]);
  if (!data) return <div className="muted pad">Loading the event chains…</div>;
  const missing = data.nodes.filter((n) => n.missing);
  const orphans = data.nodes.filter((n) => n.orphan);
  const matches = query.length > 1 ? data.nodes.filter((n) => n.id.includes(query) || (n.title ?? "").toLowerCase().includes(query.toLowerCase())).slice(0, 40) : [];
  const f = focus ? byId.get(focus) : null;
  return (
    <div className="split-view">
      {focus ? <Graph nodes={sub.nodes} edges={sub.edges} selected={focus} onNode={setFocus} />
        : <div className="muted pad">Search an event (id or title) on the right; the graph shows who fires it and what it fires (two steps).</div>}
      <div className="side-list">
        <input placeholder="event id, title, decision…" value={query} onChange={(e) => setQuery(e.target.value)} />
        {matches.map((n) => <div key={n.id} className="row" onClick={() => setFocus(n.id)}>{n.id} <span className="muted">{n.title}</span></div>)}
        {f && <div className="panel-title">{f.id}</div>}
        {f?.file && <div className="row" onClick={() => onOpen(f.file!, f.line)}>open {f.file}:{f.line}</div>}
        <div className="panel-title">Fired but missing ({missing.length})</div>
        {missing.map((n) => <div key={n.id} className="row" onClick={() => setFocus(n.id)}>{n.event_id}</div>)}
        <div className="panel-title">Triggered-only, never fired ({orphans.length})</div>
        {orphans.map((n) => <div key={n.id} className="row" onClick={() => setFocus(n.id)}>{n.event_id} <span className="muted">{n.file}</span></div>)}
      </div>
    </div>
  );
}

// -- vs vanilla (K6 H) ---------------------------------------------------------------------
function Vanilla() {
  const [files, setFiles] = useState<{ rel: string; status: string; added: number; removed: number }[] | null>(null);
  const [status, setStatus] = useState("changed");
  const [diff, setDiff] = useState<string | null>(null);
  useEffect(() => { api.vanillaFiles().then((r) => setFiles(r.files)).catch(() => undefined); }, []);
  if (!files) return <div className="muted pad">Comparing with vanilla…</div>;
  const counts = files.reduce<Record<string, number>>((c, f) => ({ ...c, [f.status]: (c[f.status] ?? 0) + 1 }), {});
  const shown = files.filter((f) => f.status === status).sort((a, b) => b.added + b.removed - a.added - a.removed);
  return (
    <div className="split-view">
      <div className="side-list wide">
        {Object.entries(counts).map(([s, n]) => <button key={s} className={s === status ? "on" : ""} onClick={() => setStatus(s)}>{s} ({n})</button>)}
        {shown.slice(0, 500).map((f) => (
          <div key={f.rel} className="row" onClick={async () => setDiff((await api.vanillaDiff(f.rel)).diff)}>
            {f.rel} {f.status === "changed" && <span className="muted">+{f.added} −{f.removed}</span>}
          </div>
        ))}
      </div>
      <pre className="diff-pane">{diff ?? "Click a file to see what the mod changes."}</pre>
    </div>
  );
}

// -- statistics (K6 I) ---------------------------------------------------------------------
function Stats() {
  const [s, setS] = useState<{ date: string; total: number; by_owner: Record<string, number>; by_culture: Record<string, number>; by_religion: Record<string, number>; by_type: Record<string, number> } | null>(null);
  useEffect(() => { api.stats().then(setS).catch(() => undefined); }, []);
  if (!s) return <div className="muted pad">Counting pops…</div>;
  const table = (title: string, t: Record<string, number>) => (
    <div className="stat-table">
      <div className="panel-title">{title}</div>
      {Object.entries(t).sort((a, b) => b[1] - a[1]).slice(0, 25).map(([k, v]) => (
        <div key={k} className="row"><span className="bar" style={{ width: `${(100 * v) / s.total}%` }} />{k} <span className="muted">{Math.round(v).toLocaleString()} ({((100 * v) / s.total).toFixed(1)}%)</span></div>
      ))}
    </div>
  );
  return (
    <div className="stats">
      <div className="pad">Pops in <code>history/pops/{s.date}</code>: total size {Math.round(s.total).toLocaleString()}</div>
      <div className="stat-grid">
        {table("By owner", s.by_owner)}{table("By culture", s.by_culture)}{table("By religion", s.by_religion)}{table("By pop type", s.by_type)}
      </div>
    </div>
  );
}

// -- localisation (K6 E) -------------------------------------------------------------------
function Localisation({ onStatus, onOpen }: Props) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<{ key: string; english: string; file: string; line: number }[]>([]);
  const [total, setTotal] = useState(0);
  const [edits, setEdits] = useState<Record<string, string>>({});
  useEffect(() => {
    if (q.length < 2) { setRows([]); setTotal(0); return; }
    const t = window.setTimeout(async () => {
      const r = await api.localisationSearch(q);
      setRows(r.entries); setTotal(r.total);
    }, 300);
    return () => window.clearTimeout(t);
  }, [q]);
  return (
    <div className="loc-editor">
      <div className="pad"><input placeholder="search key or English text (at least 2 letters)" value={q} onChange={(e) => setQ(e.target.value)} /> <span className="muted">{total > rows.length ? `${rows.length} of ${total}` : total}</span></div>
      {rows.map((r) => (
        <div key={r.key} className="loc-row">
          <span className="loc-key" title={`${r.file}:${r.line}`} onClick={() => onOpen(r.file, r.line)}>{r.key}</span>
          <input value={edits[r.key] ?? r.english} onChange={(e) => setEdits({ ...edits, [r.key]: e.target.value })} />
          <button className="mini" disabled={edits[r.key] === undefined || edits[r.key] === r.english} onClick={async () => {
            await api.localisation(r.key, edits[r.key], true);
            onStatus(`Saved ${r.key}`);
            setRows(rows.map((x) => (x.key === r.key ? { ...x, english: edits[r.key] } : x)));
          }}>save</button>
        </div>
      ))}
    </div>
  );
}

// -- git (K37 = B) -------------------------------------------------------------------------
function Git() {
  const [s, setS] = useState<{ repo: boolean; branch?: string; changed?: [string, string][]; error?: string } | null>(null);
  const [diff, setDiff] = useState<string | null>(null);
  useEffect(() => { api.git().then(setS).catch(() => undefined); }, []);
  if (!s) return <div className="muted pad">Reading git…</div>;
  if (!s.repo) return <div className="muted pad">The mod folder is not a git repository. {s.error}</div>;
  return (
    <div className="split-view">
      <div className="side-list wide">
        <div className="panel-title">Branch {s.branch} · {s.changed?.length ?? 0} changed files</div>
        {s.changed?.map(([st, rel]) => (
          <div key={rel} className="row" onClick={async () => setDiff((await api.gitDiff(rel)).diff)}><b>{st}</b> {rel}</div>
        ))}
      </div>
      <pre className="diff-pane">{diff ?? "Click a file to see its changes since the last commit."}</pre>
    </div>
  );
}
