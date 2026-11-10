import { useEffect, useMemo, useState } from "react";
import { api, type MetaInfo, type MetaPlan, type MetaRule, type ModGroup } from "../api";
import { useNav } from "../nav";
import { GroupEditor, groupSummary } from "./ModGroups";

/**
 * Meta relations (T010): a rule written once ("with conscription, poor pops promote more to soldiers")
 * that the tool copies into every matching pop file between marker comments. The modifiers are
 * written in one code box; groups of them (steps of one number) open in the chart editor.
 */

const EMPTY: MetaRule = { name: "", block: "promote_to", target: "", description: "", strata: [], pop_types: [], group: false, modifiers: "modifier = {\n\tfactor = 2\n\t\n}" };

export function MetaRelations({ onStatus, focus }: { onStatus: (t: string) => void; focus?: string | null }) {
  const [info, setInfo] = useState<MetaInfo | null>(null);
  const [selName, setSelName] = useNav<string | null>("meta.sel", focus ?? null);
  const [rule, setRule] = useState<MetaRule>(EMPTY);
  const [isNew, setIsNew] = useState(true);
  const [groups, setGroups] = useState<ModGroup[]>([]);
  const [editing, setEditing] = useState<ModGroup | null>(null);
  const [result, setResult] = useState<MetaPlan | null>(null);
  const [force, setForce] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api.meta().then(setInfo).catch((e) => setError((e as Error).message));
  useEffect(() => { load(); }, []);
  useEffect(() => { if (focus) setSelName(focus); }, [focus]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!info) return;
    const r = info.rules.find((x) => x.name === selName);
    // The "by strata" choice is gone (T010, 07:02): a rule that has one gets its pop types by name.
    const fromStrata = r ? Object.entries(info.pops).filter(([, st]) => r.strata.includes(st)).map(([p]) => p) : [];
    const pops = r ? [...new Set([...r.pop_types, ...fromStrata])].filter((p) => !(r.block === "promote_to" && p === r.target)) : [];
    setRule(r ? { ...r, strata: [], pop_types: pops } : { ...EMPTY }); setIsNew(!r); setResult(null); setError(""); setEditing(null);
  }, [info, selName]);
  // Groups in the code box (e.g. num_of_cities = 20 / 30 / 50): edited as a function.
  useEffect(() => {
    const t = window.setTimeout(() => {
      api.codeGroups(rule.modifiers, rule.block, rule.target).then((r) => setGroups(r.groups)).catch(() => setGroups([]));
    }, 400);
    return () => window.clearTimeout(t);
  }, [rule.modifiers, rule.block, rule.target]);

  const pops = info?.pops ?? {};
  const isChance = info?.blocks.chance.includes(rule.block) ?? false;
  const needsTarget = ["promote_to", "issues", "ideologies"].includes(rule.block);
  const targetNames = rule.block === "promote_to" ? info?.names.pop_type : rule.block === "issues" ? info?.names.issue_option : rule.block === "ideologies" ? info?.names.ideology : undefined;
  const goesInto = useMemo(() => {
    if (isChance) return ["common/pop_types.txt"];
    const wanted = new Set(rule.pop_types.map((p) => p.toLowerCase()));
    return Object.entries(pops).filter(([p, s]) => ((!rule.strata.length && !wanted.size) || rule.strata.includes(s) || wanted.has(p.toLowerCase()))
      && !(rule.block === "promote_to" && p.toLowerCase() === rule.target.toLowerCase())).map(([p]) => p);
  }, [pops, rule, isChance]);

  // From the highest class down: rich, middle, poor (then by name).
  const RANK: Record<string, number> = { rich: 0, middle: 1, poor: 2 };
  const sortedPops = Object.entries(pops).sort(([a, sa], [b, sb]) => (RANK[sa] ?? 3) - (RANK[sb] ?? 3) || a.localeCompare(b));
  const set = (patch: Partial<MetaRule>) => { setRule({ ...rule, ...patch }); setResult(null); };
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  const run = async (write: boolean, del = false) => {
    if (write && !window.confirm(del ? `Delete the rule "${rule.name}" and its copies in the pop files? A backup is made first.` : "Write the rule and update the pop files? A backup is made first.")) return;
    setBusy(true); setError("");
    try {
      const body = del ? { delete: true, name: selName ?? rule.name } : { rule, old_name: isNew ? undefined : selName ?? undefined };
      const r = await api.metaPlan({ ...body, force, write });
      setResult(r);
      if (r.written) {
        onStatus(`Meta relations: ${r.files.length} file(s) written; backup: ${r.backup ?? "-"}`);
        await load();
        setSelName(del ? null : rule.name);
      }
    } catch (e) { setError((e as Error).message); }
    setBusy(false);
  };

  if (!info) return <div className="muted pad">{error || "Loading the meta relations…"}</div>;
  return (
    <div className="split-view mg-tab">
      <div className="mg-list">
        <button onClick={() => setSelName(null)}>+ New rule</button>
        <div className="mg-items">
          {info.rules.map((r) => (
            <div key={r.name} className={`row${selName === r.name ? " on" : ""}`} onClick={() => setSelName(r.name)} title={r.description}>
              <b>{r.name}</b> <span className="muted">{r.block}{r.target ? ` → ${r.target}` : ""} · {r.pops?.length ?? 0} pops</span>
            </div>
          ))}
          {!info.rules.length && <div className="muted pad">No rules yet. A rule is kept in {info.folder}/ in the mod (the game does not read that folder).</div>}
        </div>
      </div>
      <div className="mg-detail">
        <div className="creator-form meta-form">
          <b>{isNew ? "New rule" : `Rule ${selName}`}</b>
          <label>Name <input value={rule.name} onChange={(e) => set({ name: e.target.value })} placeholder="conscription_poor_to_soldiers" /></label>
          <label>Description <input value={rule.description} onChange={(e) => set({ description: e.target.value })} /></label>
          <label>Block <select value={rule.block} onChange={(e) => set({ block: e.target.value })}>
            <optgroup label="poptypes/<pop>.txt">{info.blocks.pop.map((b) => <option key={b}>{b}</option>)}</optgroup>
            <optgroup label="common/pop_types.txt">{info.blocks.chance.map((b) => <option key={b}>{b}</option>)}</optgroup>
          </select></label>
          {needsTarget && rule.block !== "promote_to" && (
            <label>Target <input list="meta-targets" value={rule.target} onChange={(e) => set({ target: e.target.value })}
              placeholder={rule.block === "promote_to" ? "soldiers" : rule.block === "issues" ? "an issue option" : "an ideology"} />
              <datalist id="meta-targets">{(targetNames ?? []).map((n) => <option key={n} value={n} />)}</datalist></label>
          )}
          {!isChance && (
            <>
              <table className="meta-pops">
                <thead><tr><th>pop type</th><th title="the rule goes into these pop files">source</th>{rule.block === "promote_to" && <th title="they promote to this pop type">target</th>}</tr></thead>
                <tbody>
                  {sortedPops.map(([p, st]) => (
                    <tr key={p} className={`strata-${st}`}>
                      <td>{p} <span className="muted">({st})</span></td>
                      <td><input type="checkbox" checked={rule.pop_types.includes(p)} disabled={rule.block === "promote_to" && rule.target === p}
                        onChange={() => set({ pop_types: toggle(rule.pop_types, p) })} /></td>
                      {rule.block === "promote_to" && (
                        <td><input type="radio" name="meta-target" checked={rule.target === p}
                          onChange={() => set({ target: p, pop_types: rule.pop_types.filter((x) => x !== p) })} /></td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <div className="muted">Goes into: {goesInto.length ? goesInto.join(", ") : "nothing yet"}{!rule.pop_types.length && !isChance ? " (no source ticked = all pop types)" : ""}</div>
          <label><input type="checkbox" checked={rule.group} onChange={(e) => set({ group: e.target.checked })} /> put the modifiers inside one <code>group = {"{ }"}</code></label>
          <div className="meta-code">Modifiers (the code, written once; goes into every pop above)
            <textarea className="code" spellCheck={false} value={rule.modifiers} onChange={(e) => set({ modifiers: e.target.value })} rows={10} /></div>
          {groups.map((g) => (
            <div key={g.id} className="row">group: {groupSummary(g)} <button className="mini" onClick={() => setEditing(g)}>Edit as function</button></div>
          ))}
          {editing && (
            <div className="card">
              <GroupEditor group={editing} applyLabel="Put into the code box" onCancel={() => setEditing(null)}
                onApply={async (rows) => {
                  const r = await api.codeGroupEdit(rule.modifiers, rule.block, rule.target, editing.id, rows);
                  set({ modifiers: r.text }); setEditing(null);
                }} />
            </div>
          )}
          <label><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> also overwrite copies changed by hand</label>
          <div className="creator-buttons">
            <button disabled={busy} onClick={() => run(false)}>Preview changes</button>
            <button disabled={busy || !result} onClick={() => run(true)}>Apply (write rule and pop files)</button>
            {!isNew && <button disabled={busy} onClick={() => run(true, true)}>Delete rule</button>}
          </div>
          {error && <div className="creator-error">{error}</div>}
        </div>
        {result && (
          <div className="creator-result">
            {result.backup && <div className="muted">backup: {result.backup}</div>}
            <div>{result.added.length} added, {result.updated.length} updated, {result.removed.length} removed{result.files.length ? ` in ${result.files.length} file(s)` : ""}</div>
            {result.edited.map(([n, f]) => <div key={n + f} className="problem">copy of {n} in {f} was changed by hand: kept (tick "also overwrite" to replace it)</div>)}
            {result.missing.map(([n, f, why]) => <div key={n + f} className="muted">{n} cannot go into {f}: {why}</div>)}
            <pre>{result.diff}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
