import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Box, type GuiElement, type ReformLayout } from "../api";
import { contentExtent, GuiNode, type DrawContext } from "./GuiDraw";
import { useStored } from "./Layout";

/**
 * Reform window editor (K60, K69 = A, K80 = A): the window of the politics
 * screen with every element - issue boxes with their icon, name and the rows
 * of their options (from `reform_option_window`), labels, the panel behind -
 * as outlines or with the real pictures. Issue boxes can be dragged.
 */

const COLORS: Record<string, string> = {
  political_reforms: "#4f7cc9",
  social_reforms: "#3e9c5b",
};
// Fallback size of an issue box when the window has no element to measure.
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
  const [real, setReal] = useStored("vic2.rw.real", false);
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

  const ctx: DrawContext | null = useMemo(
    () => (layout ? { real, sprites: layout.sprites, texts: layout.texts } : null),
    [layout, real],
  );
  // The element of each issue box; new boxes look like the first box of their category.
  const elementOf = useMemo(() => {
    const map = new Map<string, GuiElement>();
    if (!layout) return map;
    for (const c of layout.tree.children) if (c.kind === "windowtype") map.set(c.name, c);
    for (const names of Object.values(layout.categories)) {
      const model = names.map((n) => map.get(n)).find(Boolean);
      if (model) for (const n of names) if (!map.has(n)) map.set(n, { ...model, name: n, line: 0 });
    }
    return map;
  }, [layout]);
  // Visible size of an issue box: its elements and the rows of its options.
  const sizeOfBox = (name: string): [number, number] => {
    const el = elementOf.get(name);
    if (!el || !ctx) return [ISSUE_W, ISSUE_H];
    let [w, h] = contentExtent(el, ctx);
    const row = layout?.option_row;
    const n = layout?.issues[name]?.options.length ?? 0;
    if (row && n) {
      const [rw, rh] = contentExtent(row, ctx);
      w = Math.max(w, rw);
      h = Math.max(h, rh + (n - 1) * (row.h || 14));
    }
    return [w || ISSUE_W, h || ISSUE_H];
  };

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

  if (!layout || !ctx) return <div className="reform-window">Loading the reform window…</div>;
  const isIssueBox = (c: GuiElement) => c.kind === "windowtype" && boxes.some((b) => b.name === c.name);
  const outsideOf = (b: Box) => {
    const [w, h] = sizeOfBox(b.name);
    return b.x < 0 || b.y < 0 || b.x + w > layout.width || b.y + h > layout.height;
  };

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
        <label title="Draw the game's pictures instead of outlines"><input type="checkbox" checked={real} onChange={(e) => setReal(e.target.checked)} /> Real graphics</label>
      </div>
      <div className="rw-body">
        <svg
          ref={svg}
          className="rw-canvas"
          preserveAspectRatio="xMinYMin meet"
          viewBox={`-80 -80 ${layout.width + MARGIN + 60} ${layout.height + 140}`}
          onPointerMove={(e) => {
            if (!drag.current) return;
            const [x, y] = toSvg(e);
            const d = drag.current;
            setPos((p) => ({ ...p, [d.name]: [Math.round(x - d.dx), Math.round(y - d.dy)] }));
          }}
          onPointerUp={() => (drag.current = null)}
          onPointerLeave={() => (drag.current = null)}
        >
          {real && layout.backdrop.map((e, i) => <GuiNode key={`bg-${i}`} e={e} x={e.x} y={e.y} ctx={ctx} />)}
          <rect x={0} y={0} width={layout.width} height={layout.height} className={"rw-window" + (real ? " real" : "")} />
          {/* labels and other elements of the window (not the issue boxes) */}
          <GuiNode e={{ ...layout.tree, x: 0, y: 0, sprite: "" }} x={0} y={0} ctx={ctx} skip={isIssueBox} />
          {boxes.map((b) => {
            const color = COLORS[b.category ?? ""] ?? "#888";
            const out = outsideOf(b);
            const [w, h] = sizeOfBox(b.name);
            const el = elementOf.get(b.name);
            const issue = layout.issues[b.name];
            const row = layout.option_row;
            return (
              <g key={b.name}>
                {el && <GuiNode e={{ ...el, x: 0, y: 0 }} x={b.x} y={b.y} ctx={{ ...ctx, replace: { REFORM_NAME: issue?.text ?? b.name } }} />}
                {row && issue?.options.map((o, i) => (
                  <GuiNode key={o.key} e={{ ...row, x: 0, y: 0 }} x={b.x} y={b.y + i * (row.h || 14)}
                    ctx={{ ...ctx, replace: { REFORM_OPTION_NAME: o.text } }} skip={(c) => c.name === "selected" && i > 0} />
                ))}
                <rect
                  x={b.x} y={b.y} width={w} height={h} rx={3}
                  className={"rw-hit" + (changed[b.name] ? " changed" : "")}
                  fill={color} fillOpacity={real ? 0 : changed[b.name] ? 0.25 : 0.1}
                  stroke={out ? "#e53935" : color} strokeWidth={out ? 4 : 1.5}
                  onPointerDown={(e) => {
                    const [x, y] = toSvg(e);
                    drag.current = { name: b.name, dx: x - b.x, dy: y - b.y };
                    (e.target as Element).setPointerCapture?.(e.pointerId);
                  }}
                  onDoubleClick={() => b.line && onOpen(layout.file, b.line)}
                  style={{ cursor: "move" }}
                >
                  <title>{`${b.name} (${issue?.text ?? "?"}) · ${b.x}, ${b.y}${b.line ? "" : " (new)"} · ${issue?.options.length ?? 0} options`}</title>
                </rect>
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
          {boxes.filter(outsideOf).map((b) => (
            <div key={b.name} className="row">{b.name} <span className="muted">{b.x}, {b.y}</span></div>
          ))}
          {layout.unknown.length > 0 && <div className="panel-title">Boxes that are no reform</div>}
          {layout.unknown.map((n) => <div key={n} className="row muted">{n}</div>)}
          <div className="muted rw-help">Drag boxes; double-click opens the box in the code. Red border: (partly) outside the window. A box is as big as its elements and the rows of its options ({layout.option_row ? `rows from ${"reform_option_window"}` : "no option row template found"}). "Real graphics" draws the game's pictures (the panel behind the window too).</div>
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
