import { useEffect, useState } from "react";
import { api } from "../api";

/** Creators (K70): new reform (C), new ideology (D), parties for an ideology (K58). */

type Kind = "reform" | "ideology" | "parties";

interface Result {
  diff: string;
  lines: string[];
}

interface Props {
  onStatus: (text: string) => void;
}

interface OptionRow { name: string; english: string; description: string; modifiers: string }

const parseModifiers = (text: string) =>
  Object.fromEntries(
    text.split(/\n|,/).map((l) => l.trim()).filter(Boolean).map((l) => {
      const [k, v] = l.split("=").map((x) => x.trim());
      return [k, v ?? ""];
    }),
  );

export function Creators({ onStatus }: Props) {
  const [kind, setKind] = useState<Kind>("reform");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [ideologies, setIdeologies] = useState<string[]>([]);
  const [groups, setGroups] = useState<string[]>([]);
  const [issues, setIssues] = useState<string[]>([]);

  // reform
  const [category, setCategory] = useState("political_reforms");
  const [rName, setRName] = useState("");
  const [rEnglish, setREnglish] = useState("");
  const [nextStep, setNextStep] = useState(true);
  const [admin, setAdmin] = useState(false);
  const [options, setOptions] = useState<OptionRow[]>([
    { name: "", english: "", description: "", modifiers: "" },
    { name: "", english: "", description: "", modifiers: "" },
  ]);
  // ideology
  const [iName, setIName] = useState("");
  const [iEnglish, setIEnglish] = useState("");
  const [template, setTemplate] = useState("conservative");
  const [group, setGroup] = useState("");
  const [color, setColor] = useState("#5060c8");
  const [date, setDate] = useState("");
  // parties
  const [pIdeology, setPIdeology] = useState("");
  const [copyFrom, setCopyFrom] = useState("conservative");
  const [policies, setPolicies] = useState("");
  const [tags, setTags] = useState("");
  const [cultureGroups, setCultureGroups] = useState("");
  const [civilized, setCivilized] = useState<"" | "yes" | "no">("");
  const [locText, setLocText] = useState("{adj} ");

  useEffect(() => {
    api.names("ideology").then((r) => setIdeologies(r.names)).catch(() => undefined);
    api.names("ideology_group").then((r) => setGroups(r.names)).catch(() => undefined);
    api.names("issue").then((r) => setIssues(r.names)).catch(() => undefined);
  }, []);

  const run = async (write: boolean) => {
    setError("");
    try {
      if (kind === "reform") {
        const spec = {
          category, name: rName, english: rEnglish, next_step_only: nextStep, administrative: admin,
          options: options.filter((o) => o.name).map((o) => ({ ...o, modifiers: parseModifiers(o.modifiers) })),
        };
        const r = await api.createReform(spec, write);
        setResult({ diff: r.diff, lines: [...r.notes, `files: ${r.files.join(", ")}`, ...(r.backup ? [`backup: ${r.backup}`] : [])] });
        if (write) onStatus(`Reform ${rName} created`);
      } else if (kind === "ideology") {
        const c = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
        const spec = { name: iName, english: iEnglish, template, group: group || null, color: c, date: date || null };
        const r = await api.createIdeology(spec, write);
        setResult({ diff: r.diff, lines: [...r.notes, `files: ${r.files.length}`, ...(r.backup ? [`backup: ${r.backup}`] : [])] });
        if (write) { onStatus(`Ideology ${iName} created`); setPIdeology(iName); }
      } else {
        const body = {
          ideology: pIdeology, copy_from: copyFrom ? [copyFrom] : [],
          policies: parseModifiers(policies),
          tags: tags ? tags.split(/[ ,]+/).filter(Boolean) : null,
          culture_groups: cultureGroups ? cultureGroups.split(/[ ,]+/).filter(Boolean) : null,
          civilized: civilized === "" ? null : civilized === "yes",
          loc_text: locText.trim() ? locText : null,
        };
        const r = await api.parties(body, write);
        const skipped = Object.entries(r.skipped).map(([t, why]) => `skipped ${t}: ${why}`);
        setResult({ diff: r.diff, lines: [`${r.created.length} parties: ${r.created.join(" ")}`, ...skipped.slice(0, 30), ...(r.backup ? [`backup: ${r.backup}`] : [])] });
        if (write) onStatus(`${r.created.length} parties created`);
      }
    } catch (e) {
      setError((e as Error).message);
      setResult(null);
    }
  };

  const setOption = (i: number, patch: Partial<OptionRow>) =>
    setOptions(options.map((o, j) => (j === i ? { ...o, ...patch } : o)));

  return (
    <div className="creators">
      <div className="rw-tools">
        <b>Create</b>
        {(["reform", "ideology", "parties"] as Kind[]).map((k) => (
          <button key={k} className={kind === k ? "on" : ""} onClick={() => { setKind(k); setResult(null); setError(""); }}>
            {k === "reform" ? "New reform" : k === "ideology" ? "New ideology" : "Parties for an ideology"}
          </button>
        ))}
      </div>
      <div className="creator-form">
        {kind === "reform" && (
          <>
            <label>Category <select value={category} onChange={(e) => setCategory(e.target.value)}>
              {["political_reforms", "social_reforms", "economic_reforms", "military_reforms", "party_issues"].map((c) => <option key={c}>{c}</option>)}
            </select></label>
            <label>Key <input value={rName} onChange={(e) => setRName(e.target.value)} placeholder="press_rights" /></label>
            <label>English name <input value={rEnglish} onChange={(e) => setREnglish(e.target.value)} placeholder="Press Rights" /></label>
            <label><input type="checkbox" checked={nextStep} onChange={(e) => setNextStep(e.target.checked)} /> next step only</label>
            <label><input type="checkbox" checked={admin} onChange={(e) => setAdmin(e.target.checked)} /> administrative</label>
            <div className="muted">Options (the first is the default). Modifiers: one <code>key = value</code> per line.</div>
            {options.map((o, i) => (
              <div key={i} className="option-row">
                <input value={o.name} onChange={(e) => setOption(i, { name: e.target.value })} placeholder="option_key" />
                <input value={o.english} onChange={(e) => setOption(i, { english: e.target.value })} placeholder="English name" />
                <input value={o.description} onChange={(e) => setOption(i, { description: e.target.value })} placeholder="Description (optional)" />
                <textarea value={o.modifiers} onChange={(e) => setOption(i, { modifiers: e.target.value })} placeholder="global_pop_militancy_modifier = -0.01" rows={2} />
                <button onClick={() => setOptions(options.filter((_, j) => j !== i))} disabled={options.length <= 2}>×</button>
              </div>
            ))}
            <button onClick={() => setOptions([...options, { name: "", english: "", description: "", modifiers: "" }])}>+ option</button>
            <div className="muted">Political and social reforms also get a box in the reform window (move it there later).</div>
          </>
        )}
        {kind === "ideology" && (
          <>
            <label>Key <input value={iName} onChange={(e) => setIName(e.target.value)} placeholder="christian_democrat" /></label>
            <label>English name <input value={iEnglish} onChange={(e) => setIEnglish(e.target.value)} placeholder="Christian Democrat" /></label>
            <label>Copy behaviour from <select value={template} onChange={(e) => setTemplate(e.target.value)}>
              {ideologies.map((i) => <option key={i}>{i}</option>)}
            </select></label>
            <label>Group <select value={group} onChange={(e) => setGroup(e.target.value)}>
              <option value="">(same as the template)</option>
              {groups.map((g) => <option key={g}>{g}</option>)}
            </select></label>
            <label>Colour <input type="color" value={color} onChange={(e) => setColor(e.target.value)} /></label>
            <label>Available from <input value={date} onChange={(e) => setDate(e.target.value)} placeholder="1870.1.1 (optional)" /></label>
            <div className="muted">Copies the template's reform preferences, its support in every pop type and the governments that allow it. Parties come next ("Parties for an ideology").</div>
          </>
        )}
        {kind === "parties" && (
          <>
            <label>Ideology <select value={pIdeology} onChange={(e) => setPIdeology(e.target.value)}>
              <option value="">(choose)</option>
              {ideologies.map((i) => <option key={i}>{i}</option>)}
            </select></label>
            <label>Copy policies from the country's party of <select value={copyFrom} onChange={(e) => setCopyFrom(e.target.value)}>
              <option value="">(none)</option>
              {ideologies.map((i) => <option key={i}>{i}</option>)}
            </select></label>
            <label>Fixed policies <textarea value={policies} onChange={(e) => setPolicies(e.target.value)} rows={3}
              placeholder={`religious_policy = moralism\n(party issues: ${issues.slice(0, 5).join(", ")})`} /></label>
            <label>Only tags <input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="PRU, AUS (empty = all)" /></label>
            <label>Only culture groups <input value={cultureGroups} onChange={(e) => setCultureGroups(e.target.value)} placeholder="germanic (empty = all)" /></label>
            <label>Civilized <select value={civilized} onChange={(e) => setCivilized(e.target.value as "" | "yes" | "no")}>
              <option value="">any</option><option value="yes">yes</option><option value="no">no</option>
            </select></label>
            <label>English name <input value={locText} onChange={(e) => setLocText(e.target.value)} placeholder="{adj} Christian Democrats" /></label>
          </>
        )}
        <div className="creator-buttons">
          <button onClick={() => run(false)}>Preview changes</button>
          <button onClick={() => run(true)} disabled={!result}>Create (write files)</button>
        </div>
        {error && <div className="creator-error">{error}</div>}
      </div>
      {result && (
        <div className="creator-result">
          {result.lines.map((l, i) => <div key={i} className="muted">{l}</div>)}
          <pre>{result.diff || "(no changes)"}</pre>
        </div>
      )}
    </div>
  );
}
