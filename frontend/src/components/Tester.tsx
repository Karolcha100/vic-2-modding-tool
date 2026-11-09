import { useState } from "react";
import { api, type Fact, type TriggerResult } from "../api";

/** Trigger tester (K53): answer the facts of a trigger block, see the result. */

interface Props {
  rel: string;
  offset: number;
  facts: Fact[];
  onOpen: (line: number) => void;
}

export function Tester({ rel, offset, facts, onOpen }: Props) {
  const [answers, setAnswers] = useState<Record<string, string | boolean>>({});
  const [result, setResult] = useState<TriggerResult | null>(null);
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
        <button className="mini" onClick={() => run({})}>clear</button>
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
