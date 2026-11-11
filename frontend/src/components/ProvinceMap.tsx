import { useEffect, useRef, useState } from "react";
import { api, mapUrl, type MapInfo, type MapProvince, type RGB } from "../api";
import { useZoom } from "./GuiDraw";

/**
 * The province map (K75 A, first part; the country creator, @A6): owners' colours at a date,
 * province borders, chosen provinces in gold. Hover shows the province, a click chooses it.
 * The picture comes as province colours (map/provinces.bmp); each pixel's province is found
 * by its colour, so the map is painted here and repainted when the choice changes.
 */

const SEA: [number, number, number] = [62, 98, 140];
const EMPTY: [number, number, number] = [196, 192, 176];
const GOLD: [number, number, number] = [255, 204, 0];

interface Pixels { w: number; h: number; ids: Int32Array; border: Uint8Array }

export function ProvinceMap({ date = "1836.1.1", selected, onToggle, info: given, paint, hint, selectedColor, focus }: {
  date?: string; selected: number[]; onToggle: (id: number) => void;
  /** The provinces' data when the caller has it already (the Map view). */
  info?: MapInfo | null;
  /** The colour of a land province (default: its owner's). */
  paint?: (id: number, p: MapProvince) => RGB;
  hint?: string;
  /** The colour of the chosen provinces (default gold). */
  selectedColor?: RGB;
  /** A province to zoom to (when it changes), e.g. from the editor's "Show on the map". */
  focus?: number | null;
}) {
  const [own, setInfo] = useState<MapInfo | null>(null);
  const info = given ?? own;
  const [pixels, setPixels] = useState<Pixels | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [error, setError] = useState("");
  const canvas = useRef<HTMLCanvasElement>(null);
  const zoom = useZoom();

  useEffect(() => {
    if (given !== undefined) return;
    api.mapInfo(date).then(setInfo).catch((e) => setError((e as Error).message));
  }, [date, given]);
  // which province each pixel is (by its colour), and where provinces meet
  useEffect(() => {
    if (!info) return;
    const img = new Image();
    img.onload = () => {
      const w = img.width, h = img.height;
      const c = document.createElement("canvas");
      c.width = w; c.height = h;
      const g = c.getContext("2d", { willReadFrequently: true })!;
      g.drawImage(img, 0, 0);
      const data = g.getImageData(0, 0, w, h).data;
      const byColor = new Map<number, number>();
      for (const [id, p] of Object.entries(info.provinces)) byColor.set((p.rgb[0] << 16) | (p.rgb[1] << 8) | p.rgb[2], Number(id));
      const ids = new Int32Array(w * h);
      for (let i = 0; i < w * h; i++) ids[i] = byColor.get((data[i * 4] << 16) | (data[i * 4 + 1] << 8) | data[i * 4 + 2]) ?? 0;
      const border = new Uint8Array(w * h);
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          const i = y * w + x;
          if ((x + 1 < w && ids[i + 1] !== ids[i]) || (y + 1 < h && ids[i + w] !== ids[i])) border[i] = 1;
        }
      }
      setPixels({ w, h, ids, border });
    };
    img.onerror = () => setError("the map picture could not be loaded");
    img.src = mapUrl(2);
  }, [info !== null]); // eslint-disable-line react-hooks/exhaustive-deps -- the picture does not change with the date
  // paint: owners' colours, sea, chosen provinces, borders
  useEffect(() => {
    if (!info || !pixels || !canvas.current) return;
    const { w, h, ids, border } = pixels;
    const cv = canvas.current;
    cv.width = w; cv.height = h;
    const g = cv.getContext("2d")!;
    const out = g.createImageData(w, h);
    const chosen = new Set(selected);
    const colorOf = new Map<number, [number, number, number]>();
    for (const [id, p] of Object.entries(info.provinces)) {
      const n = Number(id);
      const c = chosen.has(n) ? (selectedColor ?? GOLD) : !p.land ? SEA : paint ? paint(n, p) : p.owner ? ((info.colors[p.owner] ?? EMPTY) as RGB) : EMPTY;
      colorOf.set(n, n === hover && p.land ? [Math.min(255, c[0] + 50), Math.min(255, c[1] + 50), Math.min(255, c[2] + 50)] : c);
    }
    for (let i = 0; i < w * h; i++) {
      const c = colorOf.get(ids[i]) ?? SEA;
      const dark = border[i] && info.provinces[ids[i]]?.land ? 0.55 : 1;
      out.data[i * 4] = c[0] * dark; out.data[i * 4 + 1] = c[1] * dark; out.data[i * 4 + 2] = c[2] * dark; out.data[i * 4 + 3] = 255;
    }
    g.putImageData(out, 0, 0);
  }, [info, pixels, selected, hover, paint, selectedColor]);

  // zoom to a province: its pixels' box takes about a fifth of the view (K98 C, @A7 8)
  useEffect(() => {
    if (!focus || !pixels) return;
    const { w, h, ids } = pixels;
    let x0 = w, y0 = h, x1 = -1, y1 = -1;
    for (let i = 0; i < w * h; i++) {
      if (ids[i] !== focus) continue;
      const x = i % w, y = (i - x) / w;
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
    if (x1 < 0) return;
    zoom.showAt(Math.min(w / (x1 - x0 + 1), h / (y1 - y0 + 1)) / 5, (x0 + x1) / 2 / w, (y0 + y1) / 2 / h);
  }, [focus, pixels]); // eslint-disable-line react-hooks/exhaustive-deps

  const at = (e: React.MouseEvent<HTMLCanvasElement>): number => {
    if (!pixels) return 0;
    const r = e.currentTarget.getBoundingClientRect();
    const x = Math.floor(((e.clientX - r.left) / r.width) * pixels.w);
    const y = Math.floor(((e.clientY - r.top) / r.height) * pixels.h);
    return pixels.ids[y * pixels.w + x] ?? 0;
  };
  const p = hover ? info?.provinces[hover] : undefined;
  if (error) return <div className="creator-error">{error}</div>;
  if (!info || !pixels) return <div className="muted">Loading the map…</div>;
  return (
    <div className="province-map">
      <div className="muted">
        {p ? <>#{hover} <b>{p.name}</b> · {p.land ? `owner ${p.owner || "none"}${p.cores.length ? ` · cores ${p.cores.join(" ")}` : ""}` : "sea"}</> : hint ?? "Click a province to choose it (again to drop it); Ctrl + wheel zooms."}
        <span className="spacer" /> {zoom.controls}
      </div>
      <div className="province-map-box" ref={zoom.box}>
        <canvas ref={canvas} style={{ width: `${zoom.zoom * 100}%` }}
          onMouseMove={(e) => { const id = at(e); if (id !== hover) setHover(id || null); }}
          onMouseLeave={() => setHover(null)}
          onClick={(e) => { const id = at(e); if (id && info.provinces[id]?.land) onToggle(id); }} />
      </div>
    </div>
  );
}
