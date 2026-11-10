import { useEffect, useState } from "react";
import { useNav } from "../nav";
import { api } from "../api";
import { TemplateUse } from "./Templates";

/** Creators (K70): new reform (C), new ideology (D), parties for an ideology (K58). */

type Kind = "reform" | "ideology" | "parties" | "event" | "decision" | "country" | "template";

interface Result {
  diff: string;
  lines: string[];
}

interface Props {
  onStatus: (text: string) => void;
  files: string[];
  onOpen: (rel: string) => void;
}

interface OptionRow { name: string; english: string; description: string; modifiers: string }

const parseModifiers = (text: string) =>
  Object.fromEntries(
    text.split(/\n|,/).map((l) => l.trim()).filter(Boolean).map((l) => {
      const [k, v] = l.split("=").map((x) => x.trim());
      return [k, v ?? ""];
    }),
  );

export function Creators({ onStatus, files, onOpen }: Props) {
  const [kind, setKind] = useNav<Kind>("create.kind", "reform");
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
  // event / decision
  const [eFile, setEFile] = useState("");
  const [eTitle, setETitle] = useState("");
  const [eDesc, setEDesc] = useState("");
  const [eOptions, setEOptions] = useState("OK");
  const [eKind, setEKind] = useState("country_event");
  const [eTriggered, setETriggered] = useState(true);
  const [eMonths, setEMonths] = useState(12);
  const [dFile, setDFile] = useState("");
  const [dName, setDName] = useState("");
  const [dTitle, setDTitle] = useState("");
  const [dDesc, setDDesc] = useState("");
  // country
  const [cTag, setCTag] = useState("");
  const [cName, setCName] = useState("");
  const [cAdj, setCAdj] = useState("");
  const [cTemplate, setCTemplate] = useState("");
  const [cColor, setCColor] = useState("#3c8c50");
  const [cCapital, setCCapital] = useState("");
  const [cCulture, setCCulture] = useState("");
  const [cCultures, setCCultures] = useState<string | null>(null); // null = keep the template's
  const [cReligion, setCReligion] = useState("");
  const [cGovernment, setCGovernment] = useState("");
  const [cCivilized, setCCivilized] = useState<"" | "yes" | "no">("");
  const [cFlags, setCFlags] = useState(true);
  const [cProvinces, setCProvinces] = useState(""); // K76: ids that get add_core = TAG
  const [cExists, setCExists] = useState(false); // … and are owned from the start
  const [names, setNames] = useState<Record<string, string[]>>({});
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
  useEffect(() => {
    if (kind !== "country" || names.country) return;
    Promise.all(["country", "culture", "religion", "government"].map((r) => api.names(r).then((x) => [r, x.names] as const)))
      .then((all) => setNames(Object.fromEntries(all))).catch(() => undefined);
  }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps

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
      } else if (kind === "event") {
        const spec = { file: eFile, title: eTitle, description: eDesc, options: eOptions.split("\n").map((o) => o.trim()).filter(Boolean),
          kind: eKind, triggered_only: eTriggered, months: eMonths };
        const r = await api.createEvent(spec, write);
        setResult({ diff: r.diff, lines: [...r.notes, ...(r.backup ? [`backup: ${r.backup}`] : [])] });
        if (write) { onStatus(`Event created (${r.notes.join(", ")})`); onOpen(`events/${eFile}`); }
      } else if (kind === "country") {
        const spec = {
          tag: cTag, name: cName, adjective: cAdj, template: cTemplate,
          color: [1, 3, 5].map((i) => parseInt(cColor.slice(i, i + 2), 16)),
          capital: cCapital || null, primary_culture: cCulture || null,
          cultures: cCultures === null ? null : cCultures.split(/[ ,]+/).filter(Boolean),
          religion: cReligion || null, government: cGovernment || null,
          civilized: cCivilized === "" ? null : cCivilized === "yes", copy_flags: cFlags,
          provinces: cProvinces.split(/[\s,;]+/).filter(Boolean).map(Number).filter((n) => Number.isInteger(n) && n > 0),
          exists: cExists,
        };
        const r = await api.createCountry(spec, write);
        setResult({ diff: r.diff, lines: [...r.notes, `files: ${r.files.join(", ")}`, ...(r.backup ? [`backup: ${r.backup}`] : [])] });
        if (write) { onStatus(`Country ${cTag} created`); onOpen(r.files.find((f) => f.startsWith("history/")) ?? r.files[0]); }
      } else if (kind === "decision") {
        const r = await api.createDecision({ file: dFile, name: dName, title: dTitle, description: dDesc }, write);
        setResult({ diff: r.diff, lines: [...r.notes, ...(r.backup ? [`backup: ${r.backup}`] : [])] });
        if (write) { onStatus(`Decision ${dName} created`); onOpen(`decisions/${dFile}`); }
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
        {(["reform", "ideology", "parties", "event", "decision", "country", "template"] as Kind[]).map((k) => (
          <button key={k} className={kind === k ? "on" : ""} onClick={() => { setKind(k); setResult(null); setError(""); }}>
            {({ reform: "New reform", ideology: "New ideology", parties: "Parties for an ideology", event: "New event", decision: "New decision", country: "New country", template: "From a template" } as Record<Kind, string>)[k]}
          </button>
        ))}
      </div>
      {kind === "template" && <TemplateUse mode="file" files={files} onStatus={onStatus} onOpen={onOpen} />}
      {kind !== "template" && <><div className="creator-form">
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
        {kind === "event" && (
          <>
            <label>File in events/ <input list="event-files" value={eFile} onChange={(e) => setEFile(e.target.value)} placeholder="MyEvents.txt (new or existing)" /></label>
            <datalist id="event-files">{files.filter((f) => f.startsWith("events/")).map((f) => <option key={f} value={f.slice(7)} />)}</datalist>
            <label>Kind <select value={eKind} onChange={(e) => setEKind(e.target.value)}>
              <option>country_event</option><option>province_event</option>
            </select></label>
            <label>Title <input value={eTitle} onChange={(e) => setETitle(e.target.value)} /></label>
            <label>Description <textarea value={eDesc} onChange={(e) => setEDesc(e.target.value)} rows={3} /></label>
            <label>Options (one per line) <textarea value={eOptions} onChange={(e) => setEOptions(e.target.value)} rows={3} /></label>
            <label><input type="checkbox" checked={eTriggered} onChange={(e) => setETriggered(e.target.checked)} /> only fired by other events / decisions</label>
            {!eTriggered && <label>Mean time to happen (months) <input type="number" value={eMonths} onChange={(e) => setEMonths(Number(e.target.value) || 1)} /></label>}
            <div className="muted">Gets a free id (from the file's "Events N-M" header if it has one) and EVTNAME / EVTDESC / EVTOPT localisation. Fill the trigger and effects in the block view.</div>
          </>
        )}
        {kind === "decision" && (
          <>
            <label>File in decisions/ <input list="decision-files" value={dFile} onChange={(e) => setDFile(e.target.value)} placeholder="MyDecisions.txt (new or existing)" /></label>
            <datalist id="decision-files">{files.filter((f) => f.startsWith("decisions/")).map((f) => <option key={f} value={f.slice(10)} />)}</datalist>
            <label>Key <input value={dName} onChange={(e) => setDName(e.target.value)} placeholder="build_homes" /></label>
            <label>Title <input value={dTitle} onChange={(e) => setDTitle(e.target.value)} /></label>
            <label>Description <textarea value={dDesc} onChange={(e) => setDDesc(e.target.value)} rows={3} /></label>
          </>
        )}
        {kind === "country" && (
          <>
            <label>Tag <input value={cTag} onChange={(e) => setCTag(e.target.value.toUpperCase())} maxLength={3} placeholder="BOE" /></label>
            <label>English name <input value={cName} onChange={(e) => setCName(e.target.value)} placeholder="Boer Republic (also the file names)" /></label>
            <label>Adjective <input value={cAdj} onChange={(e) => setCAdj(e.target.value)} placeholder="Boer" /></label>
            <label>Copy from <input list="c-tags" value={cTemplate} onChange={(e) => setCTemplate(e.target.value.toUpperCase())} placeholder="SAF (tag of an existing country)" /></label>
            <label>Colour <input type="color" value={cColor} onChange={(e) => setCColor(e.target.value)} /></label>
            <label>Capital province <input value={cCapital} onChange={(e) => setCCapital(e.target.value)} placeholder="(the template's)" /></label>
            <label>Primary culture <input list="c-cultures" value={cCulture} onChange={(e) => setCCulture(e.target.value)} placeholder="(the template's)" /></label>
            <label><input type="checkbox" checked={cCultures === null} onChange={(e) => setCCultures(e.target.checked ? null : "")} /> keep the template's accepted cultures</label>
            {cCultures !== null && <label>Accepted cultures <input value={cCultures} onChange={(e) => setCCultures(e.target.value)} placeholder="afrikaner, british (empty = none)" /></label>}
            <label>Religion <input list="c-religions" value={cReligion} onChange={(e) => setCReligion(e.target.value)} placeholder="(the template's)" /></label>
            <label>Government <select value={cGovernment} onChange={(e) => setCGovernment(e.target.value)}>
              <option value="">(the template's)</option>
              {(names.government ?? []).map((g) => <option key={g}>{g}</option>)}
            </select></label>
            <label>Civilized <select value={cCivilized} onChange={(e) => setCCivilized(e.target.value as "" | "yes" | "no")}>
              <option value="">(the template's)</option><option value="yes">yes</option><option value="no">no</option>
            </select></label>
            <label><input type="checkbox" checked={cFlags} onChange={(e) => setCFlags(e.target.checked)} /> copy the template's flags as placeholders</label>
            <label>Provinces (cores) <input value={cProvinces} onChange={(e) => setCProvinces(e.target.value)} placeholder="ids, e.g. 2156 2157 2160"
              title="These provinces get add_core = TAG in history/provinces, so the country can be released there" /></label>
            <label><input type="checkbox" checked={cExists} onChange={(e) => setCExists(e.target.checked)} /> the country exists from the start: it also owns and controls these provinces (taken from their owner)</label>
            <datalist id="c-tags">{(names.country ?? []).map((t) => <option key={t} value={t.toUpperCase()} />)}</datalist>
            <datalist id="c-cultures">{(names.culture ?? []).map((t) => <option key={t} value={t} />)}</datalist>
            <datalist id="c-religions">{(names.religion ?? []).map((t) => <option key={t} value={t} />)}</datalist>
            <div className="muted">Makes the tag in common/countries.txt, the country file (parties renamed to the new tag), the history (without dated blocks and units), the name / adjective / party localisation and placeholder flags. The country starts without provinces: release it or create it with an event or decision.</div>
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
      )}</>}
    </div>
  );
}
