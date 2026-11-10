import { useState } from "react";
import { api, type Fact, type TriggerResult } from "../api";
import { useStored } from "./Layout";
import { WorldSource } from "./WorldSource";

/**
 * Trigger tester (K53): answer the facts of a trigger block, see the result. "From history"
 * (K75 B) answers what the history files say for a country at a date, and lists the countries
 * that meet the trigger; what history cannot tell (money, pops, relations …) stays for you.
 */

interface Props {
  rel: string;
  offset: number;
  facts: Fact[];
  onOpen: (line: number) => void;
}

export function Tester({ rel, offset, facts, onOpen }: Props) {
  const [answers, setAnswers] = useState<Record<string, string | boolean>>({});
  const [result, setResult] = useState<TriggerResult | null>(null);
  const [tag, setTag] = useStored("vic2.tester.tag", "");
  const [date, setDate] = useStored("vic2.tester.date", "1836.1.1");
  const [player, setPlayer] = useStored("vic2.tester.player", "");
  const [great, setGreat] = useStored("vic2.tester.great", "");
  const [secondary, setSecondary] = useStored("vic2.tester.secondary", "");
  const [save, setSave] = useStored("vic2.tester.save", "");
  const world = { date, player, great, secondary, save };
  const guess = async () => {
    try { const r = await api.triggerPowers(date); setGreat(r.great.join(" ")); setSecondary(r.secondary.join(" ")); } catch (e) { setError((e as Error).message); }
  };
  const [why, setWhy] = useState<string[]>([]);
  const [countries, setCountries] = useState<{ true: string[]; unknown: { tag: string; reasons: string[] }[]; false: number } | null>(null);
  const [error, setError] = useState("");
  const fromHistory = async (t = tag) => {
    if (!t.trim()) { setError("write a country tag"); return; }
    setError(""); setTag(t.toUpperCase());
    try {
      const r = await api.triggerWorld(rel, offset, t.trim(), world);
      setAnswers(r.answers); setResult(r.result); setWhy(r.value === true ? [] : r.reasons);
    } catch (e) { setError((e as Error).message); }
  };
  const which = async () => {
    setError(""); setCountries(null);
    try { setCountries(await api.triggerCountries(rel, offset, world)); } catch (e) { setError((e as Error).message); }
  };
  const run = async (next: Record<string, string | boolean>) => {
    setAnswers(next);
    const r = await api.trigger(rel, offset, next);
    setResult(r.result);
  };
  const verdict = result?.value === true ? "TRUE" : result?.value === false ? "FALSE" : "unknown";
  return (
    <div className="tester">
      <div className="tester-head">
        Result: <b className={`verdict v-${verdict}`}>{verdict}</b>
        <span className="muted"> - answer with the value in the game (a number, a tag, yes/no) or tick true / false. NOT = none of its conditions.</span>
        <button className="mini" onClick={() => { run({}); setWhy([]); }}>clear</button>
      </div>
      <div className="tester-world">
        From history: country <input value={tag} onChange={(e) => setTag(e.target.value)} placeholder="PRU" size={5}
          onKeyDown={(e) => { if (e.key === "Enter") fromHistory(); }} />
        {" "}<WorldSource date={date} setDate={setDate} save={save} setSave={setSave} />
        {" "}player <input value={player} onChange={(e) => setPlayer(e.target.value)} placeholder={save ? "(the save's)" : "(for ai)"} size={6} title="the player's country: ai = no for it, yes for the others (a save says it)" />
        {" "}<button className="mini" onClick={() => fromHistory()}>Fill from history</button>
        <button className="mini" onClick={which} title="every country that exists at the date">Which countries?</button>
        <div>great powers <input value={great} onChange={(e) => setGreat(e.target.value)} placeholder={save ? "(the save's)" : "(not known)"} size={30}
          title="tags; the game ranks the powers by its own score (a save has the great powers), so from history is_greater_power is not known until you give them" />
          {" "}secondary <input value={secondary} onChange={(e) => setSecondary(e.target.value)} placeholder="(not known)" size={30} />
          {" "}<button className="mini" onClick={guess} title="the 8 + 8 civilised countries with the most prestige at the date">guess from prestige</button></div>
        {error && <span className="creator-error"> {error}</span>}
        {why.length > 0 && <div className="muted">{result?.value === false ? "false because: " : "not known from history (answer these yourself): "}{why.join("; ")}</div>}
        {countries && (
          <div className="tester-countries">
            <b>{countries.true.length}</b> meet it{countries.true.length ? ":" : ""} {countries.true.map((t) => (
              <span key={t} className="chip" onClick={() => fromHistory(t)} title="fill the facts for this country">{t}</span>
            ))}
            {countries.unknown.length > 0 && <div className="muted">{countries.unknown.length} not known from history: {countries.unknown.slice(0, 12).map((u) => (
              <span key={u.tag} className="chip" title={u.reasons.join("; ")} onClick={() => fromHistory(u.tag)}>{u.tag}</span>
            ))}{countries.unknown.length > 12 ? " …" : ""} (hover: why)</div>}
            <div className="muted">{countries.false} do not.</div>
          </div>
        )}
      </div>
      {facts.map((f) => {
        const failed = result?.failed.includes(f.id);
        const unknown = result?.unknown.includes(f.id);
        const depth = f.id.split(".").length - 1;
        return (
          <div key={f.id} className={"fact" + (failed ? " failed" : "") + (unknown ? " unknown" : "")} style={{ paddingLeft: 8 + depth * 16 }}>
            <span className="fact-q" onClick={() => onOpen(f.line)} title={`line ${f.line}`}>{f.question}</span>
            {f.kind === "scope" || f.compare === "block" ? (
              <select value={String(answers[f.id] ?? "")} onChange={(e) => run({ ...answers, [f.id]: e.target.value === "" ? "" : e.target.value === "true" })}>
                <option value="">?</option><option value="true">true</option><option value="false">false</option>
              </select>
            ) : (
              <input value={String(answers[f.id] ?? "")} placeholder={f.value}
                onChange={(e) => setAnswers({ ...answers, [f.id]: e.target.value })}
                onBlur={() => run(answers)} onKeyDown={(e) => { if (e.key === "Enter") run(answers); }} />
            )}
          </div>
        );
      })}
    </div>
  );
}
