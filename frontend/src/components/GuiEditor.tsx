import { useEffect, useMemo, useRef, useState } from "react";
import { api, type GuiElement, type GuiWindow } from "../api";
import { GuiNode, placeOf, sizeOf, useZoom, type DrawContext } from "./GuiDraw";
import { SidePanel, useStored } from "./Layout";
import { isBackground, placeInside, stretchFrame, type Placement } from "./guiResize";
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
  const [panel, setPanel] = useStored("vic2.gui.panel", true);
  // Elements hidden from the drawing, per window (T015): e.g. tab panels that cover each other.
  const [hiddenAll, setHiddenAll] = useStored<Record<string, number[]>>("vic2.gui.hidden", {});
  const hiddenKey = `${rel}#${name}`;
  const hidden = useMemo(() => new Set(hiddenAll[hiddenKey] ?? []), [hiddenAll, hiddenKey]);
  const hiddenRef = useRef(hiddenAll); // the latest value, also for clicks in quick succession
  hiddenRef.current = hiddenAll;
  const toggleHidden = (line: number) => {
    const next = new Set(hiddenRef.current[hiddenKey] ?? []);
    if (next.has(line)) next.delete(line); else next.add(line);
    hiddenRef.current = { ...hiddenRef.current, [hiddenKey]: [...next] };
    setHiddenAll(hiddenRef.current);
  };
  const zoom = useZoom();
  // K94: a bigger window - its new size (keeping its centre) and pictures stretched to fit
  const [resize, setResize] = useState<null | { w: string; h: string; centre: boolean; place: Placement }>(null);
  // border: px kept as they are at the left, top, right and bottom edge
  const [stretchOf, setStretchOf] = useState<null | { sprite: string; line: number; w: string; h: string; border: string[]; preview?: string; note?: string }>(null);
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
  const allPlaced = useMemo(() => (root && ctx ? flatten(root, ctx) : []), [root, ctx]);
  // an element is hidden with everything inside it
  const hiddenLines = useMemo(() => {
    const out = new Set<number>();
    const walk = (e: GuiElement, under: boolean) => {
      const h = under || hidden.has(e.line);
      if (h) out.add(e.line);
      e.children.forEach((c) => walk(c, h));
    };
    if (root) walk(root, false);
    return out;
  }, [root, hidden]);
  const placed = useMemo(() => allPlaced.filter((p) => !hiddenLines.has(p.el.line)), [allPlaced, hiddenLines]);
  // Sub-windows of the window that lie on top of each other (tab panels: the game shows one at a time).
  const stacked = useMemo(() => {
    const subs = allPlaced.filter((p) => p.depth === 1 && p.el.kind === "windowtype" && p.w > 0 && p.h > 0 && !hiddenLines.has(p.el.line));
    const overlap = (a: (typeof subs)[0], b: (typeof subs)[0]) => {
      const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
      const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
      return w > 0 && h > 0 && w * h > 0.5 * Math.min(a.w * a.h, b.w * b.h);
    };
    return subs.filter((a) => subs.some((b) => b !== a && overlap(a, b)));
  }, [allPlaced, hiddenLines]);
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
        {zoom.controls}
        <button disabled={!data} onClick={() => root && setResize({ w: String(Math.max(root.w, 1600)), h: String(Math.max(root.h, 900)), centre: true, place: "edges" })}
          title="Give the window a new size (K94); its backgrounds can then be stretched to fit">Resize window…</button>
        <button onClick={() => setPanel(!panel)} title="Show or hide the panel with the elements">{panel ? "Hide panel" : "Show panel"}</button>
        <button onClick={() => plan(false)} disabled={!pending}>Preview changes</button>
        <button onClick={() => plan(true)} disabled={!pending}>Save</button>
        <button onClick={load}>Reset</button>
      </div>
      {error && <div className="creator-error">{error}</div>}
      <div className="rw-body">
        {root && ctx && data ? (
          <div className="rw-scroll" ref={zoom.box}>
          <svg ref={svg} className="rw-canvas" preserveAspectRatio="xMinYMin meet" style={zoom.style}
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
            <GuiNode e={{ ...root, x: 0, y: 0 }} x={0} y={0} ctx={ctx} skip={(c) => hiddenLines.has(c.line)} />
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
          </div>
        ) : (
          <div className="muted pad">{name ? "Loading…" : "Choose a window."}</div>
        )}
        {panel && <SidePanel id="interface" side="right" initial={260} className="rw-side">
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
                  {selected.el.sprite && <>sprite {selected.el.sprite}{" "}
                    <a href="#" onClick={(e) => { e.preventDefault(); const sp = data?.sprites[selected.el.sprite];
                      setStretchOf({ sprite: selected.el.sprite, line: selected.el.line, w: String(sp?.w || selected.w), h: String(sp?.h || selected.h), border: ["40", "40", "40", "40"] }); }}>stretch picture…</a><br /></>}
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
          {stacked.length > 1 && (
            <div className="muted small pad">These panels lie on top of each other (tabs: the game shows one at a time): {stacked.map((p) => p.el.name).join(", ")}. Untick the ones you do not want to see.</div>
          )}
          {allPlaced.map((p) => (
            <div key={p.el.line} className={"row small" + (p.el.line === sel ? " active" : "") + (hiddenLines.has(p.el.line) ? " hidden-el" : "")}
              style={{ paddingLeft: 8 + p.depth * 12 }} onClick={() => setSel(p.el.line)}>
              {p.depth > 0 && <input type="checkbox" checked={!hidden.has(p.el.line)} title="Show it in the drawing (hidden elements stay in the file)"
                onClick={(e) => e.stopPropagation()} onChange={() => toggleHidden(p.el.line)} />}
              {p.el.name || "(no name)"} <span className="muted">{p.el.kind.replace(/type$/, "")}</span>{changes[p.el.line] ? " •" : ""}
            </div>
          ))}
          <div className="muted rw-help">Click an element to select it, drag to move, drag the corner square to resize; numbers change it too. Positions are relative to the parent (and its corner / centre given by orientation). Double click opens the element in the code. Untick an element to hide it in the drawing (e.g. tab panels of one window that cover each other; the game shows one at a time). Ctrl + mouse wheel zooms.</div>
        </SidePanel>}
      </div>
      {resize && root && data && (() => {
        const was = original.get(root.line) ?? root; // the size in the file, before any change here
        const w = Number(resize.w) || root.w, h = Number(resize.h) || root.h;
        const dw = w - was.w, dh = h - was.h;
        // backgrounds: pictures of the window's own elements nearly as big as the window
        const backs = root.children.filter((c) => isBackground(c, was.w, was.h, ctx!));
        const { split } = placeInside(data.tree, dw, dh, ctx!, resize.place);
        return (
          <div className="preview-backdrop" onClick={() => setResize(null)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="creator-form">
                <b>Resize the window {root.name}</b>
                <div className="muted">In the file {was.w}×{was.h} at {was.x}, {was.y} ({root.orientation}). The game does not scale: players with a smaller screen do not see the edges.</div>
                <label>Width <input value={resize.w} onChange={(e) => setResize({ ...resize, w: e.target.value })} /></label>
                <label>Height <input value={resize.h} onChange={(e) => setResize({ ...resize, h: e.target.value })} /></label>
                <label><input type="checkbox" checked={resize.centre} onChange={(e) => setResize({ ...resize, centre: e.target.checked })} /> keep the centre where it is (moves the window by {-Math.round(dw / 2)}, {-Math.round(dh / 2)})</label>
                <label>Elements inside <select value={resize.place} onChange={(e) => setResize({ ...resize, place: e.target.value as Placement })}>
                  <option value="edges">move to the nearest edge (columns and rows move as one piece)</option>
                  <option value="middle">keep them in the middle</option>
                  <option value="none">leave them (only the window changes)</option>
                </select></label>
                <div className="muted">{resize.place === "edges"
                  ? "Elements that overlap from left to right form a column (e.g. the tabs, the panels and the reform boxes under them), and those that overlap from top to bottom a row. A column near the left edge stays, near the right edge moves with it, in the middle moves by half; rows the same with the top and bottom. Panels as big as the window grow with it. Elements the game already ties to an edge (close button) and the backgrounds are not moved. Ctrl+Z undoes."
                  : resize.place === "middle" ? "Every element moves by half the growth: on the screen it stays where it was." : "Only elements tied to the right / bottom edge or the centre move (the game does that); the rest stay at the top-left corner."}</div>
                <div className="creator-buttons">
                  <button onClick={() => {
                    // one step of Ctrl+Z: the window and its elements (placed from the file's positions)
                    const inside = placeInside(data.tree, dw, dh, ctx!, resize.place).changes;
                    history.set((all) => {
                      const next = { ...all };
                      for (const [line, c] of Object.entries(inside)) next[Number(line)] = { ...next[Number(line)], ...c };
                      next[root.line] = { ...next[root.line], w, h, ...(resize.centre ? { x: was.x - Math.round(dw / 2), y: was.y - Math.round(dh / 2) } : {}) };
                      return next;
                    });
                    onStatus(`Window ${root.name}: ${w}×${h}, ${Object.keys(inside).length} elements placed - not saved yet (Preview changes / Save)`);
                  }}>Apply the size</button>
                  <button onClick={() => setResize(null)}>Close</button>
                </div>
                {backs.length > 0 && <div><b>Backgrounds to stretch by the same amount</b> ({dw >= 0 ? "+" : ""}{dw}, {dh >= 0 ? "+" : ""}{dh}):</div>}
                {backs.map((c) => {
                  const sp = data.sprites[c.sprite]!;
                  return (
                    <div key={c.line} className="row">{c.name} <span className="muted">{c.sprite} {sp.w}×{sp.h}</span>{" "}
                      <button className="mini" onClick={() => setStretchOf({ sprite: c.sprite, line: c.line, w: String(sp.w + dw), h: String(sp.h + dh),
                        border: stretchFrame({ x: c.x, y: c.y, w: sp.w, h: sp.h }, split, resize.place === "middle").map(String) })}>
                        stretch to {sp.w + dw}×{sp.h + dh}…</button>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        );
      })()}
      {stretchOf && (
        <div className="preview-backdrop" onClick={() => setStretchOf(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="creator-form">
              <b>Stretch the picture of {stretchOf.sprite}</b>
              <div className="muted">The frame stays sharp: the edges below (px from the left, top, right and bottom) are kept as they are, only the part between them is stretched. For a background with panels drawn into it, a large left / top value keeps the panels under the elements that do not move (the Resize window dialog proposes it). The picture becomes a new file and a new sprite (in interface/vic2toolmod_stretched.gfx), and only this element is pointed at it: the original picture is often shared by many windows and stays as it is.</div>
              <label>Width <input value={stretchOf.w} onChange={(e) => setStretchOf({ ...stretchOf, w: e.target.value, preview: undefined })} /></label>
              <label>Height <input value={stretchOf.h} onChange={(e) => setStretchOf({ ...stretchOf, h: e.target.value, preview: undefined })} /></label>
              <label className="stretch-frame">Kept as it is (px): {["left", "top", "right", "bottom"].map((side, i) => (
                <span key={side}>{side} <input value={stretchOf.border[i]} onChange={(e) => setStretchOf({ ...stretchOf, border: stretchOf.border.map((b, k) => (k === i ? e.target.value : b)), preview: undefined })} /></span>
              ))}</label>
              <div className="creator-buttons">
                <button onClick={async () => {
                  try {
                    const r = await api.stretchPicture({ sprite: stretchOf.sprite, width: Number(stretchOf.w), height: Number(stretchOf.h), border: stretchOf.border.map(Number), write: false });
                    setStretchOf({ ...stretchOf, preview: r.preview, note: `${r.file}: ${r.from.join("×")} → ${r.to.join("×")}` });
                  } catch (e) { setStretchOf({ ...stretchOf, note: (e as Error).message }); }
                }}>Preview</button>
                <button disabled={!stretchOf.preview} onClick={async () => {
                  if (!window.confirm(`Write the stretched picture into the mod? A backup is made first.`)) return;
                  try {
                    const r = await api.stretchPicture({ sprite: stretchOf.sprite, width: Number(stretchOf.w), height: Number(stretchOf.h), border: stretchOf.border.map(Number), write: true, rel: data?.file ?? rel, line: stretchOf.line });
                    onStatus(`New picture ${r.texture} (${r.to.join("×")}), sprite ${r.sprite}${r.backup ? `; backup: ${r.backup}` : ""}`);
                    setStretchOf(null);
                    if (data) setData(await api.guiWindow(rel, name));
                  } catch (e) { setStretchOf({ ...stretchOf, note: (e as Error).message }); }
                }}>Write</button>
                <button onClick={() => setStretchOf(null)}>Cancel</button>
              </div>
              {stretchOf.note && <div className="muted">{stretchOf.note}</div>}
              {stretchOf.preview && <img className="stretch-preview" src={`data:image/png;base64,${stretchOf.preview}`} alt="preview" />}
            </div>
          </div>
        </div>
      )}
      {diff !== null && (
        <div className="rw-diff">
          <div className="panel-title">Changes <span onClick={() => setDiff(null)}>close</span></div>
          <pre>{diff}</pre>
        </div>
      )}
    </div>
  );
}
