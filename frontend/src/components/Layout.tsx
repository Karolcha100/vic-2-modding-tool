import { useRef, useState } from "react";

/** State remembered in this browser (panel sizes, the minimap). Storage may be unavailable. */
export function useStored<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  const set = (v: T) => {
    setValue(v);
    try {
      window.localStorage.setItem(key, JSON.stringify(v));
    } catch {
      /* not remembered, still works */
    }
  };
  return [value, set];
}

interface SplitterProps {
  /**
   * Where the handle is: on the right edge of a left panel, the left edge of a
   * right panel, the top edge of a bottom panel, or between two flex items
   * (sizing the item after it).
   */
  edge: "right" | "left" | "top" | "between";
  size: number;
  setSize: (v: number) => void;
  min: number;
  max: number;
  /** Size after a double click. */
  reset: number;
  /** Current size when ``size`` is 0 (``between``: measured from the layout). */
  measure?: (handle: HTMLElement) => number;
}

/** A handle to drag a panel border with the mouse (T005: resizable panels). */
export function Splitter({ edge, size, setSize, min, max, reset, measure }: SplitterProps) {
  const start = useRef<{ x: number; y: number; size: number } | null>(null);
  const vertical = edge === "top";
  return (
    <div
      className={`splitter ${edge}`}
      title="Drag to resize · double click: default size"
      onPointerDown={(e) => {
        const el = e.currentTarget;
        el.setPointerCapture(e.pointerId);
        const now = size || measure?.(el) || 0;
        start.current = { x: e.clientX, y: e.clientY, size: now };
        document.body.classList.add(vertical ? "resizing-y" : "resizing-x");
      }}
      onPointerMove={(e) => {
        const s = start.current;
        if (!s) return;
        const d = vertical ? s.y - e.clientY : edge === "right" ? e.clientX - s.x : s.x - e.clientX;
        setSize(Math.round(Math.min(max, Math.max(min, s.size + d))));
      }}
      onPointerUp={() => {
        start.current = null;
        document.body.classList.remove("resizing-x", "resizing-y");
      }}
      onDoubleClick={() => setSize(reset)}
    />
  );
}

/**
 * A side panel whose width is dragged at its inner border, the neighbour taking the rest (T019).
 * `side`: where the panel is ("left": handle on its right edge; "right": on its left edge).
 */
export function SidePanel({ id, side, initial, min = 160, max = 1400, className, children }: {
  id: string; side: "left" | "right"; initial: number; min?: number; max?: number; className?: string;
  children: React.ReactNode;
}) {
  const [w, setW] = useStored(`vic2.pane.${id}`, initial);
  return (
    <div className={className} style={{ width: w, flex: `0 0 ${w}px`, position: "relative" }}>
      {children}
      <Splitter edge={side === "left" ? "right" : "left"} size={w} setSize={setW} min={min} max={max} reset={initial} />
    </div>
  );
}
