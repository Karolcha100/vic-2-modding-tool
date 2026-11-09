import { useEffect, useState } from "react";
import { api, type Projects } from "../api";

/** Open another mod or the game's own files (K81 = A, T005 point 3). */
export function ProjectPicker({ dirty, onClose }: { dirty: boolean; onClose: () => void }) {
  const [data, setData] = useState<Projects | null>(null);
  const [path, setPath] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { api.projects().then(setData).catch((e) => setError((e as Error).message)); }, []);

  const open = async (mod: string | null) => {
    if (dirty && !window.confirm("Some files have unsaved changes. Open another project anyway?")) return;
    try {
      await api.openProject(mod);
      location.reload(); // everything in the page belongs to the old project
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const label = { game: "in the game's mod folder", settings: "from the settings", recent: "opened recently" };
  return (
    <div className="project-picker">
      <div className="panel-title">Open a project</div>
      {error && <div className="creator-error">{error}</div>}
      {!data ? <div className="muted pad">Loading…</div> : (
        <>
          {data.mods.map((m) => (
            <div key={m.path} className={"row" + (m.path === data.current ? " active" : "")} onClick={() => open(m.path)} title={m.path}>
              <b>{m.name}</b> <span className="muted">{m.path} · {label[m.source]}</span>
              {m.path === data.current && <span className="chip">open</span>}
            </div>
          ))}
          <div className={"row" + (data.current === null ? " active" : "")} onClick={() => open(null)}>
            <b>Vanilla (read-only)</b> <span className="muted">{data.game_dir ?? "game folder not set"} · the game's own files, nothing can be saved</span>
          </div>
          <div className="pad project-path">
            <input placeholder="or another mod folder: /path/to/MyMod" value={path} onChange={(e) => setPath(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && path.trim()) open(path.trim()); }} />
            <button disabled={!path.trim()} onClick={() => open(path.trim())}>Open</button>
          </div>
        </>
      )}
      <div className="pad"><button onClick={onClose}>Cancel</button></div>
    </div>
  );
}
