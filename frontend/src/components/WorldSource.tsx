import { useEffect, useState } from "react";
import { api, type SaveGame } from "../api";

/**
 * Where the trigger tester and the map read the world from (K75 B, K98 A): the history files
 * at a start date, or a save game (.v2) found in Victoria II's save folders (or a path).
 */
export function WorldSource({ date, setDate, save, setSave }: {
  date: string; setDate: (d: string) => void; save: string; setSave: (s: string) => void;
}) {
  const [saves, setSaves] = useState<SaveGame[] | null>(null);
  useEffect(() => { api.saves().then((r) => setSaves(r.saves)).catch(() => setSaves([])); }, []);
  const folders = [...new Set((saves ?? []).map((s) => s.folder))];
  const known = !save || (saves ?? []).some((s) => s.path === save);
  return (
    <span className="world-source">
      from <select value={save ? (known ? save : "?path") : ""} onChange={(e) => {
        const v = e.target.value;
        if (v === "?path") { const p = window.prompt("Path of a save game (.v2):", save); if (p) setSave(p.trim()); return; }
        setSave(v);
      }} title="the history files at a start date, or the state of a saved game">
        <option value="">history files</option>
        {folders.map((f) => (
          <optgroup key={f} label={`saves: ${f}`}>
            {(saves ?? []).filter((s) => s.folder === f).slice(0, 60).map((s) => (
              <option key={s.path} value={s.path}>{s.name} ({new Date(s.time * 1000).toLocaleDateString()})</option>
            ))}
          </optgroup>
        ))}
        {!known && <option value="?path">{save}</option>}
        <option value="?path">a save game by its path…</option>
      </select>
      {!save && <> at <input value={date} onChange={(e) => setDate(e.target.value)} size={10} title="a start date: the history up to it (e.g. 1836.1.1)" /></>}
    </span>
  );
}
