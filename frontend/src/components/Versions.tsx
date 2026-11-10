import { useEffect, useState } from "react";
import { api, type ModVersion, type VersionsInfo } from "../api";
import { SidePanel } from "./Layout";

/**
 * Versions of the mod (T025): the whole mod saved under a name, the list of saved versions,
 * what each changed, and going back to one. Kept as git commits when the mod is a git
 * repository, else as copies of the changed files (K95 = C). Going to a version makes the files what they
 * were then, after saving the state now (K96 = A), so nothing is lost.
 */

const STATUS: Record<string, string> = { A: "added", M: "changed", D: "removed" };

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function Versions({ readOnly, unsaved, onStatus, onOpen }: {
  readOnly: boolean; unsaved: number; onStatus: (t: string) => void; onOpen: (rel: string) => void;
}) {
  const [info, setInfo] = useState<VersionsInfo | null>(null);
  const [sel, setSel] = useState<ModVersion | null>(null);
  const [files, setFiles] = useState<{ title: string; list: { status: string; path: string }[] } | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = () => api.versions().then((r) => { setInfo(r); setError(""); }).catch((e) => setError((e as Error).message));
  useEffect(() => { load(); }, []);

  const show = async (v: ModVersion, compare: boolean) => {
    setSel(v); setFiles(null); setError("");
    try {
      const r = await api.versionFiles(v.id, compare);
      setFiles({ title: compare ? `Files that differ from "${v.name}" now` : `Files "${v.name}" changed`, list: r.files });
    } catch (e) { setError((e as Error).message); }
  };

  const save = async () => {
    setBusy("Saving the version…"); setError("");
    try {
      const v = await api.versionSave(name, description);
      onStatus(`Version "${v.name}" saved`);
      setName(""); setDescription("");
      await load();
    } catch (e) { setError((e as Error).message); }
    setBusy("");
  };

  const restore = async (v: ModVersion) => {
    const now = info?.changed ? ` The ${info.changed} file(s) changed since the last version are saved first as an automatic version.` : "";
    if (!window.confirm(`Make the files of the mod what they were in "${v.name}"?${now} Nothing is lost: you can go to any version of the list later.`)) return;
    setBusy("Going to the version…"); setError("");
    try {
      const r = await api.versionRestore(v.id, v.name);
      onStatus(r.version ? `The mod is now as in "${v.name}" (open files reload from disk)` : `The mod already was as in "${v.name}"`);
      setSel(null); setFiles(null);
      await load();
    } catch (e) { setError((e as Error).message); }
    setBusy("");
  };

  if (!info) return <div className="muted pad">{error || "Reading the versions…"}</div>;
  const blocked = unsaved > 0 ? `${unsaved} file(s) in the editor have unsaved changes: save them first` : "";
  return (
    <div className="split-view mg-tab">
      <SidePanel id="versions" side="left" initial={460} className="mg-list">
        <div className="creator-form versions-save">
          <b>Save the mod as a version</b>
          <div className="muted">{info.changed ? `${info.changed} file(s) changed since the last version.` : info.versions.length ? "Nothing changed since the last version." : "No version yet."}
</div>
          {/* K95: where the versions are and whether they reach GitHub; copies can be big */}
          <div className={info.kind === "copies" || info.note.includes("not connected") ? "problem" : "muted"}>{info.note}</div>
          <label>Name <input value={name} onChange={(e) => setName(e.target.value)} placeholder="before the new reforms" /></label>
          <label>Description <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="(optional)" /></label>
          <button disabled={readOnly || !!busy || !name.trim() || !!blocked} onClick={save} title={blocked}>Save version</button>
        </div>
        <div className="mg-items">
          {info.versions.map((v) => (
            <div key={v.id} className={`row${sel?.id === v.id ? " on" : ""}`} onClick={() => show(v, false)} title={v.description || v.name}>
              <b>{v.name}</b>{v.current && <span className="chip" title="the files on disk are this version">now</span>}
              {v.auto && <span className="chip" title="saved by the tool before going to another version">auto</span>}
              <div className="muted">{when(v.date)} · {v.files} file(s){info.kind === "git" ? ` · ${v.id.slice(0, 8)}` : ""}</div>
            </div>
          ))}
        </div>
      </SidePanel>
      <div className="mg-detail pad">
        {busy && <div className="muted">{busy}</div>}
        {error && <div className="creator-error">{error}</div>}
        {blocked && <div className="problem">{blocked}</div>}
        {!sel && <div className="muted">Choose a version to see what it changed, compare it with the files now or go back to it. Going to a version makes the files on disk what they were then (the game reads them as they are); the state now is saved first, so you can always come back.</div>}
        {sel && (
          <>
            <b>{sel.name}</b> <span className="muted">{when(sel.date)}</span>
            {sel.description && <div>{sel.description}</div>}
            <div className="creator-buttons">
              <button onClick={() => show(sel, false)}>What it changed</button>
              <button onClick={() => show(sel, true)}>Compare with now</button>
              <button disabled={readOnly || !!busy || !!blocked || sel.current} onClick={() => restore(sel)}
                title={sel.current ? "the files are this version already" : blocked}>Go to this version</button>
            </div>
            {files && (
              <div className="versions-files">
                <div className="panel-title">{files.title}: {files.list.length}</div>
                {files.list.slice(0, 1000).map((f) => (
                  <div key={f.path} className="row" onClick={() => f.status !== "D" && onOpen(f.path)} title={f.status !== "D" ? "open in the editor" : ""}>
                    <span className={`chip status-${f.status}`}>{STATUS[f.status] ?? f.status}</span> {f.path}
                  </div>
                ))}
                {files.list.length > 1000 && <div className="muted">… {files.list.length - 1000} more</div>}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
