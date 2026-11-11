import { useState } from "react";

/**
 * Choose several names by searching (T032): type part of a tag or a name, pick from the list,
 * the chosen ones show as chips (× drops one). The value is the names separated by spaces.
 */
export function ChipPicker({ value, onChange, items, placeholder, title }: {
  value: string; onChange: (v: string) => void;
  /** What can be chosen: the name written into the file and a label to search too. */
  items: { name: string; label?: string }[];
  placeholder?: string; title?: string;
}) {
  const [query, setQuery] = useState("");
  const chosen = value.split(/[\s,]+/).filter(Boolean);
  const q = query.trim().toLowerCase();
  // best first: the exact name, then names / labels starting with the text, then the rest
  const score = (i: { name: string; label?: string }) => {
    const n = i.name.toLowerCase(), l = (i.label ?? "").toLowerCase();
    return n === q ? 0 : n.startsWith(q) ? 1 : l.startsWith(q) || l.includes(` ${q}`) ? 2 : 3;
  };
  const found = q ? items.filter((i) => !chosen.includes(i.name) && (i.name.toLowerCase().includes(q) || (i.label ?? "").toLowerCase().includes(q)))
    .sort((a, b) => score(a) - score(b) || a.name.localeCompare(b.name)).slice(0, 12) : [];
  const add = (name: string) => { onChange([...chosen, name].join(" ")); setQuery(""); };
  return (
    <span className="chip-picker" title={title}>
      {chosen.map((c) => {
        const label = items.find((i) => i.name === c)?.label;
        return <span key={c} className="chip">{c}{label ? ` · ${label}` : ""} <span className="chip-x" onClick={() => onChange(chosen.filter((x) => x !== c).join(" "))}>×</span></span>;
      })}
      <span className="chip-search">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={chosen.length ? "add…" : placeholder}
          onKeyDown={(e) => { if (e.key === "Enter" && found[0]) { e.preventDefault(); add(found[0].name); } }} />
        {found.length > 0 && (
          <span className="chip-list">{found.map((i) => (
            <span key={i.name} className="row" onMouseDown={(e) => { e.preventDefault(); add(i.name); }}>{i.name}{i.label ? <span className="muted"> · {i.label}</span> : null}</span>
          ))}</span>
        )}
      </span>
    </span>
  );
}
