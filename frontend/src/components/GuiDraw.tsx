import { spriteUrl, type GuiElement, type SpriteInfo } from "../api";

/**
 * Drawing elements of the game's windows (K80): as outlines with names and
 * texts, or with the real pictures. Positions follow the game: relative to
 * the parent, from the corner / centre its `orientation` names.
 */

export const ANCHORS: Record<string, [number, number]> = {
  upper_left: [0, 0], upper_right: [1, 0], lower_left: [0, 1], lower_right: [1, 1],
  center: [0.5, 0.5], centre: [0.5, 0.5], center_up: [0.5, 0], center_down: [0.5, 1],
  center_left: [0, 0.5], center_right: [1, 0.5],
};

export interface DrawContext {
  real: boolean; // real pictures instead of outlines
  sprites: Record<string, SpriteInfo>;
  texts: Record<string, string>;
  /** Text to show instead of a localisation key (e.g. REFORM_NAME -> the issue's name). */
  replace?: Record<string, string>;
}

/** Size of an element: its own size, else its picture's, else its text box's. */
export function sizeOf(e: GuiElement, ctx: DrawContext): [number, number] {
  const s = ctx.sprites[e.sprite];
  const w = e.w || (s?.w ?? 0) || e.max_w || (e.text ? 120 : 0);
  const h = e.h || (s?.h ?? 0) || e.max_h || (e.text ? 18 : 0);
  return [w, h];
}

/** Top-left corner of an element inside a parent of the given size. */
export function placeOf(e: GuiElement, parentW: number, parentH: number): [number, number] {
  const [fx, fy] = ANCHORS[e.orientation] ?? [0, 0];
  return [fx * parentW + e.x, fy * parentH + e.y];
}

/** Bottom-right extent of an element and its children (relative to its own corner). */
export function extentOf(e: GuiElement, ctx: DrawContext): [number, number] {
  let [w, h] = sizeOf(e, ctx);
  for (const c of e.children) {
    const [cx, cy] = placeOf(c, w, h);
    const [cw, ch] = extentOf(c, ctx);
    w = Math.max(w, cx + cw);
    h = Math.max(h, cy + ch);
  }
  return [w, h];
}

/**
 * What a window really shows: the extent of its children (a windowType's own
 * `size` is often much bigger than what is drawn, e.g. 310×100 for an issue box).
 */
export function contentExtent(e: GuiElement, ctx: DrawContext): [number, number] {
  const [pw, ph] = sizeOf(e, ctx);
  let w = 0;
  let h = 0;
  for (const c of e.children) {
    const [cx, cy] = placeOf(c, pw, ph);
    const [cw, ch] = extentOf(c, ctx);
    w = Math.max(w, cx + cw);
    h = Math.max(h, cy + ch);
  }
  return [w, h];
}

const textColor = (font: string, real: boolean) =>
  /black/i.test(font) ? "#1a1a1a" : real ? "#f2e6c4" : "var(--text)";

/** One element and its children, drawn at (x, y). */
export function GuiNode({ e, x, y, ctx, skip }: {
  e: GuiElement; x: number; y: number; ctx: DrawContext;
  /** Children not to draw here (drawn by the caller, e.g. draggable issue boxes). */
  skip?: (child: GuiElement) => boolean;
}) {
  const [w, h] = sizeOf(e, ctx);
  const s = ctx.sprites[e.sprite];
  const text = e.text ? (ctx.replace?.[e.text] ?? ctx.texts[e.text] ?? e.text) : "";
  const anchorX = e.format === "centre" || e.format === "center" ? x + (e.max_w || w) / 2 : e.format === "right" ? x + (e.max_w || w) : x;
  const anchor = e.format === "centre" || e.format === "center" ? "middle" : e.format === "right" ? "end" : "start";
  return (
    <g>
      {e.sprite && ctx.real && s?.found && w > 0 && h > 0 && (
        <image href={spriteUrl(e.sprite, 1)} x={x} y={y} width={w} height={h} preserveAspectRatio="none" />
      )}
      {!ctx.real && (e.kind === "windowtype" || e.sprite) && w > 0 && h > 0 && (
        <rect x={x} y={y} width={w} height={h} className={`gui-outline ${e.kind}`}>
          <title>{`${e.kind} ${e.name}${e.sprite ? ` · ${e.sprite}` : ""} · ${w}×${h}`}</title>
        </rect>
      )}
      {!ctx.real && e.sprite && w >= 24 && h >= 10 && (
        <text x={x + 2} y={y + 9} className="gui-name">{e.name || e.sprite}</text>
      )}
      {text && (
        <text x={anchorX} y={y + Math.min(h || 16, 16) - 3} textAnchor={anchor} className="gui-text"
          style={{ fill: textColor(e.font, ctx.real), fontSize: /1[89]|2\d/.test(e.font) ? 15 : 12 }}>
          {text}
        </text>
      )}
      {e.children.filter((c) => !skip?.(c)).map((c, i) => {
        const [cx, cy] = placeOf(c, w, h);
        return <GuiNode key={`${c.name}-${i}`} e={c} x={x + cx} y={y + cy} ctx={ctx} />;
      })}
    </g>
  );
}
