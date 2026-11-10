import type { GuiElement } from "../api";
import { ANCHORS, contentExtent, extentOf, placeOf, type DrawContext } from "./GuiDraw";

/**
 * Where the elements of a window go when the window gets bigger (T017).
 *
 * The game places an element from its parent's corner or centre (`orientation`):
 * elements tied to the right / bottom / centre move with a bigger window by
 * themselves; the others stay at the top-left corner. `placeInside` moves those:
 *
 * - "edges": elements whose spans overlap along an axis form a band (the left column
 *   of the politics window; the tabs, the panels under them and the reform boxes)
 *   and the band moves as one piece to the edge it is closest to: left / top
 *   (stays), right / bottom (by the whole growth) or the middle (by half). A band
 *   that spans most of the window keeps to its nearer edge. Bands are found for
 *   each axis on its own, so a grid never comes apart. Panels as big as the window
 *   (`reforms_window`) grow with it, and their elements join the window's bands
 *   (the reform boxes move with the tabs above them).
 * - "middle": everything moves by half the growth (stays where it was on the screen
 *   when the window keeps its centre).
 *
 * Backgrounds (pictures nearly as big as the window) are not moved: they are stretched.
 */

export type Placement = "edges" | "middle" | "none";
type Change = { x?: number; y?: number; w?: number; h?: number };

/** A share of the window (70 %) above which a picture is a background and a panel fills the window. */
const BIG = 0.7;
/**
 * The frame to keep when a background of the window is stretched ([left, top, right, bottom] px):
 * the picture grows just after the first column / row that moves (split), so what lies under the
 * elements that stay looks the same; without a split, just before its right / bottom edge.
 */
export function stretchFrame(pic: { x: number; y: number; w: number; h: number }, split: Placed["split"], spread: boolean): [number, number, number, number] {
  if (spread) return [40, 40, 40, 40];
  const at = (s: number | null, start: number, size: number) =>
    Math.max(40, Math.min(size - 41, s === null ? size - 80 : s - start + 20));
  return [at(split.x, pic.x, pic.w), at(split.y, pic.y, pic.h), 40, 40];
}

/** Elements closer than this (px) along an axis belong to one band. */
const TOUCH = 4;
/** A text box without a width (maxWidth is only a limit): its start counts, a guess would join neighbours. */
const TEXT_W = 30;

/** A picture nearly as big as its parent: stretched, not moved. */
export function isBackground(e: GuiElement, w: number, h: number, ctx: DrawContext): boolean {
  const s = ctx.sprites[e.sprite];
  return !!e.sprite && !!s?.found && s.w >= w * BIG && s.h >= h * BIG;
}

/** A sub-window that fills its parent (a tab panel at its corner with the parent's size). */
function fillsParent(e: GuiElement, w: number, h: number): boolean {
  return e.kind === "windowtype" && e.w >= w * BIG && e.h >= h * BIG
    && Math.abs(e.x) <= w * 0.1 && Math.abs(e.y) <= h * 0.1 && (ANCHORS[e.orientation] ?? [0, 0]).every((f) => f === 0);
}

/** 0 = stay at the start edge, 1 = move with the end edge, 0.5 = keep in the middle. */
function anchor(a: number, b: number, size: number): number {
  const before = Math.max(0, a), after = Math.max(0, size - b);
  if ((b - a) >= size * BIG) return before <= after ? 0 : 1;
  const t = before / (before + after || 1);
  return t < 0.25 ? 0 : t > 0.75 ? 1 : 0.5;
}

interface Unit { e: GuiElement; x0: number; y0: number; x1: number; y1: number }

export interface Placed {
  /** Changes by element line. */
  changes: Record<number, Change>;
  /** Where (in the window) the first column / row that moves begins, or null: a background is best
   *  stretched just after it, so the part under the elements that stay keeps its look. */
  split: { x: number | null; y: number | null };
}

/** Changes that place the elements of `root` (as in the file) in a window bigger by dw × dh. */
export function placeInside(root: GuiElement, dw: number, dh: number, ctx: DrawContext, mode: Placement): Placed {
  const out: Record<number, Change> = {};
  const split: Placed["split"] = { x: null, y: null };
  if (mode === "none" || (!dw && !dh)) return { changes: out, split };
  const W = root.w, H = root.h;
  const units: Unit[] = [];
  // ox, oy: where the children's parent is in the window (panels that fill the window share its frame)
  const collect = (children: GuiElement[], pw: number, ph: number, ox: number, oy: number) => {
    for (const c of children) {
      if (isBackground(c, pw, ph, ctx)) continue;
      const [fx, fy] = ANCHORS[c.orientation] ?? [0, 0];
      if (mode === "middle") {
        out[c.line] = { x: c.x + Math.round((0.5 - fx) * dw), y: c.y + Math.round((0.5 - fy) * dh) };
        continue;
      }
      if (fx !== 0 || fy !== 0) continue; // the game moves it already (close button at the right …)
      if (fillsParent(c, pw, ph)) {
        out[c.line] = { w: c.w + dw, h: c.h + dh };
        collect(c.children, c.w, c.h, ox + c.x, oy + c.y);
        continue;
      }
      const [x, y] = placeOf(c, pw, ph);
      let [w, h] = c.kind === "windowtype" && !c.sprite && c.children.length ? contentExtent(c, ctx) : extentOf(c, ctx);
      if (c.text && !c.w && !c.sprite) w = TEXT_W; // maxWidth is a limit, not the width
      if (!w && !h) continue;
      units.push({ e: c, x0: ox + x, y0: oy + y, x1: ox + x + w, y1: oy + y + h });
    }
  };
  collect(root.children, W, H, 0, 0);
  if (mode === "edges") {
    // bands: elements whose spans along an axis overlap (or nearly touch) move along it as one piece
    const bands = (lo: (u: Unit) => number, hi: (u: Unit) => number, size: number, grow: number, axis: "x" | "y") => {
      const shift = new Map<Unit, number>();
      const sorted = [...units].sort((p, q) => lo(p) - lo(q));
      for (let i = 0; i < sorted.length;) {
        let end = hi(sorted[i]), j = i + 1;
        while (j < sorted.length && lo(sorted[j]) <= end + TOUCH) end = Math.max(end, hi(sorted[j++]));
        const m = Math.round(anchor(lo(sorted[i]), end, size) * grow);
        for (const u of sorted.slice(i, j)) shift.set(u, m);
        if (m && split[axis] === null) split[axis] = lo(sorted[i]);
        i = j;
      }
      return shift;
    };
    const sx = bands((u) => u.x0, (u) => u.x1, W, dw, "x"), sy = bands((u) => u.y0, (u) => u.y1, H, dh, "y");
    for (const u of units) {
      const mx = sx.get(u) ?? 0, my = sy.get(u) ?? 0;
      if (mx || my) out[u.e.line] = { x: u.e.x + mx, y: u.e.y + my };
    }
  }
  return { changes: out, split };
}
