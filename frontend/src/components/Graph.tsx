import { useEffect, useMemo, useRef, useState } from "react";

/** A small interactive graph: force layout (no libraries, K47), draggable nodes. */

export interface GNode { id: string; label: string; color?: string; title?: string }
export interface GEdge { source: string; target: string; width?: number; label?: string; key: string }

interface Props {
  nodes: GNode[];
  edges: GEdge[];
  selected?: string | null;
  onNode?: (id: string) => void;
  onEdge?: (key: string) => void;
  /** Click on the empty background (e.g. to clear the selection). */
  onBackground?: () => void;
  /** "circle" for small dense graphs (pop types), "force" for sparse ones (events). */
  shape?: "circle" | "force";
}

const W = 1000;
const H = 700;

function layout(nodes: GNode[], edges: GEdge[], shape: "circle" | "force"): Record<string, [number, number]> {
  const pos: Record<string, [number, number]> = {};
  nodes.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, nodes.length) - Math.PI / 2;
    pos[n.id] = [W / 2 + Math.cos(a) * W * 0.38, H / 2 + Math.sin(a) * H * 0.4];
  });
  if (shape === "circle") return pos;
  const k = Math.sqrt((W * H) / Math.max(1, nodes.length)) * 0.9;
  for (let it = 0; it < 300; it++) {
    const disp: Record<string, [number, number]> = Object.fromEntries(nodes.map((n) => [n.id, [0, 0]]));
    for (const a of nodes) for (const b of nodes) {
      if (a.id === b.id) continue;
      const dx = pos[a.id][0] - pos[b.id][0];
      const dy = pos[a.id][1] - pos[b.id][1];
      const d = Math.max(1, Math.hypot(dx, dy));
      const f = (k * k) / d;
      disp[a.id][0] += (dx / d) * f;
      disp[a.id][1] += (dy / d) * f;
    }
    for (const e of edges) {
      if (e.source === e.target || !pos[e.source] || !pos[e.target]) continue;
      const dx = pos[e.source][0] - pos[e.target][0];
      const dy = pos[e.source][1] - pos[e.target][1];
      const d = Math.max(1, Math.hypot(dx, dy));
      const f = (d * d) / k / 3;
      disp[e.source][0] -= (dx / d) * f; disp[e.source][1] -= (dy / d) * f;
      disp[e.target][0] += (dx / d) * f; disp[e.target][1] += (dy / d) * f;
    }
    const t = 40 * (1 - it / 300) + 1;
    for (const n of nodes) {
      const [dx, dy] = disp[n.id];
      const d = Math.max(1, Math.hypot(dx, dy));
      pos[n.id][0] = Math.min(W - 60, Math.max(60, pos[n.id][0] + (dx / d) * Math.min(d, t)));
      pos[n.id][1] = Math.min(H - 30, Math.max(30, pos[n.id][1] + (dy / d) * Math.min(d, t)));
    }
  }
  return pos;
}

const R = 13; // node radius

/** End of an edge pulled back to the target circle, so the arrow tip touches it. */
function shorten(b: [number, number], from: [number, number], by: number): [number, number] {
  const dx = b[0] - from[0];
  const dy = b[1] - from[1];
  const d = Math.max(1, Math.hypot(dx, dy));
  return [b[0] - (dx / d) * by, b[1] - (dy / d) * by];
}

export function Graph({ nodes, edges, selected, onNode, onEdge, onBackground, shape = "force" }: Props) {
  const initial = useMemo(() => layout(nodes, edges, shape), [nodes, edges, shape]);
  const [pos, setPos] = useState(initial);
  useEffect(() => setPos(initial), [initial]);
  const drag = useRef<string | null>(null);
  const svg = useRef<SVGSVGElement>(null);

  const toSvg = (e: React.PointerEvent): [number, number] => {
    const ctm = svg.current!.getScreenCTM();
    if (!ctm) return [0, 0];
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse());
    return [p.x, p.y];
  };
  const seen = new Map<string, number>();

  return (
    <svg ref={svg} className="graph" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
      onPointerMove={(e) => { if (drag.current) { const p = toSvg(e); setPos((s) => ({ ...s, [drag.current!]: p })); } }}
      onPointerUp={() => (drag.current = null)} onPointerLeave={() => (drag.current = null)}>
      <defs>
        {(["", "out", "in"] as const).map((k) => (
          <marker key={k} id={`arrow${k}`} viewBox="0 0 10 10" refX="10" refY="5" markerUnits="userSpaceOnUse"
            markerWidth="12" markerHeight="12" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" className={`graph-arrow ${k}`} />
          </marker>
        ))}
      </defs>
      <rect className="graph-bg" x={0} y={0} width={W} height={H} onClick={() => onBackground?.()} />
      {edges.map((e) => {
        const a = pos[e.source];
        const b = pos[e.target];
        if (!a || !b) return null;
        const pair = [e.source, e.target].sort().join("|");
        const n = seen.get(pair) ?? 0;
        seen.set(pair, n + 1);
        // Selected node: outgoing edges red, incoming blue, the rest faded.
        const dir = !selected ? "" : e.source === selected ? "out" : e.target === selected ? "in" : "dim";
        const cls = "graph-edge" + (dir ? ` ${dir}` : "");
        if (e.source === e.target) {
          return <path key={e.key} d={`M ${a[0]} ${a[1] - 14} c 30 -40 60 0 18 16`} className={cls}
            strokeWidth={e.width ?? 1.5} fill="none" onClick={() => onEdge?.(e.key)}><title>{e.label}</title></path>;
        }
        const mx = (a[0] + b[0]) / 2 + (n % 2 ? 1 : -1) * n * 12;
        const my = (a[1] + b[1]) / 2 + (n % 2 ? -1 : 1) * n * 12;
        const end = shorten(b, [mx, my], R + 2); // the curve arrives from its control point
        const marker = dir === "out" || dir === "in" ? dir : "";
        return (
          <path key={e.key} d={`M ${a[0]} ${a[1]} Q ${mx} ${my} ${end[0]} ${end[1]}`} className={cls}
            strokeWidth={e.width ?? 1.5} fill="none" markerEnd={`url(#arrow${marker})`} onClick={() => onEdge?.(e.key)}>
            <title>{e.label}</title>
          </path>
        );
      })}
      {nodes.map((n) => {
        const p = pos[n.id];
        if (!p) return null;
        return (
          <g key={n.id} transform={`translate(${p[0]},${p[1]})`} className={"graph-node" + (n.id === selected ? " sel" : "")}
            onPointerDown={(e) => { drag.current = n.id; (e.target as Element).setPointerCapture?.(e.pointerId); }}
            onClick={() => onNode?.(n.id)}>
            <circle r={R} fill={n.color ?? "#4f7cc9"} />
            <text y={28} textAnchor="middle">{n.label}</text>
            <title>{n.title ?? n.label}</title>
          </g>
        );
      })}
    </svg>
  );
}
