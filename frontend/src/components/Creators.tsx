import { useEffect, useState } from "react";
import { useNav } from "../nav";
import { api } from "../api";
import { TemplateUse } from "./Templates";
import { ProvinceMap } from "./ProvinceMap";
import { ChipPicker } from "./ChipPicker";
import { CodeWithPicker } from "./CodeWithPicker";

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
  const [issueTree, setIssueTree] = useState<Record<string, Record<string, string[]>>>({});
  const [countries, setCountries] = useState<{ tag: string; name: string }[]>([]);
  const [cultureGroupNames, setCultureGroupNames] = useState<string[]>([]);

  // reform
  const [category, setCategory] = useState("political_reforms");
  const [rName, setRName] = useState("");
  const [rEnglish, setREnglish] = useState("");
  const [nextStep, setNextStep] = useState(true);
  const [admin, setAdmin] = useState(false);
  // T030: the box in the reform window; the option the countries start with, and exceptions
  const [inWindow, setInWindow] = useState(true);
  const [boxAt, setBoxAt] = useState(""); // "x, y" or "" = the first free place
  const [countryDefault, setCountryDefault] = useState("");
  const [exceptions, setExceptions] = useState<{ tags: string; option: string }[]>([]);
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
  // T031: an ideology without a template, and a new group
  const [scratch, setScratch] = useState(false);
  const [newGroup, setNewGroup] = useState(""); // a key = make this group
  const [newGroupEnglish, setNewGroupEnglish] = useState("");
  const [uncivilized, setUncivilized] = useState(true);
  const [reduceMil, setReduceMil] = useState(false);
  const [weights, setWeights] = useState<Record<string, string>>({ add_political_reform: "1", remove_political_reform: "1", add_social_reform: "1", remove_social_reform: "1" });
  const [support, setSupport] = useState<Record<string, string>>({ rich: "1", middle: "1", poor: "1" });
  const [govs, setGovs] = useState<string[]>([]);
  const [governments, setGovernments] = useState<string[]>([]);
  // event / decision
  const [eFile, setEFile] = useState("");
  const [eTitle, setETitle] = useState("");
  const [eDesc, setEDesc] = useState("");
  // T033: chosen id, an id range for a new file, the trigger, options with effects and AI factor
  const [eOptions, setEOptions] = useState<{ name: string; effects: string; ai_factor: string }[]>([{ name: "OK", effects: "", ai_factor: "" }]);
  const [eId, setEId] = useState("");
  const [eRange, setERange] = useState(["", ""]);
  const [eTrigger, setETrigger] = useState("");
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
  const [cMap, setCMap] = useState(false); // @A6: choose the provinces on the map
  const idsOf = (text: string) => text.split(/[\s,;]+/).filter(Boolean).map(Number).filter((n) => Number.isInteger(n) && n > 0);
  const cChosen = idsOf(cProvinces);
  const toggleProvince = (id: number) => setCProvinces((text) => {
    const now = idsOf(text);
    return (now.includes(id) ? now.filter((x) => x !== id) : [...now, id]).join(" ");
  });
  const [names, setNames] = useState<Record<string, string[]>>({});
  // parties
  const [pIdeology, setPIdeology] = useState("");
  const [copyFrom, setCopyFrom] = useState("conservative");
  // T032: one choice per party policy (common/issues.txt party_issues); "" = copy / leave
  const [policies, setPolicies] = useState<Record<string, string>>({});
  const [tags, setTags] = useState("");
  const [cultureGroups, setCultureGroups] = useState("");
  const [civilized, setCivilized] = useState<"" | "yes" | "no">("");
  const [locText, setLocText] = useState("{adj} ");

  useEffect(() => {
    api.names("ideology").then((r) => setIdeologies(r.names)).catch(() => undefined);
    api.names("ideology_group").then((r) => setGroups(r.names)).catch(() => undefined);
    api.issueOptions().then((r) => setIssueTree(r.categories)).catch(() => undefined);
    api.countryList().then((r) => setCountries(r.countries)).catch(() => undefined);
    api.names("culture_group").then((r) => setCultureGroupNames(r.names)).catch(() => undefined);
    api.names("government").then((r) => setGovernments(r.names)).catch(() => undefined);
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
          in_window: inWindow, position: /^\s*-?\d+\s*[, ]\s*-?\d+\s*$/.test(boxAt) ? boxAt.split(/[, ]+/).filter(Boolean).map(Number) : null,
          country_default: countryDefault || null,
          country_options: Object.fromEntries(exceptions.flatMap((x) => x.option ? x.tags.split(/[\s,]+/).filter(Boolean).map((t) => [t, x.option]) : [])),
          options: options.filter((o) => o.name).map((o) => ({ ...o, modifiers: parseModifiers(o.modifiers) })),
        };
        const r = await api.createReform(spec, write);
        setResult({ diff: r.diff, lines: [...r.notes, `files: ${r.files.join(", ")}`, ...(r.backup ? [`backup: ${r.backup}`] : [])] });
        if (write) onStatus(`Reform ${rName} created`);
      } else if (kind === "ideology") {
        const c = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
        const spec = {
          name: iName, english: iEnglish, template: scratch ? null : template, group: group === "+new" ? null : group || null,
          color: c, date: date || null, new_group: group === "+new" ? newGroup : null, new_group_english: newGroupEnglish,
          uncivilized, can_reduce_militancy: reduceMil,
          reform_weights: Object.fromEntries(Object.entries(weights).map(([k, v]) => [k, Number(v) || 0])),
          support: Object.fromEntries(Object.entries(support).map(([k, v]) => [k, Number(v) || 0])), governments: govs,
        };
        const r = await api.createIdeology(spec, write);
        setResult({ diff: r.diff, lines: [...r.notes, `files: ${r.files.length}`, ...(r.backup ? [`backup: ${r.backup}`] : [])] });
        if (write) { onStatus(`Ideology ${iName} created`); setPIdeology(iName); }
      } else if (kind === "event") {
        const newFile = !files.includes(`events/${eFile}`);
        const spec = { file: eFile, title: eTitle, description: eDesc, options: eOptions.filter((o) => o.name.trim()),
          kind: eKind, triggered_only: eTriggered, months: eMonths, trigger: eTrigger,
          event_id: eId.trim() ? Number(eId) : null,
          id_range: newFile && eRange[0] && eRange[1] ? [Number(eRange[0]), Number(eRange[1])] : null };
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
          policies: Object.fromEntries(Object.entries(policies).filter(([, v]) => v)),
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
            <label title="The list in common/issues.txt: political and social reforms are in the reform window (and change with votes); economic and military ones are for uncivilised countries; party_issues are party policies">Category <select value={category} onChange={(e) => setCategory(e.target.value)}>
              {["political_reforms", "social_reforms", "economic_reforms", "military_reforms", "party_issues"].map((c) => <option key={c}>{c}</option>)}
            </select></label>
            <label title="The name in the files (lower case, no spaces); the reform window's box gets the same name">Key <input value={rName} onChange={(e) => setRName(e.target.value)} placeholder="press_rights" /></label>
            <label title="The name players see (localisation)">English name <input value={rEnglish} onChange={(e) => setREnglish(e.target.value)} placeholder="Press Rights" /></label>
            <label title="next_step_only = yes: the reform can only move one option at a time (like suffrage: no jumping from the first to the last option)"><input type="checkbox" checked={nextStep} onChange={(e) => setNextStep(e.target.checked)} /> next step only</label>
            <label title="administrative = yes (social reforms in vanilla): each option's administrative_multiplier raises the share of bureaucrats a country needs for full administrative efficiency - the more of such reforms, the more bureaucrats needed"><input type="checkbox" checked={admin} onChange={(e) => setAdmin(e.target.checked)} /> administrative</label>
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
            {(category === "political_reforms" || category === "social_reforms") && (
              <label title="Political and social reforms need a box in the reform window (interface/country_politics.gui), or players cannot see them. Automatic: the first place of the category's grid that no other box covers.">
                <input type="checkbox" checked={inWindow} onChange={(e) => setInWindow(e.target.checked)} /> add its box to the reform window at
                {" "}<input value={boxAt} onChange={(e) => setBoxAt(e.target.value)} placeholder="the first free place" size={18} disabled={!inWindow} /></label>
            )}
            <label title="The option every country starts with (written into history/countries); the game's default is the first option">Countries start with <select value={countryDefault} onChange={(e) => setCountryDefault(e.target.value)}>
              <option value="">{options[0]?.name ? `${options[0].name} (the first: the game's default)` : "(the first option)"}</option>
              {options.slice(1).filter((o) => o.name).map((o) => <option key={o.name}>{o.name}</option>)}
            </select></label>
            {exceptions.map((x, i) => (
              <div key={i} className="option-row" title="These countries start with another option">
                <ChipPicker value={x.tags} onChange={(v) => setExceptions(exceptions.map((y, j) => (j === i ? { ...y, tags: v } : y)))}
                  items={countries.map((c) => ({ name: c.tag, label: c.name }))} placeholder="search a tag or a name" />
                <select value={x.option} onChange={(e) => setExceptions(exceptions.map((y, j) => (j === i ? { ...y, option: e.target.value } : y)))}>
                  <option value="">(option)</option>
                  {options.filter((o) => o.name).map((o) => <option key={o.name}>{o.name}</option>)}
                </select>
                <button onClick={() => setExceptions(exceptions.filter((_, j) => j !== i))}>×</button>
              </div>
            ))}
            <button title="Countries that start with another option than the one above" onClick={() => setExceptions([...exceptions, { tags: "", option: "" }])}>+ countries with another option</button>
          </>
        )}
        {kind === "ideology" && (
          <>
            <label title="The name in the files (lower case, no spaces)">Key <input value={iName} onChange={(e) => setIName(e.target.value)} placeholder="christian_democrat" /></label>
            <label>English name <input value={iEnglish} onChange={(e) => setIEnglish(e.target.value)} placeholder="Christian Democrat" /></label>
            <label title="Copy an existing ideology's behaviour, or set everything here (T031)"><input type="checkbox" checked={scratch} onChange={(e) => setScratch(e.target.checked)} /> without a template (fill the fields below)</label>
            {!scratch && <label title="The new ideology starts with this one's reform preferences, support in every pop type and the governments that allow it">Copy behaviour from <select value={template} onChange={(e) => setTemplate(e.target.value)}>
              {ideologies.map((i) => <option key={i}>{i}</option>)}
            </select></label>}
            <label title="The ideology group in common/ideologies.txt (conservative, liberal, socialist …); pops move between ideologies of a group more easily">Group <select value={group} onChange={(e) => setGroup(e.target.value)}>
              <option value="">{scratch ? "(choose)" : "(same as the template)"}</option>
              {groups.map((g) => <option key={g}>{g}</option>)}
              <option value="+new">+ a new group…</option>
            </select></label>
            {group === "+new" && (
              <>
                <label title="The new group's name in the files (lower case, ends with _group by custom)">New group key <input value={newGroup} onChange={(e) => setNewGroup(e.target.value)} placeholder="agrarian_group" /></label>
                <label title="The group's name players see">New group English name <input value={newGroupEnglish} onChange={(e) => setNewGroupEnglish(e.target.value)} placeholder="Agrarians" /></label>
              </>
            )}
            {scratch && (
              <>
                <label title="uncivilized = no keeps the ideology out of uncivilised countries"><input type="checkbox" checked={uncivilized} onChange={(e) => setUncivilized(e.target.checked)} /> also in uncivilised countries</label>
                <label title="can_reduce_militancy = yes: a ruling party of this ideology lowers militancy (vanilla: conservative, liberal)"><input type="checkbox" checked={reduceMil} onChange={(e) => setReduceMil(e.target.checked)} /> can reduce militancy</label>
                <div title="How much pops of this ideology want to pass / repeal reforms (base of add_ / remove_ political / social reform; 0 = never, 1 = as much as others). Modifiers can be added later in the code.">Reform wishes (base):
                  <div className="policy-grid">{Object.keys(weights).map((k) => (
                    <label key={k} style={{ display: "contents" }}><span>{k}</span><input value={weights[k]} onChange={(e) => setWeights({ ...weights, [k]: e.target.value })} size={5} /></label>
                  ))}</div></div>
                <div title="The factor in every pop type's ideologies block, by the pop type's strata (more = more pops support it)">Support in pop types (factor):
                  <div className="policy-grid">{["rich", "middle", "poor"].map((k) => (
                    <label key={k} style={{ display: "contents" }}><span>{k} pops</span><input value={support[k]} onChange={(e) => setSupport({ ...support, [k]: e.target.value })} size={5} /></label>
                  ))}</div></div>
                <div title="common/governments.txt: under these governments a party of this ideology can rule">Governments that allow it:
                  <div className="gov-list">{governments.map((g) => (
                    <label key={g}><input type="checkbox" checked={govs.includes(g)} onChange={(e) => setGovs(e.target.checked ? [...govs, g] : govs.filter((x) => x !== g))} /> {g}</label>
                  ))}</div></div>
              </>
            )}
            <label>Colour <input type="color" value={color} onChange={(e) => setColor(e.target.value)} /></label>
            <label title="date = …: before it no pop supports the ideology (e.g. fascism from 1905)">Available from <input value={date} onChange={(e) => setDate(e.target.value)} placeholder="1870.1.1 (optional)" /></label>
            <div className="muted">{scratch ? "Writes the ideology, its support in every pop type and the chosen governments." : "Copies the template's reform preferences, its support in every pop type and the governments that allow it."} Parties come next ("Parties for an ideology").</div>
          </>
        )}
        {kind === "event" && (
          <>
            <label title="An existing file of events/ or a new name; a new file gets the 'Events N-M' header">File in events/ <input list="event-files" value={eFile} onChange={(e) => setEFile(e.target.value)} placeholder="MyEvents.txt (new or existing)" /></label>
            <datalist id="event-files">{files.filter((f) => f.startsWith("events/")).map((f) => <option key={f} value={f.slice(7)} />)}</datalist>
            <label title="country_event: happens to a country (scope: the country); province_event: to a province (scope: the province)">Kind <select value={eKind} onChange={(e) => setEKind(e.target.value)}>
              <option>country_event</option><option>province_event</option>
            </select></label>
            <label>Title <input value={eTitle} onChange={(e) => setETitle(e.target.value)} /></label>
            <label>Description <textarea value={eDesc} onChange={(e) => setEDesc(e.target.value)} rows={3} /></label>
            {eFile && !files.includes(`events/${eFile}`) && (
              <label title="A new file: the event ids it claims, written in its first line (### Events N-M used) - new events of this file take free ids from there">Ids of the new file from
                {" "}<input value={eRange[0]} onChange={(e) => setERange([e.target.value, eRange[1]])} size={8} placeholder="95000" /> to
                {" "}<input value={eRange[1]} onChange={(e) => setERange([eRange[0], e.target.value])} size={8} placeholder="95099" /></label>
            )}
            <label title="Empty: the first free id (of the file's range, or after the highest id of the mod)">Event id <input value={eId} onChange={(e) => setEId(e.target.value.replace(/\D/g, ""))} placeholder="(a free id)" size={10} /></label>
            <label title="is_triggered_only = yes: the event never happens by itself; other events or decisions fire it (country_event = id)"><input type="checkbox" checked={eTriggered} onChange={(e) => setETriggered(e.target.checked)} /> only fired by other events / decisions</label>
            {!eTriggered && <label title="mean_time_to_happen: the average waiting time once the trigger holds (modifiers can change it later)">Mean time to happen (months) <input type="number" value={eMonths} onChange={(e) => setEMonths(Number(e.target.value) || 1)} /></label>}
            {!eTriggered && <div title="trigger = { … }: when the event can happen (all conditions must hold)">Trigger
              <CodeWithPicker value={eTrigger} onChange={setETrigger} context="trigger" placeholder={"tag = ENG\nwar = no"} /></div>}
            <div title="Each option: its name, its effects (code) and how much the AI likes it (ai_chance factor)">Options</div>
            {eOptions.map((o, i) => (
              <div key={i} className="event-option">
                <div className="option-row">
                  <input value={o.name} onChange={(e) => setEOptions(eOptions.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} placeholder="Option name (English)" />
                  <input value={o.ai_factor} onChange={(e) => setEOptions(eOptions.map((x, j) => (j === i ? { ...x, ai_factor: e.target.value } : x)))}
                    placeholder="AI factor" size={8} title="ai_chance = { factor = … }: how often the AI picks it, relative to the other options (empty = the game's default)" />
                  <button onClick={() => setEOptions(eOptions.filter((_, j) => j !== i))} disabled={eOptions.length <= 1}>×</button>
                </div>
                <CodeWithPicker value={o.effects} onChange={(v) => setEOptions(eOptions.map((x, j) => (j === i ? { ...x, effects: v } : x)))} context="effect" placeholder="prestige = 5" rows={2} />
              </div>
            ))}
            <button onClick={() => setEOptions([...eOptions, { name: "", effects: "", ai_factor: "" }])}>+ option</button>
            <div className="muted">Gets the chosen id or a free one (from the file's "Events N-M" header if it has one) and EVTNAME / EVTDESC / EVTOPT localisation.</div>
          </>
        )}
        {kind === "decision" && (
          <>
            <label>File in decisions/ <input list="decision-files" value={dFile} onChange={(e) => setDFile(e.target.value)} placeholder="MyDecisions.txt (new or existing)" /></label>
            <datalist id="decision-files">{files.filter((f) => f.startsWith("decisions/")).map((f) => <option key={f} value={f.slice(10)} />)}</datalist>
            <label title="The decision's name in the files (lower case, no spaces)">Key <input value={dName} onChange={(e) => setDName(e.target.value)} placeholder="build_homes" /></label>
            <label>Title <input value={dTitle} onChange={(e) => setDTitle(e.target.value)} /></label>
            <label>Description <textarea value={dDesc} onChange={(e) => setDDesc(e.target.value)} rows={3} /></label>
          </>
        )}
        {kind === "country" && (
          <>
            <label title="Three letters or digits, the first a letter; must be new">Tag <input value={cTag} onChange={(e) => setCTag(e.target.value.toUpperCase())} maxLength={3} placeholder="BOE" /></label>
            <label>English name <input value={cName} onChange={(e) => setCName(e.target.value)} placeholder="Boer Republic (also the file names)" /></label>
            <label>Adjective <input value={cAdj} onChange={(e) => setCAdj(e.target.value)} placeholder="Boer" /></label>
            <label title="An existing country to copy: its parties, history (without dates and units), flags as placeholders">Copy from <input list="c-tags" value={cTemplate} onChange={(e) => setCTemplate(e.target.value.toUpperCase())} placeholder="SAF (tag of an existing country)" /></label>
            <label>Colour <input type="color" value={cColor} onChange={(e) => setCColor(e.target.value)} /></label>
            <label title="A province id; hover a number in the code or use the map to find one">Capital province <input value={cCapital} onChange={(e) => setCCapital(e.target.value)} placeholder="(the template's)" /></label>
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
              title="These provinces get add_core = TAG in history/provinces, so the country can be released there" />
              {" "}<button type="button" className="mini" onClick={() => setCMap(!cMap)}>{cMap ? "Hide the map" : "Choose on the map…"}</button></label>
            {cMap && <ProvinceMap selected={cChosen} onToggle={toggleProvince}
              selectedColor={cExists ? ([1, 3, 5].map((i) => parseInt(cColor.slice(i, i + 2), 16)) as [number, number, number]) : undefined}
              hint={cExists ? "The chosen provinces in the new country's colour (it owns them from the start); click to choose / drop." : undefined} />}
            <label><input type="checkbox" checked={cExists} onChange={(e) => setCExists(e.target.checked)} /> the country exists from the start: it also owns and controls these provinces (taken from their owner)</label>
            <datalist id="c-tags">{(names.country ?? []).map((t) => <option key={t} value={t.toUpperCase()} />)}</datalist>
            <datalist id="c-cultures">{(names.culture ?? []).map((t) => <option key={t} value={t} />)}</datalist>
            <datalist id="c-religions">{(names.religion ?? []).map((t) => <option key={t} value={t} />)}</datalist>
            <div className="muted">Makes the tag in common/countries.txt, the country file (parties renamed to the new tag), the history (without dated blocks and units), the name / adjective / party localisation and placeholder flags. The chosen provinces get its cores (add_core); without "exists from the start" the country appears when released or created by an event or decision.</div>
          </>
        )}
        {kind === "parties" && (
          <>
            <label title="The ideology the new parties have (one party per chosen country)">Ideology <select value={pIdeology} onChange={(e) => setPIdeology(e.target.value)}>
              <option value="">(choose)</option>
              {ideologies.map((i) => <option key={i}>{i}</option>)}
            </select></label>
            <label title="Each country's new party starts with the policies of its existing party of this ideology (if it has one); the choices below override them">Copy policies from the country's party of <select value={copyFrom} onChange={(e) => setCopyFrom(e.target.value)}>
              <option value="">(none)</option>
              {ideologies.map((i) => <option key={i}>{i}</option>)}
            </select></label>
            <div title="A party's policies: the party issues of common/issues.txt (party_issues). A choice here is the same for every new party; '(copy)' keeps what the copied party has.">
              <div>Policies of the new parties</div>
              <div className="policy-grid">{Object.entries(issueTree.party_issues ?? {}).map(([issue, opts]) => (
                <label key={issue} style={{ display: "contents" }}>
                  <span>{issue}</span>
                  <select value={policies[issue] ?? ""} onChange={(e) => setPolicies({ ...policies, [issue]: e.target.value })}>
                    <option value="">{copyFrom ? "(copy)" : "(none)"}</option>
                    {opts.map((o) => <option key={o}>{o}</option>)}
                  </select>
                </label>
              ))}</div>
            </div>
            <label title="Only these countries get the party (empty = every country that passes the other filters); search by tag or name">Only countries <ChipPicker value={tags} onChange={setTags}
              items={countries.map((c) => ({ name: c.tag, label: c.name }))} placeholder="search a tag or a name (empty = all)" /></label>
            <label title="Only countries whose primary culture is in one of these groups (common/cultures.txt)">Only culture groups <ChipPicker value={cultureGroups} onChange={setCultureGroups}
              items={cultureGroupNames.map((g) => ({ name: g }))} placeholder="search a group (empty = all)" /></label>
            <label title="Only civilised or only uncivilised countries (their history's civilized)">Civilized <select value={civilized} onChange={(e) => setCivilized(e.target.value as "" | "yes" | "no")}>
              <option value="">any</option><option value="yes">yes</option><option value="no">no</option>
            </select></label>
            <label title="The party's name in every country; {adj} becomes the country's adjective (e.g. Prussian)">English name <input value={locText} onChange={(e) => setLocText(e.target.value)} placeholder="{adj} Christian Democrats" /></label>
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
