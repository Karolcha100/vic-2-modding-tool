import { useEffect, useState } from "react";
import { api } from "../api";

const cache: Record<string, { name: string; doc: string }[]> = {};

/**
 * A box of script code with a search of the schema's triggers or effects (T033): picking one
 * adds a line `name = ` at the end, to be finished by hand (hover the name in the editor later
 * for its full description).
 */
export function CodeWithPicker({ value, onChange, context, placeholder, rows = 3 }: {
  value: string; onChange: (v: string) => void; context: "trigger" | "effect"; placeholder?: string; rows?: number;
}) {
  const [list, setList] = useState(cache[context] ?? []);
  const [query, setQuery] = useState("");
  useEffect(() => {
    if (cache[context]) return;
    api.commandList(context).then((r) => { cache[context] = r.commands; setList(r.commands); }).catch(() => undefined);
  }, [context]);
  const q = query.trim().toLowerCase();
  const found = q ? list.filter((c) => c.name.toLowerCase().includes(q) || c.doc.toLowerCase().includes(q)).slice(0, 14) : [];
  const add = (name: string) => {
    const sep = value && !value.endsWith("\n") ? "\n" : "";
    onChange(`${value}${sep}${name} = `);
    setQuery("");
  };
  return (
    <span className="code-picker">
      <textarea className="code" value={value} onChange={(e) => onChange(e.target.value)} rows={rows} spellCheck={false} placeholder={placeholder} />
      <span className="chip-search">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`+ add ${context === "trigger" ? "a condition" : "an effect"} (search)…`}
          onKeyDown={(e) => { if (e.key === "Enter" && found[0]) { e.preventDefault(); add(found[0].name); } }} />
        {found.length > 0 && (
          <span className="chip-list">{found.map((c) => (
            <span key={c.name} className="row" title={c.doc} onMouseDown={(e) => { e.preventDefault(); add(c.name); }}>{c.name}<span className="muted"> · {c.doc}</span></span>
          ))}</span>
        )}
      </span>
    </span>
  );
}
