import { useEffect, useMemo, useState } from "react";
import { api, type FormatPlan } from "../api";

/**
 * Format the whole mod (T011, K91 = A, K92 = A): every .txt / .gui / .gfx file of the mod,
 * lightly (indentation, spaces around =, line ends). A plan first, a diff per file, then
 * "Write" with a backup. Folders can be left out.
 */
export function FormatMod({ onStatus, onClose }: { onStatus: (t: string) => void; onClose: () => void }) {
  const [plan, setPlan] = useState<FormatPlan | null>(null);
  const [error, setError] = useState("");
  const [off, setOff] = useState<Set<string>>(new Set());
  const [shown, setShown] = useState<string | null>(null);
  const [diff, setDiff] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.formatPlan().then(setPlan).catch((e) => setError((e as Error).message)); }, []);
  const folders = useMemo(() => {
    const m = new Map<string, { files: number; lines: number }>();
    for (const f of plan?.files ?? []) {
      const top = f.rel.split("/")[0];
      const v = m.get(top) ?? { files: 0, lines: 0 };
      m.set(top, { files: v.files + 1, lines: v.lines + f.lines });
    }
    return [...m.entries()].sort((a, b) => b[1].files - a[1].files);
  }, [plan]);
  const chosen = (plan?.files ?? []).filter((f) => !off.has(f.rel.split("/")[0]));
  const lines = chosen.reduce((a, f) => a + f.lines, 0);

  const show = async (rel: string) => {
    setShown(rel); setDiff("…");
    try { setDiff((await api.formatDiff(rel)).diff); } catch (e) { setDiff((e as Error).message); }
  };
  const write = async () => {
    if (!window.confirm(`Format ${chosen.length} file(s) (${lines} lines)? A backup is made first.\n\nTip: commit the mod in git before, and commit the formatting on its own.`)) return;
    setBusy(true);
    try {
      const r = await api.formatWrite(chosen.map((f) => f.rel));
      onStatus(`Formatted ${r.written} file(s); backup: ${r.backup ?? "-"}`);
      onClose();
    } catch (e) { setError((e as Error).message); }
    setBusy(false);
  };

  return (
    <div className="format-mod">
      <b>Format the whole mod</b>
      <div className="muted">Indentation (a tab per level), one space around <code>=</code>, no spaces at line ends, at most one empty line in a row. Line breaks, comments and strings stay; game files are never touched.</div>
      {!plan && !error && <div className="muted">Formatting every file of the mod (a few seconds)…</div>}
      {error && <div className="creator-error">{error}</div>}
      {plan && (
        <>
          <div><b>{chosen.length}</b> file(s) would change (<b>{lines}</b> lines); {plan.same} already formatted{plan.skipped.length > 0 && <>; {plan.skipped.length} not formatted</>}.</div>
          <div className="format-folders">
            {folders.map(([top, v]) => (
              <label key={top}><input type="checkbox" checked={!off.has(top)} onChange={() => { const n = new Set(off); if (n.has(top)) n.delete(top); else n.add(top); setOff(n); }} />
                {top}/ <span className="muted">{v.files} files, {v.lines} lines</span></label>
            ))}
          </div>
          {plan.skipped.length > 0 && (
            <details><summary>Not formatted ({plan.skipped.length})</summary>
              {plan.skipped.map((s) => <div key={s.rel} className="muted">{s.rel}: {s.reason}</div>)}
            </details>
          )}
          <div className="format-body">
            <div className="format-files">
              {chosen.slice(0, 1000).map((f) => (
                <div key={f.rel} className={`row${shown === f.rel ? " on" : ""}`} onClick={() => show(f.rel)}>{f.rel} <span className="muted">{f.lines}</span></div>
              ))}
              {chosen.length > 1000 && <div className="muted">… {chosen.length - 1000} more</div>}
            </div>
            <pre className="format-diff">{shown ? diff : "Click a file to see its changes."}</pre>
          </div>
        </>
      )}
      <div className="creator-buttons">
        <button disabled={!plan || !chosen.length || busy} onClick={write}>Write {chosen.length} file(s)</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </div>
  );
}
