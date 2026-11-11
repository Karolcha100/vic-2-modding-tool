import { useEffect, useState } from "react";
import { api } from "../api";

type Kind = "trigger" | "effect" | "modifier";
type Entry = { name: string; doc: string; groups: string[] };
const cache: Partial<Record<Kind, Entry[]>> = {};
const LABEL: Record<Kind, string> = { trigger: "conditions", effect: "effects", modifier: "modifiers" };

/**
 * A box of script code with a search of the schema's triggers, effects or modifiers (T033,
 * T030): choose what to search, filter by scope (triggers / effects) or subject (modifiers),
 * and a picked name is added as a line `name = ` to finish by hand.
 */
export function CodeWithPicker({ value, onChange, kinds, placeholder, rows = 3, title }: {
  value: string; onChange: (v: string) => void; kinds: Kind[]; placeholder?: string; rows?: number; title?: string;
}) {
  const [kind, setKind] = useState<Kind>(kinds[0]);
  const [list, setList] = useState<Entry[]>(cache[kinds[0]] ?? []);
  const [group, setGroup] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    setGroup("");
    if (cache[kind]) { setList(cache[kind]!); return; }
    api.commandList(kind).then((r) => { cache[kind] = r.commands; setList(r.commands); }).catch(() => undefined);
  }, [kind]);
  const groups = [...new Set(list.flatMap((c) => c.groups))].sort();
  const q = query.trim().toLowerCase();
  const found = q || group
    ? list.filter((c) => (!group || c.groups.includes(group) || c.groups.includes("any"))
      && (!q || c.name.toLowerCase().includes(q) || c.doc.toLowerCase().includes(q)))
      .sort((a, b) => Number(!a.name.toLowerCase().startsWith(q)) - Number(!b.name.toLowerCase().startsWith(q)) || a.name.localeCompare(b.name))
      .slice(0, 40)
    : [];
  const add = (name: string) => {
    const sep = value && !value.endsWith("\n") ? "\n" : "";
    onChange(`${value}${sep}${name} = `);
    setQuery("");
  };
  return (
    <span className="code-picker" title={title}>
      <span className="code-picker-bar">
        {kinds.length > 1
          ? <select value={kind} onChange={(e) => setKind(e.target.value as Kind)} title="what to search">{kinds.map((k) => <option key={k} value={k}>{LABEL[k]}</option>)}</select>
          : <span className="muted">{LABEL[kind]}:</span>}
        <select value={group} onChange={(e) => setGroup(e.target.value)} title={kind === "modifier" ? "subject of the modifier" : "the scope it works in"}>
          <option value="">{kind === "modifier" ? "any subject" : "any scope"}</option>
          {groups.filter((g) => g !== "any").map((g) => <option key={g}>{g}</option>)}
        </select>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`search ${LABEL[kind]}…`}
          onKeyDown={(e) => { if (e.key === "Enter" && found[0]) { e.preventDefault(); add(found[0].name); } }} />
        {(q || group) && <button type="button" className="mini" onClick={() => { setQuery(""); setGroup(""); }} title="close the list">×</button>}
      </span>
      {found.length > 0 && (
        <span className="code-picker-list">{found.map((c) => (
          <span key={c.name} className="row" title={c.doc} onMouseDown={(e) => { e.preventDefault(); add(c.name); }}>{c.name}<span className="muted"> · {c.doc}</span></span>
        ))}</span>
      )}
      <textarea className="code" value={value} onChange={(e) => onChange(e.target.value)} rows={rows} spellCheck={false} placeholder={placeholder} />
    </span>
  );
}
