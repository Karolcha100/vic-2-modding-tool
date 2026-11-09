import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Box, type ReformLayout } from "../api";

/** Reform window editor (K60, K69 = A): boxes of `reforms_window`, drag, auto grid, save. */

const COLORS: Record<string, string> = {
  political_reforms: "#4f7cc9",
  social_reforms: "#3e9c5b",
};
// Approximate visible size of one issue widget in the game (name + option selector).
const ISSUE_W = 140;
const ISSUE_H = 60;
// Extra canvas to the right / bottom so boxes outside the window stay visible.
const MARGIN = 320;

interface Props {
  onOpen: (rel: string, line: number) => void;
  onStatus: (text: string) => void;
}

export function ReformWindow({ onOpen, onStatus }: Props) {
  const [layout, setLayout] = useState<ReformLayout | null>(null);
  const [pos, setPos] = useState<Record<string, [number, number]>>({});
  const [diff, setDiff] = useState<string | null>(null);
  const [cat, setCat] = useState("political_reforms");
  const [cols, setCols] = useState(3);
  const [origin, setOrigin] = useState<[number, number]>([380, 60]);
  const [cell, setCell] = useState<[number, number]>([150, 75]);
  const drag = useRef<{ name: string; dx: number; dy: number } | null>(null);
  const svg = useRef<SVGSVGElement>(null);

  const load = async () => {
    try {
      const l = await api.reformWindow();
      setLayout(l);
      setPos(Object.fromEntries(l.boxes.map((b) => [b.name, [b.x, b.y] as [number, number]])));
      setDiff(null);
    } catch (e) {
      onStatus(`Reform window: ${(e as Error).message}`);
    }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Grid defaults for the chosen category: start where its boxes are now and
  // use as many columns as fit in the window.
  useEffect(() => {
    if (!layout) return;
    const inside = layout.boxes.filter((b) => b.category === cat && !b.outside && !b.clipped);
    const ox = inside.length ? Math.min(...inside.map((b) => b.x)) : 20;
    const oy = inside.length ? Math.min(...inside.map((b) => b.y)) : 60;
    setOrigin([ox, oy]);
    setCols(Math.max(1, Math.floor((layout.width - ox) / cell[0])));
  }, [layout, cat]); // eslint-disable-line react-hooks/exhaustive-deps

  const boxes: Box[] = useMemo(() => {
    if (!layout) return [];
    const existing = layout.boxes.map((b) => ({ ...b, x: pos[b.name]?.[0] ?? b.x, y: pos[b.name]?.[1] ?? b.y }));
    const added = Object.entries(layout.missing).flatMap(([category, names]) =>
      names.filter((n) => pos[n]).map((n) => ({
        name: n, x: pos[n][0], y: pos[n][1], w: ISSUE_W, h: ISSUE_H, category, line: 0, outside: false, clipped: false,
      })),
    );
    return [...existing, ...added];
  }, [layout, pos]);

  if (!layout) return <div className="reform-window">Loading the reform window…</div>;

  const changed = Object.fromEntries(
    Object.entries(pos).filter(([n, [x, y]]) => {
      const b = layout.boxes.find((b) => b.name === n);
      return !b || b.x !== x || b.y !== y;
    }),
  );
  const toSvg = (e: React.PointerEvent) => {
    const ctm = svg.current!.getScreenCTM();
    if (!ctm) return [0, 0];
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse());
    return [p.x, p.y];
  };
  const autoGrid = () => {
    const issues = layout.categories[cat] ?? [];
    const next = { ...pos };
    issues.forEach((name, n) => {
      next[name] = [origin[0] + (n % cols) * cell[0], origin[1] + Math.floor(n / cols) * cell[1]];
    });
    setPos(next);
  };
  const preview = async () => setDiff((await api.reformWindowPlan(changed, false)).diff || "(no changes)");
  const save = async () => {
    const r = await api.reformWindowPlan(changed, true);
    onStatus(`Reform window saved${r.backup ? ` (backup: ${r.backup})` : ""}`);
    load();
  };
  const num = (v: string) => Number(v) || 0;

  return (
    <div className="reform-window">
      <div className="rw-tools">
        <b>Reform window</b> <span className="muted">{layout.file} · {layout.width}×{layout.height}</span>
        <span className="spacer" />
        <label>Category <select value={cat} onChange={(e) => setCat(e.target.value)}>
          {Object.keys(COLORS).map((c) => <option key={c}>{c}</option>)}
        </select></label>
        <label>Columns <input type="number" min={1} max={6} value={cols} onChange={(e) => setCols(num(e.target.value) || 1)} /></label>
        <label>Start x <input type="number" value={origin[0]} onChange={(e) => setOrigin([num(e.target.value), origin[1]])} /></label>
        <label>y <input type="number" value={origin[1]} onChange={(e) => setOrigin([origin[0], num(e.target.value)])} /></label>
        <label>Cell w <input type="number" value={cell[0]} onChange={(e) => setCell([num(e.target.value), cell[1]])} /></label>
        <label>h <input type="number" value={cell[1]} onChange={(e) => setCell([cell[0], num(e.target.value)])} /></label>
        <button onClick={autoGrid}>Auto grid</button>
        <button onClick={preview} disabled={!Object.keys(changed).length}>Preview changes</button>
        <button onClick={save} disabled={!Object.keys(changed).length}>Save</button>
        <button onClick={load}>Reset</button>
      </div>
      <div className="rw-body">
        <svg
          ref={svg}
          className="rw-canvas"
          preserveAspectRatio="xMinYMin meet"
          viewBox={`-20 -20 ${layout.width + MARGIN} ${layout.height + 80}`}
          onPointerMove={(e) => {
            if (!drag.current) return;
            const [x, y] = toSvg(e);
            const d = drag.current;
            setPos((p) => ({ ...p, [d.name]: [Math.round(x - d.dx), Math.round(y - d.dy)] }));
          }}
          onPointerUp={() => (drag.current = null)}
          onPointerLeave={() => (drag.current = null)}
        >
          <rect x={0} y={0} width={layout.width} height={layout.height} className="rw-window" />
          {boxes.map((b) => {
            const color = COLORS[b.category ?? ""] ?? "#888";
            const out = b.x < 0 || b.y < 0 || b.x + ISSUE_W > layout.width || b.y + ISSUE_H > layout.height;
            return (
              <g
                key={b.name}
                transform={`translate(${b.x},${b.y})`}
                onPointerDown={(e) => {
                  const [x, y] = toSvg(e);
                  drag.current = { name: b.name, dx: x - b.x, dy: y - b.y };
                  (e.target as Element).setPointerCapture?.(e.pointerId);
                }}
                onDoubleClick={() => b.line && onOpen(layout.file, b.line)}
                style={{ cursor: "move" }}
              >
                <rect width={ISSUE_W} height={ISSUE_H} rx={4} fill={color} fillOpacity={changed[b.name] ? 0.55 : 0.3}
                      stroke={out ? "#e53935" : color} strokeWidth={out ? 4 : 1.5} />
                <text x={6} y={18} className="rw-label">{b.name}</text>
                <text x={6} y={36} className="rw-sub">{b.x}, {b.y}{b.line ? "" : " (new)"}</text>
              </g>
            );
          })}
        </svg>
        <div className="rw-side">
          <div className="panel-title">Not in the window</div>
          {Object.entries(layout.missing).flatMap(([c, names]) => names.map((n) => (
            <div key={n} className="row">
              {n} <span className="muted">{c}</span>{" "}
              {!pos[n] && <button onClick={() => setPos({ ...pos, [n]: [20, 20] })}>Add</button>}
            </div>
          )))}
          {!Object.keys(layout.missing).length && <div className="row muted">Every reform has a box.</div>}
          <div className="panel-title">Outside / sticking out</div>
          {boxes.filter((b) => b.x < 0 || b.y < 0 || b.x + ISSUE_W > layout.width || b.y + ISSUE_H > layout.height).map((b) => (
            <div key={b.name} className="row">{b.name} <span className="muted">{b.x}, {b.y}</span></div>
          ))}
          {layout.unknown.length > 0 && <div className="panel-title">Boxes that are no reform</div>}
          {layout.unknown.map((n) => <div key={n} className="row muted">{n}</div>)}
          <div className="muted rw-help">Drag boxes; double-click opens the box in the code. Red border: (partly) outside the window. Box size shown is an estimate of the visible widget ({ISSUE_W}×{ISSUE_H}).</div>
        </div>
      </div>
      {diff !== null && (
        <div className="rw-diff">
          <div className="panel-title">Changes <span onClick={() => setDiff(null)}>close</span></div>
          <pre>{diff}</pre>
        </div>
      )}
    </div>
  );
}
