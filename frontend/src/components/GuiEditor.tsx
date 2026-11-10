import { useEffect, useMemo, useRef, useState } from "react";
import { api, type GuiElement, type GuiWindow } from "../api";
import { GuiNode, placeOf, sizeOf, type DrawContext } from "./GuiDraw";
import { useStored } from "./Layout";
import { useNavStored, useUndoable, useUndoTarget } from "../nav";

/**
 * Editor of any window of interface/*.gui (K80 B): the window drawn as outlines
 * or with the real pictures, every element selectable (on the canvas or in the
 * tree), moved by dragging, resized by its corner handle or with the numbers;
 * preview of the changes and save (with a backup), like the reform window.
 */

type Change = { x?: number; y?: number; w?: number; h?: number };

interface Placed { el: GuiElement; x: number; y: number; w: number; h: number; depth: number }

interface Props {
  files: string[];
  onOpen: (rel: string, line: number) => void;
  onStatus: (text: string) => void;
}

/** The element with the pending changes applied (recursively). */
function applied(e: GuiElement, changes: Record<number, Change>): GuiElement {
  const c = changes[e.line];
  return {
    ...e,
    x: c?.x ?? e.x, y: c?.y ?? e.y, w: c?.w ?? e.w, h: c?.h ?? e.h,
    children: e.children.map((k) => applied(k, changes)),
  };
}

/** Every element with its place on the canvas (the window's corner at 0, 0). */
function flatten(root: GuiElement, ctx: DrawContext): Placed[] {
  const out: Placed[] = [];
  const walk = (e: GuiElement, x: number, y: number, depth: number) => {
    const [w, h] = sizeOf(e, ctx);
    out.push({ el: e, x, y, w, h, depth });
    for (const c of e.children) {
      const [cx, cy] = placeOf(c, w, h);
      walk(c, x + cx, y + cy, depth + 1);
    }
  };
  walk({ ...root, x: 0, y: 0 }, 0, 0, 0);
  return out;
}

export function GuiEditor({ files, onOpen, onStatus }: Props) {
  const guiFiles = useMemo(() => files.filter((f) => /^interface\/.*\.gui$/i.test(f)).sort(), [files]);
  const [rel, setRel] = useNavStored("vic2.gui.file", "interface/country_politics.gui");
  const [name, setName] = useNavStored("vic2.gui.window", "country_politics");
  const [real, setReal] = useStored("vic2.gui.real", false);
  const [windows, setWindows] = useState<{ name: string; line: number; depth: number }[]>([]);
  const [data, setData] = useState<GuiWindow | null>(null);
  // Moves and sizes not written yet; Ctrl+Z / Ctrl+Shift+Z step through them (T012).
  const history = useUndoable<Record<number, Change>>({});
  const changes = history.value;
  useUndoTarget(history);
  const [sel, setSel] = useState<number | null>(null);
  const [diff, setDiff] = useState<string | null>(null);
  const [error, setError] = useState("");
  const drag = useRef<null | { mode: "move" | "size"; line: number; px: number; py: number; a: number; b: number; moved?: boolean }>(null);
  const svg = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!rel) return;
    api.guiWindows(rel).then((r) => { setWindows(r.windows); setError(""); }).catch((e) => setError((e as Error).message));
  }, [rel]);
  const load = async () => {
    if (!rel || !name) return;
    try {
      setData(await api.guiWindow(rel, name));
      history.reset({}); setSel(null); setDiff(null); setError("");
    } catch (e) {
      setData(null);
      setError((e as Error).message);
    }
  };
  useEffect(() => { load(); }, [rel, name]); // eslint-disable-line react-hooks/exhaustive-deps

  const ctx: DrawContext | null = useMemo(() => (data ? { real, sprites: data.sprites, texts: data.texts } : null), [data, real]);
  const root = useMemo(() => (data ? applied(data.tree, changes) : null), [data, changes]);
  const placed = useMemo(() => (root && ctx ? flatten(root, ctx) : []), [root, ctx]);
  const selected = placed.find((p) => p.el.line === sel) ?? null;
  const original = useMemo(() => {
    const m = new Map<number, GuiElement>();
    const walk = (e: GuiElement) => { m.set(e.line, e); e.children.forEach(walk); };
    if (data) walk(data.tree);
    return m;
  }, [data]);

  const toSvg = (e: React.PointerEvent): [number, number] => {
    const ctm = svg.current!.getScreenCTM();
    if (!ctm) return [0, 0];
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse());
    return [p.x, p.y];
  };
  const set = (line: number, c: Change) => history.set((all) => ({ ...all, [line]: { ...all[line], ...c } }));
  /** While dragging: one undo step for the whole drag (made when it starts). */
  const setDragging = (line: number, c: Change) => history.setQuiet((all) => ({ ...all, [line]: { ...all[line], ...c } }));

  if (!guiFiles.length) return <div className="muted pad">No interface/*.gui files in this project.</div>;
  const pending = Object.keys(changes).length;
  const bounds = placed.concat(
    (real && data ? data.backdrop : []).map((e) => ({ el: e, x: e.x, y: e.y, w: sizeOf(e, ctx!)[0], h: sizeOf(e, ctx!)[1], depth: 0 })),
  );
  const minX = Math.min(0, ...bounds.map((p) => p.x)) - 20;
  const minY = Math.min(0, ...bounds.map((p) => p.y)) - 20;
  const maxX = Math.max(root ? sizeOf(root, ctx!)[0] : 100, ...bounds.map((p) => p.x + p.w)) + 20;
  const maxY = Math.max(root ? sizeOf(root, ctx!)[1] : 100, ...bounds.map((p) => p.y + p.h)) + 20;

  const plan = async (write: boolean) => {
    if (!data) return;
    try {
      const r = await api.guiPlan(data.file, changes, write);
      if (write) { onStatus(`Saved ${data.file}${r.backup ? ` (backup: ${r.backup})` : ""}`); load(); }
      else setDiff(r.diff || "(no changes)");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="reform-window">
      <div className="rw-tools">
        <b>Interface</b>
        <select value={rel} onChange={(e) => { setRel(e.target.value); setName(""); }}>
          {!guiFiles.includes(rel) && <option value="">(choose a file)</option>}
          {guiFiles.map((f) => <option key={f} value={f}>{f.slice("interface/".length)}</option>)}
        </select>
        <select value={name} onChange={(e) => setName(e.target.value)}>
          <option value="">(choose a window)</option>
          {windows.map((w) => <option key={w.line} value={w.name}>{"  ".repeat(w.depth)}{w.name || "(no name)"}</option>)}
        </select>
        <span className="spacer" />
        <label><input type="checkbox" checked={real} onChange={(e) => setReal(e.target.checked)} /> Real graphics</label>
        <button onClick={() => plan(false)} disabled={!pending}>Preview changes</button>
        <button onClick={() => plan(true)} disabled={!pending}>Save</button>
        <button onClick={load}>Reset</button>
      </div>
      {error && <div className="creator-error">{error}</div>}
      <div className="rw-body">
        {root && ctx && data ? (
          <svg ref={svg} className="rw-canvas" preserveAspectRatio="xMinYMin meet"
            viewBox={`${minX} ${minY} ${maxX - minX} ${maxY - minY}`}
            onPointerDown={(e) => {
              const [x, y] = toSvg(e);
              // the smallest element under the pointer (the deepest on ties)
              const hit = placed
                .filter((p) => p.w > 0 && p.h > 0 && x >= p.x && x <= p.x + p.w && y >= p.y && y <= p.y + p.h)
                .sort((a, b) => a.w * a.h - b.w * b.h || b.depth - a.depth)[0];
              if (!hit) { setSel(null); return; }
              setSel(hit.el.line);
              if (hit.depth === 0) return; // the window itself is not moved here
              drag.current = { mode: "move", line: hit.el.line, px: x, py: y, a: hit.el.x, b: hit.el.y };
              (e.target as Element).setPointerCapture?.(e.pointerId);
            }}
            onPointerMove={(e) => {
              const d = drag.current;
              if (!d) return;
              const [x, y] = toSvg(e);
              const dx = Math.round(x - d.px);
              const dy = Math.round(y - d.py);
              if (!d.moved) { d.moved = true; history.mark(); } // the whole drag is one undo step
              if (d.mode === "move") setDragging(d.line, { x: d.a + dx, y: d.b + dy });
              else setDragging(d.line, { w: Math.max(1, d.a + dx), h: Math.max(1, d.b + dy) });
            }}
            onPointerUp={() => (drag.current = null)}
            onDoubleClick={() => sel && onOpen(data.file, sel)}
          >
            {real && data.backdrop.map((e, i) => <GuiNode key={`bg-${i}`} e={e} x={e.x} y={e.y} ctx={ctx} />)}
            <GuiNode e={{ ...root, x: 0, y: 0 }} x={0} y={0} ctx={ctx} />
            {placed.filter((p) => changes[p.el.line]).map((p) => (
              <rect key={`c-${p.el.line}`} x={p.x} y={p.y} width={Math.max(p.w, 4)} height={Math.max(p.h, 4)} className="gui-changed" />
            ))}
            {selected && (
              <g>
                <rect x={selected.x} y={selected.y} width={Math.max(selected.w, 4)} height={Math.max(selected.h, 4)} className="gui-selected" />
                {selected.depth > 0 && (selected.el.kind === "windowtype" || selected.el.w > 0 || selected.el.h > 0) && (
                  <rect x={selected.x + selected.w - 5} y={selected.y + selected.h - 5} width={10} height={10} className="gui-handle"
                    onPointerDown={(e) => {
                      e.stopPropagation();
                      const [x, y] = toSvg(e);
                      drag.current = { mode: "size", line: selected.el.line, px: x, py: y, a: selected.w, b: selected.h };
                      (e.target as Element).setPointerCapture?.(e.pointerId);
                    }} />
                )}
              </g>
            )}
          </svg>
        ) : (
          <div className="muted pad">{name ? "Loading…" : "Choose a window."}</div>
        )}
        <div className="rw-side">
          {selected && (
            <>
              <div className="panel-title">{selected.el.name || "(no name)"} <span className="muted">{selected.el.kind}</span></div>
              <div className="gui-props">
                {(["x", "y", "w", "h"] as const).map((k) => (
                  <label key={k}>{k} <input type="number" value={selected.el[k]}
                    onChange={(e) => set(selected.el.line, { [k]: Number(e.target.value) || 0 })} /></label>
                ))}
                <div className="muted small">
                  {selected.el.orientation !== "upper_left" && <>orientation {selected.el.orientation}<br /></>}
                  {selected.el.sprite && <>sprite {selected.el.sprite}<br /></>}
                  {selected.el.text && <>text {selected.el.text}{data?.texts[selected.el.text] ? ` = “${data.texts[selected.el.text]}”` : ""}<br /></>}
                  {selected.el.font && <>font {selected.el.font}<br /></>}
                  {original.get(selected.el.line) && changes[selected.el.line] && (
                    <>was {original.get(selected.el.line)!.x}, {original.get(selected.el.line)!.y}
                      {" "}({original.get(selected.el.line)!.w}×{original.get(selected.el.line)!.h})<br /></>
                  )}
                  <a href="#" onClick={(e) => { e.preventDefault(); if (data) onOpen(data.file, selected.el.line); }}>line {selected.el.line} in the code</a>
                </div>
              </div>
            </>
          )}
          <div className="panel-title">Elements {pending ? <span className="muted">· {pending} changed</span> : null}</div>
          {placed.map((p) => (
            <div key={p.el.line} className={"row small" + (p.el.line === sel ? " active" : "")} style={{ paddingLeft: 8 + p.depth * 12 }}
              onClick={() => setSel(p.el.line)}>
              {p.el.name || "(no name)"} <span className="muted">{p.el.kind.replace(/type$/, "")}</span>{changes[p.el.line] ? " •" : ""}
            </div>
          ))}
          <div className="muted rw-help">Click an element to select it, drag to move, drag the corner square to resize; numbers change it too. Positions are relative to the parent (and its corner / centre given by orientation). Double click opens the element in the code.</div>
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
