// Thin typed client of the engine's JSON API (vic2toolmod/server/app.py).

const token = new URLSearchParams(location.search).get("token") ?? "";

export class ApiError extends Error {}

async function call<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-Token": token, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new ApiError(data.error ?? `HTTP ${response.status}`);
  return data as T;
}

const q = (params: Record<string, string | number>) =>
  Object.entries(params)
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join("&");

export interface FileEntry { rel: string; origin: "game" | "mod" }
export interface Project { game_dir: string | null; mod_dir: string | null; files: FileEntry[] }
export interface Diagnostic {
  severity: "error" | "warning" | "info";
  code: string; message: string; start: number; end: number;
  line: number; column: number; end_line: number; end_column: number;
}
export interface FileData { text: string; encoding: string; rel: string; file_type: string | null; diagnostics: Diagnostic[] }
export interface Report { rel: string; file_type: string | null; diagnostics: Diagnostic[] }
export interface Completion { label: string; kind: string; detail: string; doc: string }
export interface Hover { text: string; start: number; end: number }
export interface Definition { name: string; file: string; line: number }
export interface Usage { file: string; start: number; end: number; line: number; column: number }
export interface TextEdit { start: number; end: number; new_text: string }
export interface OutlineNode {
  kind: "assignment" | "block" | "value" | "error";
  key?: string; value?: string; start: number; end: number; line: number; children?: OutlineNode[];
}

export interface Fact { id: string; key: string; value: string; compare: string; kind: "condition" | "scope"; line: number; question: string }
export interface TriggerResult { value: boolean | null; failed: string[]; unknown: string[] }

export interface BlockNode {
  kind: "assignment" | "block" | "value" | "error";
  start: number; end: number; line: number;
  key?: string; key_start?: number; key_end?: number;
  role?: "trigger" | "effect" | "scope" | "field" | "dynamic" | "unknown";
  doc?: string; spec?: string;
  block?: boolean; lbrace?: number; rbrace?: number | null; scope?: string | null; context?: string | null;
  children?: BlockNode[];
  value?: string; value_start?: number; value_end?: number;
  value_kind?: "bool" | "number" | "enum" | "ref" | "loc" | "date" | "text" | "block";
  registry?: string | null; choices?: string[]; loc_text?: string | null;
}

export interface Box {
  name: string; x: number; y: number; w: number; h: number;
  category: string | null; line: number; outside: boolean; clipped: boolean;
}
export interface ReformLayout {
  file: string; width: number; height: number; boxes: Box[];
  missing: Record<string, string[]>; unknown: string[]; categories: Record<string, string[]>;
}

export const api = {
  project: () => call<Project>("project"),
  file: (rel: string) => call<FileData>(`file?${q({ rel })}`),
  buffer: (rel: string, text: string) => call<Report>("buffer", { rel, text }),
  revert: (rel: string) => call<{ ok: boolean }>("revert", { rel }),
  save: (rel: string, text: string) => call<{ ok: boolean; path: string; backup: string | null }>("save", { rel, text }),
  check: (onlyMod = true) => call<{ files: { rel: string; diagnostics: Diagnostic[] }[] }>(`check?only_mod=${onlyMod ? 1 : 0}`),
  complete: (rel: string, offset: number) => call<{ items: Completion[]; total: number }>(`complete?${q({ rel, offset })}`),
  hover: (rel: string, offset: number) => call<{ hover: Hover | null }>(`hover?${q({ rel, offset })}`),
  definition: (rel: string, offset: number) => call<{ definition: Definition | null }>(`definition?${q({ rel, offset })}`),
  references: (rel: string, offset: number) => call<{ usages: Usage[] }>(`references?${q({ rel, offset })}`),
  rename: (rel: string, offset: number, newName: string) =>
    call<{ edits: Record<string, TextEdit[]> }>("rename", { rel, offset, new_name: newName }),
  changed: () => call<{ changed: string[] }>("changed"),
  outline: (rel: string) => call<{ items: OutlineNode[] }>(`outline?${q({ rel })}`),
  trigger: (rel: string, offset: number, answers?: Record<string, string | boolean>) =>
    call<{ start: number; facts: Fact[]; result: TriggerResult | null }>("trigger", { rel, offset, answers }),
  blocks: (rel: string) => call<{ items: BlockNode[]; root_rule: string | null }>(`blocks?${q({ rel })}`),
  edit: (body: Record<string, unknown>) => call<{ edits: TextEdit[] }>("edit", body),
  localisation: (key: string, english: string, write: boolean) =>
    call<{ diff: string }>("localisation", { key, english, write }),
  names: (registry: string) => call<{ names: string[] }>(`names?${q({ registry })}`),
  createReform: (spec: unknown, write: boolean) =>
    call<{ diff: string; files: string[]; notes: string[]; backup?: string | null }>("create/reform", { spec, write }),
  createIdeology: (spec: unknown, write: boolean) =>
    call<{ diff: string; files: string[]; notes: string[]; backup?: string | null }>("create/ideology", { spec, write }),
  createEvent: (spec: unknown, write: boolean) =>
    call<{ diff: string; files: string[]; notes: string[]; backup?: string | null }>("create/event", { spec, write }),
  createDecision: (spec: unknown, write: boolean) =>
    call<{ diff: string; files: string[]; notes: string[]; backup?: string | null }>("create/decision", { spec, write }),
  parties: (body: unknown, write: boolean) =>
    call<{ diff: string; created: string[]; skipped: Record<string, string>; backup?: string | null }>(
      write ? "parties/write" : "parties/plan", body),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  poptypesGraph: () => call<any>("poptypes/graph"),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  eventsGraph: () => call<any>("events/graph"),
  vanillaFiles: () => call<{ files: { rel: string; status: string; added: number; removed: number }[] }>("vanilla/diff"),
  vanillaDiff: (rel: string) => call<{ diff: string }>(`vanilla/diff?${q({ rel })}`),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  stats: () => call<any>("stats"),
  localisationSearch: (text: string, limit = 200) =>
    call<{ entries: { key: string; english: string; file: string; line: number }[]; total: number }>(`localisation?${q({ q: text, limit })}`),
  git: () => call<{ repo: boolean; branch?: string; changed?: [string, string][]; error?: string }>("git"),
  gitDiff: (rel: string) => call<{ diff: string }>(`git?${q({ rel })}`),
  reformWindow: () => call<ReformLayout>("reforms/window"),
  reformWindowPlan: (positions: Record<string, [number, number]>, write: boolean) =>
    call<{ diff: string; backup?: string | null }>("reforms/window", { positions, add_missing: true, write }),
};

/** Apply edits (offsets into `text`) - same semantics as vic2toolmod.edit.apply_edits. */
export function applyEdits(text: string, edits: TextEdit[]): string {
  const sorted = [...edits].sort((a, b) => b.start - a.start);
  let out = text;
  for (const e of sorted) out = out.slice(0, e.start) + e.new_text + out.slice(e.end);
  return out;
}
