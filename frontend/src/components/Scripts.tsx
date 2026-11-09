import { useEffect, useMemo, useState } from "react";
import { api, type ScriptInfo, type ScriptRun } from "../api";

/**
 * Light Python scripts (T007): built-in and own ones, fields, a code box,
 * Preview (output + diff, nothing written) and Apply (write with a backup).
 */

interface Props {
  readOnly: boolean;
  onStatus: (text: string) => void;
  onOpen: (rel: string) => void;
}

const NEW_SCRIPT = `#@ name: My script
#@ description: What the script does.
#@ param: files = events/*.txt | which files (* also crosses folders)
#@ param: old | text to find
#@ param: new | what to put instead

# mod.files(pattern), mod.read(rel), mod.write(rel, text), mod.replace(old, new, files=..., regex=False),
# mod.find(text, files=...), mod.document(rel) (syntax tree), mod.names("country"); print() shows in Output.
count = mod.replace(params["old"], params["new"], files=params["files"])
print(count, "replacement(s)")
`;

export function Scripts({ readOnly, onStatus, onOpen }: Props) {
  const [list, setList] = useState<ScriptInfo[]>([]);
  const [dir, setDir] = useState("");
  const [id, setId] = useState("");
  const [code, setCode] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ScriptRun | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const reload = async (select?: string) => {
    try {
      const r = await api.scripts();
      setList(r.scripts); setDir(r.dir);
      if (select) pick(select, r.scripts);
    } catch (e) { setError((e as Error).message); }
  };
  useEffect(() => { reload(); }, []);
  const script = useMemo(() => list.find((s) => s.id === id) ?? null, [list, id]);
  const edited = script ? code !== script.code : code.trim() !== "";

  const pick = (sid: string, from = list) => {
    const s = from.find((x) => x.id === sid);
    setId(sid); setResult(null); setError("");
    setCode(s?.code ?? ""); setName(s && !s.builtin ? s.name : "");
    setValues(Object.fromEntries((s?.params ?? []).map((p) => [p.name, p.default])));
  };

  // Fields come from the "#@ param:" lines; while the code is edited they are read here too.
  const params = useMemo(() => {
    if (script && !edited) return script.params;
    return code.split("\n").flatMap((line) => {
      const m = /^#\s*@\s*param\s*:\s*([A-Za-z_]\w*)\s*(?::\s*([a-z]+)\s*)?(?:=\s*([^|]*?)\s*)?(?:\|\s*(.*))?$/.exec(line.trim());
      return m ? [{ name: m[1], type: (m[2] ?? "text") as "text", default: m[3] ?? "", help: m[4] ?? "" }] : [];
    });
  }, [script, edited, code]);

  const go = async (write: boolean) => {
    if (write && !window.confirm(`Write the changes to ${result?.files.length ?? 0} file(s)? A backup is made first.`)) return;
    setBusy(true); setError("");
    try {
      const shown = Object.fromEntries(params.map((p) => [p.name, values[p.name] ?? p.default]));
      const r = await api.scriptRun({ id: id || "edited", code: edited || !id ? code : null, values: shown, write });
      setResult(r);
      if (r.written) onStatus(`Script written ${r.files.length} file(s); backup: ${r.backup ?? "-"}`);
      else onStatus(r.error ? "The script failed" : `Preview: ${r.files.length} file(s) would change`);
    } catch (e) { setError((e as Error).message); setResult(null); }
    setBusy(false);
  };

  const saveIt = async () => {
    try {
      const own = script && !script.builtin && name.trim() === script.name;
      const r = await api.scriptSave({ name, code, overwrite: !!own });
      onStatus(`Script saved (${r.id})`);
      await reload(r.id);
    } catch (e) { setError((e as Error).message); }
  };

  const remove = async () => {
    if (!script || script.builtin || !window.confirm(`Delete your script "${script.name}"?`)) return;
    await api.scriptDelete(script.id);
    setId(""); setCode(""); reload();
  };

  return (
    <div className="scripts">
      <div className="creator-form">
        <label>Script <select value={id} onChange={(e) => pick(e.target.value)}>
          <option value="">(choose)</option>
          <optgroup label="Built-in">{list.filter((s) => s.builtin).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</optgroup>
          <optgroup label="Your scripts">{list.filter((s) => !s.builtin).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</optgroup>
        </select>
          <button onClick={() => { setId(""); setCode(NEW_SCRIPT); setName(""); setResult(null); setValues({}); }}>New script</button>
        </label>
        {!id && !code && <div className="muted">Small Python programs for repeated jobs on the mod: replace a text in many files, change a value everywhere, list lines… Nothing is written until you press Apply, and a backup is made first. Your scripts are kept in {dir}.</div>}
        {script?.description && <div className="muted">{script.description}</div>}
        {params.map((p) => (
          <label key={p.name} title={p.help}>{p.name} {p.help && <span className="muted">({p.help})</span>}
            {p.type === "bool" ? (
              <select value={values[p.name] ?? (p.default || "no")} onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}><option>yes</option><option>no</option></select>
            ) : (
              <input value={values[p.name] ?? p.default} inputMode={p.type === "int" ? "numeric" : undefined} onChange={(e) => setValues({ ...values, [p.name]: e.target.value })} />
            )}
          </label>
        ))}
        {(id || code) && (
          <>
            <div className="creator-buttons">
              <button onClick={() => go(false)} disabled={busy}>Preview</button>
              <button onClick={() => go(true)} disabled={busy || readOnly || !result || !!result.error || !result.files.length || !!result.written}
                title={readOnly ? "Open a mod to change files" : "Run again and write the files (backup first)"}>Apply (write files)</button>
            </div>
            <details open={!script?.builtin || edited}>
              <summary>Code {script?.builtin && "(built-in: edit and save it as your own script)"}{edited && " - edited"}</summary>
              <textarea className="code script-code" value={code} spellCheck={false} onChange={(e) => { setCode(e.target.value); setResult(null); }} rows={18} />
              <div className="script-save">
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="name of your script" />
                <button onClick={saveIt} disabled={!name.trim()}>{script && !script.builtin && name.trim() === script.name ? "Save" : "Save as my script"}</button>
                {script && !script.builtin && <button onClick={remove}>Delete</button>}
              </div>
            </details>
          </>
        )}
        {error && <div className="creator-error">{error}</div>}
      </div>
      {result && (
        <div className="creator-result">
          {result.error && <pre className="creator-error">{result.error}</pre>}
          {result.output && <><b>Output</b><pre>{result.output}</pre></>}
          {result.backup && <div className="muted">backup: {result.backup}</div>}
          {result.files.length > 0 && (
            <div>{result.written ? "Written: " : "Would change: "}
              {result.files.map((f) => <button key={f} className="link" onClick={() => onOpen(f)}>{f}</button>)}
            </div>
          )}
          {!result.error && !result.files.length && <div className="muted">No file changes.</div>}
          {result.diff && <pre>{result.diff}</pre>}
        </div>
      )}
    </div>
  );
}
