import { useEffect, useMemo, useState } from "react";
import { api, type TemplateFill, type TemplateInfo } from "../api";

/** Templates (K39 = B): built-in and own; fill the fields, append to a file or insert at the cursor. */

interface UseProps {
  /** "file": append to a mod file (Create view); "cursor": insert into the open editor. */
  mode: "file" | "cursor";
  files?: string[];
  onStatus: (text: string) => void;
  onOpen?: (rel: string) => void;
  onInsert?: (text: string) => void;
  onClose?: () => void;
}

const TYPE_HINT: Record<string, string> = {
  text: "text", int: "number", name: "name (no spaces)", bool: "yes / no", event_id: "event id (free one proposed)",
};

export function TemplateUse({ mode, files = [], onStatus, onOpen, onInsert, onClose }: UseProps) {
  const [list, setList] = useState<TemplateInfo[]>([]);
  const [dir, setDir] = useState("");
  const [id, setId] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [choices, setChoices] = useState<Record<string, string[]>>({});
  const [file, setFile] = useState("");
  const [result, setResult] = useState<TemplateFill | null>(null);
  const [error, setError] = useState("");

  const reload = () => api.templates().then((r) => { setList(r.templates); setDir(r.dir); }).catch((e) => setError((e as Error).message));
  useEffect(() => { reload(); }, []);
  const tpl = useMemo(() => list.find((t) => t.id === id) ?? null, [list, id]);

  const choose = async (tid: string) => {
    setId(tid); setResult(null); setError("");
    const t = list.find((x) => x.id === tid);
    if (!t) return;
    const target = t.folder ? `${t.folder}/` : "";
    setFile(target);
    try {
      const r = await api.templateValues(tid);
      setValues(r.defaults); setChoices(r.choices);
    } catch (e) { setError((e as Error).message); }
  };

  // Free event ids depend on the target file's "Events N-M" header.
  const refreshIds = async (target: string) => {
    if (!tpl || !tpl.fields.some((f) => f.type === "event_id")) return;
    try {
      const r = await api.templateValues(tpl.id, target.endsWith(".txt") ? target : "");
      setValues((v) => ({ ...v, ...Object.fromEntries(tpl.fields.filter((f) => f.type === "event_id").map((f) => [f.name, r.defaults[f.name]])) }));
    } catch { /* keep the old ids */ }
  };

  const run = async (write: boolean) => {
    if (!tpl) return;
    setError("");
    try {
      const r = await api.templateFill({ id: tpl.id, values, file: mode === "file" ? file : null, write });
      setResult(r);
      if (write) {
        if (mode === "file") { onStatus(`Template "${tpl.name}" written to ${file}`); onOpen?.(file); }
        else { onInsert?.(r.text); onStatus(`Template "${tpl.name}" inserted${r.files.length ? ` (localisation written: ${r.files.join(", ")})` : ""} - not saved yet`); onClose?.(); }
      }
    } catch (e) { setError((e as Error).message); setResult(null); }
  };

  const remove = async () => {
    if (!tpl || tpl.builtin || !window.confirm(`Delete your template "${tpl.name}"?`)) return;
    await api.templateDelete(tpl.id);
    setId(""); reload();
  };

  return (
    <div className="template-use">
      <div className="creator-form">
        <label>Template <select value={id} onChange={(e) => choose(e.target.value)}>
          <option value="">(choose)</option>
          <optgroup label="Built-in">{list.filter((t) => t.builtin).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</optgroup>
          <optgroup label="Your templates">{list.filter((t) => !t.builtin).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</optgroup>
        </select></label>
        {!tpl && <div className="muted">Your own templates: select code in the editor → right click → "Save selection as template". They are kept in {dir}.</div>}
        {tpl && (
          <>
            {tpl.description && <div className="muted">{tpl.description}</div>}
            {mode === "file" && (
              <>
                <label>File in the mod <input list="tpl-files" value={file} onChange={(e) => setFile(e.target.value)} onBlur={() => refreshIds(file)} placeholder="events/MyEvents.txt (new or existing)" /></label>
                <datalist id="tpl-files">{files.filter((f) => !tpl.folder || f.startsWith(tpl.folder + "/")).map((f) => <option key={f} value={f} />)}</datalist>
              </>
            )}
            {tpl.fields.map((f) => (
              <label key={f.name}>{f.name} <span className="muted">({f.type.startsWith("ref:") ? f.type.slice(4) : TYPE_HINT[f.type] ?? f.type})</span>
                {f.type === "bool" ? (
                  <select value={values[f.name] ?? "yes"} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}><option>yes</option><option>no</option></select>
                ) : (
                  <input list={choices[f.name] ? `tpl-${f.name}` : undefined} value={values[f.name] ?? ""} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
                )}
                {choices[f.name] && <datalist id={`tpl-${f.name}`}>{choices[f.name].slice(0, 2000).map((c) => <option key={c} value={c} />)}</datalist>}
              </label>
            ))}
            <div className="creator-buttons">
              <button onClick={() => run(false)}>Preview</button>
              <button onClick={() => run(true)} disabled={!result}>{mode === "file" ? "Create (write files)" : "Insert at the cursor"}</button>
              {!tpl.builtin && <button onClick={remove}>Delete template</button>}
              {onClose && <button onClick={onClose}>Cancel</button>}
            </div>
          </>
        )}
        {error && <div className="creator-error">{error}</div>}
      </div>
      {result && (
        <div className="creator-result">
          {result.notes.map((l, i) => <div key={i} className="muted">{l}</div>)}
          {result.backup && <div className="muted">backup: {result.backup}</div>}
          {mode === "cursor" && <pre>{result.text}</pre>}
          {result.diff && <pre>{result.diff}</pre>}
        </div>
      )}
    </div>
  );
}

interface SaveProps { text: string; folder: string; onStatus: (text: string) => void; onClose: () => void }

/** Remove the common leading indentation of the selected lines. */
function dedent(text: string): string {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const indents = lines.filter((l) => l.trim()).map((l) => /^[\t ]*/.exec(l)![0]);
  let common = indents[0] ?? "";
  for (const i of indents) while (!i.startsWith(common)) common = common.slice(0, -1);
  return lines.map((l) => (l.startsWith(common) ? l.slice(common.length) : l)).join("\n").trim() + "\n";
}

export function TemplateSave({ text, folder, onStatus, onClose }: SaveProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [dir, setDir] = useState(folder);
  const [body, setBody] = useState(() => dedent(text));
  const [loc, setLoc] = useState("");
  const [field, setField] = useState("");
  const [error, setError] = useState("");
  const [area, setArea] = useState<HTMLTextAreaElement | null>(null);

  // Turn the text selected in the code box into a field: every copy becomes {{field}},
  // the first one keeps it as the default value.
  const makeField = () => {
    if (!area || !field.match(/^[A-Za-z_][A-Za-z0-9_]*$/)) { setError("Select text in the code box and give the field a name (letters, digits, _)."); return; }
    const picked = body.slice(area.selectionStart, area.selectionEnd);
    if (!picked) { setError("Select the text that should become a field first."); return; }
    const parts = body.split(picked);
    setBody(parts[0] + `{{${field}=${picked}}}` + parts.slice(1).join(`{{${field}}}`));
    setLoc(loc.split(picked).join(`{{${field}}}`));
    setField(""); setError("");
  };

  const saveIt = async () => {
    try {
      const r = await api.templateSave({ name, body, description, folder: dir, loc: loc.split("\n").filter((l) => l.trim()) });
      onStatus(`Template saved (${r.id})`);
      onClose();
    } catch (e) { setError((e as Error).message); }
  };

  return (
    <div className="creator-form">
      <b>Save selection as template</b>
      <label>Name <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Flavour event for a tag" /></label>
      <label>Description <input value={description} onChange={(e) => setDescription(e.target.value)} /></label>
      <label>Folder <input value={dir} onChange={(e) => setDir(e.target.value)} placeholder="events" /></label>
      <label>Code <textarea ref={setArea} className="code" value={body} onChange={(e) => setBody(e.target.value)} rows={12} /></label>
      <div className="option-row">
        <input value={field} onChange={(e) => setField(e.target.value)} placeholder="field name, e.g. tag" />
        <button onClick={makeField}>Make field from the selected text</button>
      </div>
      <div className="muted">Fields: <code>{"{{name}}"}</code>, with a type <code>{"{{id:event_id}}"}</code>, <code>{"{{n:int=5}}"}</code>, <code>{"{{tag:ref:country}}"}</code> (types: text, int, name, bool, event_id, ref:&lt;registry&gt;).</div>
      <label>Localisation (optional, one <code>KEY = English text</code> per line) <textarea value={loc} onChange={(e) => setLoc(e.target.value)} rows={3} placeholder={"EVTNAME{{id}} = {{title}}"} /></label>
      <div className="creator-buttons">
        <button onClick={saveIt} disabled={!name.trim()}>Save template</button>
        <button onClick={onClose}>Cancel</button>
      </div>
      {error && <div className="creator-error">{error}</div>}
    </div>
  );
}
