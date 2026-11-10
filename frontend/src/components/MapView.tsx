import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type MapInfo, type MapProvince, type ProvinceDetail, type RGB } from "../api";
import { SidePanel, useStored } from "./Layout";
import { useNav } from "../nav";
import { ProvinceMap } from "./ProvinceMap";
import { WorldSource } from "./WorldSource";

/**
 * Analyses → Map (K97 A): the province map at a start date coloured by owner, culture,
 * religion, trade goods, terrain, continent or pop count, or by where a trigger holds;
 * a click shows the province (history, cores, pops, neighbours) and opens its file.
 */

type Mode = "owner" | "culture" | "religion" | "trade_goods" | "terrain" | "continent" | "pops" | "prestige" | "government" | "civilized" | "trigger";
const MODES: [Mode, string][] = [
  ["owner", "owner"], ["culture", "culture (most pops)"], ["religion", "religion (most pops)"], ["trade_goods", "trade goods"],
  ["terrain", "terrain"], ["continent", "continent"], ["pops", "pop count"], ["prestige", "owner's prestige"],
  ["government", "owner's government"], ["civilized", "owner civilised or not"], ["trigger", "where a trigger holds"],
];
const NONE: RGB = [196, 192, 176];
const YES: RGB = [46, 160, 67], NO: RGB = [200, 70, 60], UNKNOWN: RGB = [150, 150, 150];

/** A stable colour for a name (the files give none for goods, terrain, continents). */
function hashColor(name: string): RGB {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const hue = h % 360, s = 0.45 + ((h >> 9) % 30) / 100, l = 0.45 + ((h >> 15) % 20) / 100;
  const k = (n: number) => (n + hue / 30) % 12, a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)];
}

export function MapView({ onOpen }: { onOpen: (rel: string, line?: number) => void }) {
  const [date, setDate] = useStored("vic2.map.date", "1836.1.1");
  const [save, setSave] = useStored("vic2.map.save", "");
  const [mode, setMode] = useStored<Mode>("vic2.map.mode", "owner");
  const [text, setText] = useStored("vic2.map.trigger", "is_core = ENG");
  const [scope, setScope] = useStored<"province" | "owner">("vic2.map.scope", "province");
  const [info, setInfo] = useState<MapInfo | null>(null);
  const [results, setResults] = useState<{ results: Record<string, boolean | null>; true: number; false: number; unknown: number } | null>(null);
  // the chosen province is a navigation step; "Show on the map" in the editor sets it (K98 C)
  const [sel, setSel] = useNav<number | null>("map.sel", null);
  const [detail, setDetail] = useState<ProvinceDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => { setInfo(null); setError(""); api.mapInfo(date, save).then(setInfo).catch((e) => setError((e as Error).message)); }, [date, save]);
  useEffect(() => {
    if (sel === null) { setDetail(null); return; }
    api.mapProvince(sel, date, save).then(setDetail).catch((e) => setError((e as Error).message));
  }, [sel, date, save]);
  const runTrigger = async () => {
    setError("");
    try { setResults(await api.mapTrigger(text, scope, { date, player: "", great: "", secondary: "", save })); setMode("trigger"); }
    catch (e) { setError((e as Error).message); }
  };

  const maxPops = useMemo(() => Math.max(1, ...Object.values(info?.provinces ?? {}).map((p) => p.pops)), [info]);
  const keyOf = useCallback((p: MapProvince): string => (mode === "owner" ? p.owner : mode === "culture" ? p.culture : mode === "religion" ? p.religion
    : mode === "trade_goods" ? p.trade_goods : mode === "terrain" ? p.terrain : mode === "continent" ? p.continent
    : mode === "government" ? (p.owner ? info?.countries[p.owner]?.government ?? "" : "")
    : mode === "civilized" ? (p.owner ? (info?.countries[p.owner]?.civilized ? "civilised" : "uncivilised") : "") : ""), [mode, info]);
  const maxPrestige = useMemo(() => Math.max(1, ...Object.values(info?.countries ?? {}).map((c) => c.prestige)), [info]);
  const paint = useCallback((id: number, p: MapProvince): RGB => {
    if (!info) return NONE;
    if (mode === "trigger") {
      const r = results?.results[id];
      return r === true ? YES : r === false ? NO : r === null ? UNKNOWN : NONE;
    }
    if (mode === "prestige") {
      const v = p.owner ? info.countries[p.owner]?.prestige ?? 0 : -1;
      if (v < 0) return NONE;
      const t = Math.sqrt(Math.max(0, v) / maxPrestige);
      return [Math.round(235 - 40 * t), Math.round(225 - 150 * t), Math.round(150 - 130 * t)];
    }
    if (mode === "pops") {
      const t = p.pops ? Math.log(1 + p.pops) / Math.log(1 + maxPops) : 0;
      return [Math.round(240 - 200 * t), Math.round(235 - 150 * t), Math.round(200 - 60 * t)];
    }
    const k = keyOf(p);
    if (!k) return NONE;
    if (mode === "owner") return info.colors[k] ?? NONE;
    if (mode === "culture") return info.culture_colors[k] ?? hashColor(k);
    if (mode === "religion") return info.religion_colors[k] ?? hashColor(k);
    return hashColor(k);
  }, [info, mode, results, maxPops, maxPrestige, keyOf]);
  // the legend: the most common values of the mode
  const legend = useMemo(() => {
    if (!info || mode === "pops" || mode === "prestige" || mode === "trigger") return [];
    const count = new Map<string, number>();
    for (const p of Object.values(info.provinces)) if (p.land) { const k = keyOf(p); if (k) count.set(k, (count.get(k) ?? 0) + 1); }
    return [...count.entries()].sort((a, b) => b[1] - a[1]).slice(0, 24);
  }, [info, mode, keyOf]);
  const p = sel !== null ? info?.provinces[sel] : undefined;

  return (
    <div className="split-view mg-tab">
      <div className="mg-detail map-main">
        <div className="map-tools">
          <WorldSource date={date} setDate={setDate} save={save} setSave={setSave} />
          {" "}colour by <select value={mode} onChange={(e) => setMode(e.target.value as Mode)}>{MODES.map(([m, l]) => <option key={m} value={m}>{l}</option>)}</select>
          {error && <span className="creator-error"> {error}</span>}
        </div>
        <div className="map-trigger">
          <textarea className="code" rows={2} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
            placeholder="a trigger, e.g. is_core = ENG  or  owner = { civilized = no }" />
          <select value={scope} onChange={(e) => setScope(e.target.value as "province" | "owner")} title="check it in each province, or in the province's owner">
            <option value="province">in each province</option><option value="owner">in the province's owner</option></select>
          <button onClick={runTrigger}>Show where it holds</button>
          {results && mode === "trigger" && <span className="muted"> <span style={{ color: `rgb(${YES})` }}>■</span> {results.true} yes · <span style={{ color: `rgb(${NO})` }}>■</span> {results.false} no · <span style={{ color: `rgb(${UNKNOWN})` }}>■</span> {results.unknown} not known from history</span>}
        </div>
        {info && <ProvinceMap date={date} info={info} paint={paint} selected={sel !== null ? [sel] : []} onToggle={(id) => setSel(id === sel ? null : id)}
          hint="Click a province to see it; Ctrl + wheel zooms." />}
        {legend.length > 0 && (
          <div className="map-legend">{legend.map(([k, n]) => {
            const c = mode === "owner" ? info?.colors[k] : mode === "culture" ? info?.culture_colors[k] ?? hashColor(k) : mode === "religion" ? info?.religion_colors[k] ?? hashColor(k) : hashColor(k);
            return <span key={k}><span style={{ color: `rgb(${c ?? NONE})` }}>■</span> {k} <span className="muted">{n}</span></span>;
          })}</div>
        )}
      </div>
      <SidePanel id="map" side="right" initial={320} className="rw-side">
        {!p && <div className="muted pad">Click a province on the map.</div>}
        {p && sel !== null && (
          <div className="pad map-province">
            <b>#{sel} {p.name}</b>
            {detail?.file && <div><button className="mini" onClick={() => onOpen(detail.file!)}>Open {detail.file.split("/").pop()}</button></div>}
            <div>owner <b>{p.owner || "none"}</b>{p.controller && p.controller !== p.owner ? ` · controller ${p.controller}` : ""}</div>
            <div>cores {p.cores.join(" ") || "none"}</div>
            {detail && <table><tbody>{Object.entries(detail.values).map(([k, v]) => <tr key={k}><td className="muted">{k}</td><td>{v}</td></tr>)}</tbody></table>}
            {detail && detail.pops.length > 0 && (
              <>
                <div className="panel-title">Pops: {Math.round(detail.pops.reduce((a, x) => a + x.size, 0))}</div>
                <table><tbody>{detail.pops.slice(0, 30).map((x, i) => (
                  <tr key={i}><td>{x.type}</td><td className="muted">{x.culture} · {x.religion}</td><td>{x.size}</td></tr>
                ))}</tbody></table>
              </>
            )}
            {detail && detail.neighbours.length > 0 && <div className="muted">neighbours: {detail.neighbours.map((n) => (
              <span key={n} className="chip" onClick={() => setSel(n)} title={info?.provinces[n]?.name}>{n}</span>
            ))}</div>}
          </div>
        )}
      </SidePanel>
    </div>
  );
}
