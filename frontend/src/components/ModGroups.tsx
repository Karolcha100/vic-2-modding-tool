import { useEffect, useMemo, useState } from "react";
import { api, type ModGroup } from "../api";

/**
 * Modifier groups (T008): many `modifier = { factor = F  key = N }` of one block that differ
 * only in N are one step function of `key`. The editor shows it as a table and a chart and
 * builds new steps from a function (same factor each step, a straight line, or any formula).
 */

type Row = [string, string];

/** Does the condition of a step hold at x? */
function active(g: ModGroup, threshold: number, x: number): boolean {
  if (g.compare === "gte") return g.negated ? x < threshold : x >= threshold; // NOT = { key = N }: below N
  return g.negated ? x > threshold : x <= threshold;
}

/** The group's combined factor at x (product, or sum for additive blocks). */
export function total(g: ModGroup, rows: Row[], combine: string, x: number): number {
  let t = combine === "add" ? 0 : 1;
  for (const [v, f] of rows) {
    const value = Number(v), factor = Number(f);
    if (Number.isNaN(value) || Number.isNaN(factor) || !active(g, value, x)) continue;
    t = combine === "add" ? t + factor : t * factor;
  }
  return t;
}

/** Steps take effect one after another as x goes up (at least N) or down (below / at most N). */
function upward(g: ModGroup): boolean {
  return (g.compare === "gte") !== g.negated;
}

const IDENT = /[a-z_]+/gi;
const FUNCS: Record<string, string> = { x: "x", ln: "Math.log", log: "Math.log10", exp: "Math.exp", sqrt: "Math.sqrt", pow: "Math.pow", min: "Math.min", max: "Math.max", abs: "Math.abs" };

/** A formula of x (`1.1^((x-20)/10)`, `1 + 0.02*x`, `sqrt(x)/5`) as a function, or an error text. */
function formula(text: string): ((x: number) => number) | string {
  if (!/^[\d\s.+\-*/()^,a-z_]*$/i.test(text)) return "only numbers, x, + - * / ^ ( ) and ln log exp sqrt pow min max abs";
  const bad = (text.match(IDENT) ?? []).find((w) => !(w.toLowerCase() in FUNCS));
  if (bad) return `unknown name "${bad}"`;
  const js = text.replace(IDENT, (w) => FUNCS[w.toLowerCase()]).replace(/\^/g, "**");
  try {
    const fn = new Function("x", `"use strict"; return (${js});`) as (x: number) => number;
    fn(1);
    return fn;
  } catch (e) { return (e as Error).message; }
}

function fmt(n: number, decimals: number): string {
  if (!Number.isFinite(n)) return "0";
  const s = n.toFixed(decimals);
  return s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
}

function Chart({ g, oldRows, rows, combine }: { g: ModGroup; oldRows: Row[]; rows: Row[]; combine: string }) {
  const W = 560, H = 220, P = 36;
  const values = [...oldRows, ...rows].map(([v]) => Number(v)).filter((n) => !Number.isNaN(n));
  if (!values.length) return null;
  let lo = Math.min(...values), hi = Math.max(...values);
  const pad = (hi - lo) * 0.15 || Math.abs(hi) * 0.2 || 1;
  lo -= pad; hi += pad;
  const marks = [lo, ...Array.from(new Set(values)).sort((a, b) => a - b), hi];
  const series = (r: Row[]) => {
    const pts: [number, number][] = [];
    for (let i = 0; i < marks.length - 1; i++) {
      const y = total(g, r, combine, (marks[i] + marks[i + 1]) / 2);
      pts.push([marks[i], y], [marks[i + 1], y]);
    }
    return pts;
  };
  const a = series(oldRows), b = series(rows);
  const ys = [...a, ...b].map(([, y]) => y);
  let ylo = Math.min(...ys, combine === "add" ? 0 : 1), yhi = Math.max(...ys, combine === "add" ? 0 : 1);
  if (yhi - ylo < 1e-9) { ylo -= 0.5; yhi += 0.5; }
  const sx = (x: number) => P + ((x - lo) / (hi - lo)) * (W - 2 * P);
  const sy = (y: number) => H - P + -((y - ylo) / (yhi - ylo)) * (H - 2 * P);
  const path = (pts: [number, number][]) => pts.map(([x, y], i) => `${i ? "L" : "M"}${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join(" ");
  const neutral = combine === "add" ? 0 : 1;
  return (
    <svg className="mg-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="combined factor of the group">
      <line x1={P} x2={W - P} y1={sy(neutral)} y2={sy(neutral)} className="mg-axis" />
      <text x={P - 4} y={sy(neutral) + 4} textAnchor="end" className="mg-tick">{neutral}</text>
      <text x={P - 4} y={sy(yhi) + 4} textAnchor="end" className="mg-tick">{fmt(yhi, 2)}</text>
      <text x={P - 4} y={sy(ylo) + 4} textAnchor="end" className="mg-tick">{fmt(ylo, 2)}</text>
      {Array.from(new Set(values)).map((v) => <text key={v} x={sx(v)} y={H - P + 14} textAnchor="middle" className="mg-tick">{fmt(v, 3)}</text>)}
      <text x={W - P} y={H - 4} textAnchor="end" className="mg-tick">{g.negated ? `NOT ${g.key}` : g.key}</text>
      <path d={path(a)} className="mg-old" />
      <path d={path(b)} className="mg-new" />
    </svg>
  );
}

/** A small chart of the group's combined factor (for the card in the Blocks view). */
export function Sparkline({ g }: { g: ModGroup }) {
  const rows: Row[] = g.steps.map((s) => [s.value, s.factor]);
  const values = rows.map(([v]) => Number(v));
  const lo = Math.min(...values), hi = Math.max(...values), pad = (hi - lo) * 0.15 || 1;
  const marks = [lo - pad, ...Array.from(new Set(values)).sort((a, b) => a - b), hi + pad];
  const ys: [number, number][] = [];
  for (let i = 0; i < marks.length - 1; i++) {
    const y = total(g, rows, g.combine, (marks[i] + marks[i + 1]) / 2);
    ys.push([marks[i], y], [marks[i + 1], y]);
  }
  const yl = Math.min(...ys.map((p) => p[1])), yh = Math.max(...ys.map((p) => p[1])) || 1;
  const W = 90, H = 22;
  const sx = (x: number) => ((x - marks[0]) / (marks[marks.length - 1] - marks[0])) * W;
  const sy = (y: number) => H - 2 - ((y - yl) / (yh - yl || 1)) * (H - 4);
  return <svg className="mg-spark" width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
    <path d={ys.map(([x, y], i) => `${i ? "L" : "M"}${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join(" ")} />
  </svg>;
}

/** "num_of_cities 20 → 75 · all: ×1.464" */
export function groupSummary(g: ModGroup): string {
  const values = g.steps.map((s) => Number(s.value));
  const rows: Row[] = g.steps.map((s) => [s.value, s.factor]);
  const all = g.combine === "add" ? rows.reduce((a, [, f]) => a + Number(f), 0) : rows.reduce((a, [, f]) => a * Number(f), 1);
  const span = `${Math.min(...values)} → ${Math.max(...values)}`;
  return `${g.negated ? `NOT ${g.key}` : g.key} ${span} · all steps: ${g.combine === "add" ? (all >= 0 ? "+" : "") : "×"}${fmt(all, 3)}`;
}

interface EditorProps {
  group: ModGroup;
  /** Identical copies elsewhere (Analyses view); the editor offers to change them too. */
  copies?: ModGroup[];
  applyLabel: string;
  onApply: (rows: Row[], withCopies: boolean) => Promise<void> | void;
  onPreview?: (rows: Row[], withCopies: boolean) => Promise<void> | void;
  onCancel?: () => void;
}

export function GroupEditor({ group: g, copies = [], applyLabel, onApply, onPreview, onCancel }: EditorProps) {
  const oldRows: Row[] = useMemo(() => g.steps.map((s) => [s.value, s.factor]), [g]);
  const [rows, setRows] = useState<Row[]>(oldRows);
  const [combine, setCombine] = useState<string>(g.combine);
  const [mode, setMode] = useState<"each" | "line" | "formula">("each");
  const nums = oldRows.map(([v]) => Number(v));
  const [from, setFrom] = useState(String(Math.min(...nums)));
  const [to, setTo] = useState(String(Math.max(...nums)));
  const [count, setCount] = useState(String(oldRows.length));
  const [each, setEach] = useState(oldRows[0]?.[1] ?? "1");
  const [start, setStart] = useState(g.combine === "add" ? "0.1" : "1.1");
  const [end, setEnd] = useState(g.combine === "add" ? "1" : "2");
  const [expr, setExpr] = useState(g.combine === "add" ? "0.05 * x" : "1.1 ^ x");
  const [decimals, setDecimals] = useState("3");
  const [withCopies, setWithCopies] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setRows(oldRows); setCombine(g.combine); setError(""); }, [g, oldRows]);

  const generate = () => {
    setError("");
    const a = Number(from), b = Number(to), n = Math.round(Number(count)), d = Number(decimals);
    if ([a, b].some(Number.isNaN) || !(n >= 1) || n > 200) { setError("thresholds: from / to are numbers, steps 1..200"); return; }
    const xs = Array.from({ length: n }, (_, i) => (n === 1 ? a : a + ((b - a) * i) / (n - 1)));
    const order = [...xs].sort((p, q) => (upward(g) ? p - q : q - p)); // order in which the steps switch on
    let target: (x: number, i: number) => number;
    if (mode === "each") {
      const f = Number(each);
      if (Number.isNaN(f)) { setError("the factor is not a number"); return; }
      target = (_x, i) => (combine === "add" ? f * (i + 1) : f ** (i + 1));
    } else if (mode === "line") {
      const s = Number(start), e = Number(end);
      if (Number.isNaN(s) || Number.isNaN(e)) { setError("start / end are numbers"); return; }
      target = (_x, i) => (n === 1 ? e : s + ((e - s) * i) / (n - 1));
    } else {
      const fn = formula(expr);
      if (typeof fn === "string") { setError(`formula: ${fn}`); return; }
      target = (x) => fn(x);
    }
    let prev = combine === "add" ? 0 : 1;
    const out: Row[] = [];
    for (let i = 0; i < order.length; i++) {
      const t = target(order[i], i);
      if (!Number.isFinite(t) || (combine !== "add" && (t === 0 || prev === 0))) { setError(`the function gives ${t} at ${order[i]}: a multiplier cannot pass 0`); return; }
      out.push([fmt(order[i], d), fmt(combine === "add" ? t - prev : t / prev, d)]);
      prev = t;
    }
    setRows(out);
  };

  const run = async (fn: EditorProps["onApply"] | undefined) => {
    if (!fn) return;
    const bad = rows.find(([v, f]) => Number.isNaN(Number(v)) || Number.isNaN(Number(f)) || !v.trim() || !f.trim());
    if (bad) { setError(`not a number: ${bad.join(" / ")}`); return; }
    setBusy(true); setError("");
    try { await fn(rows, withCopies); } catch (e) { setError((e as Error).message); }
    setBusy(false);
  };

  const setRow = (i: number, j: 0 | 1, v: string) => setRows(rows.map((r, k) => (k === i ? (j ? [r[0], v] : [v, r[1]]) : r)));
  const files = new Set(copies.map((c) => c.rel));
  const when = g.compare === "gte" ? (g.negated ? "below N" : "N or more") : (g.negated ? "above N" : "N or less");
  const cond = `${g.negated ? `NOT = { ${g.key} = N }` : `${g.key} = N`} (true for ${when})`;

  return (
    <div className="mg-editor">
      <div className="mg-head">
        <b>{g.path.join(" › ")}</b> <span className="muted">{g.rel}:{g.line}</span>
        <div className="muted">{g.steps.length} modifiers on <code>{cond}</code>{g.context.length > 0 && <> with <code>{g.context.join(" ")}</code></>}
          {g.base_key && <> · block {g.base_key} = {g.base}</>}</div>
      </div>
      <div className="mg-body">
        <div className="mg-table">
          <table>
            <thead><tr><th>{g.key} (N)</th><th>factor</th><th>combined</th><th /></tr></thead>
            <tbody>
              {rows.map(([v, f], i) => (
                <tr key={i}>
                  <td><input value={v} onChange={(e) => setRow(i, 0, e.target.value)} /></td>
                  <td><input value={f} onChange={(e) => setRow(i, 1, e.target.value)} /></td>
                  <td className="muted">{fmt(total(g, rows, combine, Number(v) + (upward(g) ? 1e-9 : -1e-9)), 3)}</td>
                  <td><button title="remove" onClick={() => setRows(rows.filter((_, k) => k !== i))}>×</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="creator-buttons">
            <button onClick={() => setRows([...rows, rows.length ? [...rows[rows.length - 1]] as Row : ["1", "1"]])}>+ row</button>
            <button onClick={() => setRows([...rows].sort((a, b) => Number(a[0]) - Number(b[0])))}>Sort</button>
            <button onClick={() => setRows(oldRows)}>Reset</button>
          </div>
        </div>
        <div className="mg-side">
          <Chart g={g} oldRows={oldRows} rows={rows} combine={combine} />
          <div className="muted small"><span className="mg-key-old">━ now</span> <span className="mg-key-new">━ new</span> · combined factor of the group by {g.key}
            {" · factors "}<select value={combine} onChange={(e) => setCombine(e.target.value)} title={`How the game joins the factors of this block: ${g.combine_note}`}>
              <option value="multiply">multiply</option><option value="add">add up</option></select>
            {g.combine_note.startsWith("uncertain") && <span className="problem" title={g.combine_note}> ⚠ uncertain</span>}</div>
          <fieldset className="mg-gen">
            <legend>Make the steps from a function</legend>
            <label>Thresholds from <input value={from} onChange={(e) => setFrom(e.target.value)} /> to <input value={to} onChange={(e) => setTo(e.target.value)} />, steps <input value={count} onChange={(e) => setCount(e.target.value)} /></label>
            <label><input type="radio" checked={mode === "each"} onChange={() => setMode("each")} /> same factor at each step <input value={each} onChange={(e) => setEach(e.target.value)} /></label>
            <label><input type="radio" checked={mode === "line"} onChange={() => setMode("line")} /> combined factor in a straight line from <input value={start} onChange={(e) => setStart(e.target.value)} /> to <input value={end} onChange={(e) => setEnd(e.target.value)} /></label>
            <label><input type="radio" checked={mode === "formula"} onChange={() => setMode("formula")} /> combined factor = f(x) = <input className="mg-expr" value={expr} onChange={(e) => setExpr(e.target.value)} placeholder="1.1 ^ ((x - 20) / 10)" /></label>
            <label>decimals <input value={decimals} onChange={(e) => setDecimals(e.target.value)} /> <button onClick={generate}>Generate</button></label>
          </fieldset>
        </div>
      </div>
      {copies.length > 0 && (
        <label className="mg-copies"><input type="checkbox" checked={withCopies} onChange={(e) => setWithCopies(e.target.checked)} />
          also change the {copies.length} identical {copies.length === 1 ? "copy" : "copies"} ({files.size} {files.size === 1 ? "file" : "files"}: {[...files].slice(0, 4).join(", ")}{files.size > 4 ? " …" : ""})</label>
      )}
      <div className="creator-buttons">
        {onPreview && <button disabled={busy} onClick={() => run(onPreview)}>Preview changes</button>}
        <button disabled={busy} onClick={() => run(onApply)}>{applyLabel}</button>
        {onCancel && <button onClick={onCancel}>Cancel</button>}
      </div>
      {error && <div className="creator-error">{error}</div>}
    </div>
  );
}

/** Analyses → Modifier groups: every group of the mod, edited and written to the files. */
export function ModGroupsTab({ onOpen, onStatus }: { onOpen: (rel: string, line?: number) => void; onStatus: (t: string) => void }) {
  const [groups, setGroups] = useState<ModGroup[] | null>(null);
  const [filter, setFilter] = useState("");
  const [sel, setSel] = useState<ModGroup | null>(null);
  const [result, setResult] = useState<{ diff: string; files: string[]; backup?: string | null; written?: boolean } | null>(null);
  const [error, setError] = useState("");
  const load = () => api.modGroups().then((r) => setGroups(r.groups)).catch((e) => setError((e as Error).message));
  useEffect(() => { load(); }, []);

  const bySig = useMemo(() => {
    const m = new Map<string, ModGroup[]>();
    for (const g of groups ?? []) m.set(g.signature, [...(m.get(g.signature) ?? []), g]);
    return m;
  }, [groups]);
  const shown = useMemo(() => {
    const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
    return (groups ?? []).filter((g) => words.every((w) => `${g.rel} ${g.path.join(" ")} ${g.key}`.toLowerCase().includes(w)));
  }, [groups, filter]);

  if (error && !groups) return <div className="creator-error pad">{error}</div>;
  if (!groups) return <div className="muted pad">Looking for modifier groups in every mod file…</div>;
  const copies = sel ? (bySig.get(sel.signature) ?? []).filter((c) => c !== sel) : [];
  const plans = (rows: Row[], withCopies: boolean) =>
    [sel!, ...(withCopies ? copies : [])].map((g) => ({ rel: g.rel, id: g.id, steps: rows }));

  return (
    <div className="split-view mg-tab">
      <div className="mg-list">
        <input placeholder={`filter ${groups.length} groups: file, block, key…`} value={filter} onChange={(e) => setFilter(e.target.value)} />
        <div className="mg-items">
          {shown.slice(0, 500).map((g) => (
            <div key={`${g.rel}:${g.id}`} className={`row${sel === g ? " on" : ""}`} onClick={() => { setSel(g); setResult(null); }} title={g.path.join(" › ")}>
              <b>{g.key}</b> × {g.steps.length} <span className="muted">{g.path[g.path.length - 1]} · {g.rel}:{g.line}</span>
              {(bySig.get(g.signature)?.length ?? 1) > 1 && <span className="chip">{bySig.get(g.signature)!.length} copies</span>}
            </div>
          ))}
          {shown.length > 500 && <div className="muted">… {shown.length - 500} more: narrow the filter</div>}
        </div>
      </div>
      <div className="mg-detail">
        {!sel && <div className="muted pad">Modifiers of one block that differ only in one number (e.g. <code>num_of_cities = 20 / 30 / 50</code>) are shown here as one group. Choose a group to see its curve and set new steps from a function.</div>}
        {sel && (
          <>
            <div className="creator-buttons"><button onClick={() => onOpen(sel.rel, sel.steps[0].line)}>Open in the editor</button></div>
            <GroupEditor group={sel} copies={copies} applyLabel="Write files"
              onPreview={async (rows, wc) => setResult(await api.modGroupPlan(plans(rows, wc), false))}
              onApply={async (rows, wc) => {
                const p = plans(rows, wc);
                if (!window.confirm(`Write the new steps to ${new Set(p.map((x) => x.rel)).size} file(s)? A backup is made first.`)) return;
                const r = await api.modGroupPlan(p, true);
                setResult(r); onStatus(`Modifier groups written (${r.files.length} file(s)); backup: ${r.backup ?? "-"}`);
                setSel(null); load();
              }} />
          </>
        )}
        {result && (
          <div className="creator-result">
            {result.backup && <div className="muted">backup: {result.backup}</div>}
            {!result.diff && <div className="muted">No changes.</div>}
            <pre>{result.diff}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
