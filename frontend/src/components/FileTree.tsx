import { useMemo, useState } from "react";
import type { FileEntry } from "../api";

/** Logical groups of the mod (K: "widok logiczny"), by path. */
const GROUPS: [string, (rel: string) => boolean][] = [
  ["Events", (r) => r.startsWith("events/")],
  ["Decisions", (r) => r.startsWith("decisions/")],
  ["Reforms & parties", (r) => ["common/issues.txt", "common/ideologies.txt", "common/governments.txt"].includes(r) || r.startsWith("common/countries/")],
  ["Modifiers", (r) => /^common\/(event|static|triggered)_modifiers\.txt$|^common\/(nationalvalues|crime|national_focus)\.txt$/.test(r)],
  ["Technologies & inventions", (r) => r.startsWith("technologies/") || r.startsWith("inventions/") || r === "common/technology.txt"],
  ["Pop types", (r) => r.startsWith("poptypes/") || r === "common/pop_types.txt"],
  ["Units", (r) => r.startsWith("units/")],
  ["History: countries", (r) => r.startsWith("history/countries/")],
  ["History: provinces", (r) => r.startsWith("history/provinces/")],
  ["History: other", (r) => r.startsWith("history/")],
  ["Other common", (r) => r.startsWith("common/")],
  ["Localisation", (r) => r.startsWith("localisation/")],
  ["Map & interface", (r) => r.startsWith("map/") || r.startsWith("interface/")],
];

const SCRIPT = /\.(txt|gui|gfx|csv|lua|mod|map)$/i;

interface Props {
  files: FileEntry[];
  current: string | null;
  dirty: Set<string>;
  onOpen: (rel: string) => void;
}

export function FileTree({ files, current, dirty, onOpen }: Props) {
  const [filter, setFilter] = useState("");
  const [modOnly, setModOnly] = useState(true);
  const [view, setView] = useState<"logical" | "folders">("logical");
  const [open, setOpen] = useState<Set<string>>(new Set(["Events"]));

  const groups = useMemo(() => {
    const f = filter.toLowerCase();
    const visible = files.filter(
      (e) => SCRIPT.test(e.rel) && (!modOnly || e.origin === "mod") && (!f || e.rel.toLowerCase().includes(f)),
    );
    const out = new Map<string, FileEntry[]>();
    for (const e of visible) {
      const rel = e.rel.toLowerCase();
      const name =
        view === "logical"
          ? (GROUPS.find(([, test]) => test(rel))?.[0] ?? "Other")
          : e.rel.includes("/") ? e.rel.slice(0, e.rel.lastIndexOf("/")) : "(root)";
      if (!out.has(name)) out.set(name, []);
      out.get(name)!.push(e);
    }
    const order = (name: string) => {
      const i = GROUPS.findIndex(([g]) => g === name);
      return i < 0 ? GROUPS.length : i;
    };
    return [...out.entries()].sort((a, b) =>
      view === "logical" ? order(a[0]) - order(b[0]) : a[0].localeCompare(b[0]),
    );
  }, [files, filter, modOnly, view]);

  const toggle = (name: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(name)) n.delete(name);
      else n.add(name);
      return n;
    });

  return (
    <div className="tree">
      <div className="tree-tools">
        <input placeholder="Filter files…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <label><input type="checkbox" checked={modOnly} onChange={(e) => setModOnly(e.target.checked)} /> mod files only</label>
        <select value={view} onChange={(e) => setView(e.target.value as "logical" | "folders")}>
          <option value="logical">By content</option>
          <option value="folders">By folder</option>
        </select>
      </div>
      <div className="tree-list">
        {groups.map(([name, entries]) => {
          const expanded = open.has(name) || filter.length > 1;
          return (
            <div key={name}>
              <div className="tree-group" onClick={() => toggle(name)}>
                {expanded ? "▾" : "▸"} {name} <span className="muted">({entries.length})</span>
              </div>
              {expanded &&
                entries.map((e) => (
                  <div
                    key={e.rel}
                    className={"tree-file" + (e.rel === current ? " active" : "")}
                    title={`${e.rel} (${e.origin === "mod" ? "mod" : "vanilla"})`}
                    onClick={() => onOpen(e.rel)}
                  >
                    {dirty.has(e.rel) ? "● " : ""}
                    {e.rel.slice(e.rel.lastIndexOf("/") + 1)}
                    {e.origin === "game" && <span className="badge">vanilla</span>}
                  </div>
                ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
