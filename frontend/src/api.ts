// Thin typed client of the engine's JSON API (vic2toolmod/server/app.py).

const token = new URLSearchParams(location.search).get("token") ?? "";
/** This browser tab, so the server knows when the last one was closed (server/lifecycle.py). */
const client = Math.random().toString(36).slice(2) + Date.now().toString(36);

/** Tell the server this tab is going away (it stops when the last one is gone). */
export function sayBye(): void {
  navigator.sendBeacon(`/api/bye?token=${encodeURIComponent(token)}&client=${client}`);
}

export class ApiError extends Error {}

async function call<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-Token": token, "X-Client": client, "Content-Type": "application/json" },
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
export interface Project { game_dir: string | null; mod_dir: string | null; read_only?: boolean; files: FileEntry[] }
export interface ModEntry { name: string; path: string; source: "game" | "settings" | "recent" }
export interface Projects { current: string | null; game_dir: string | null; recent: string[]; mods: ModEntry[] }
export interface Diagnostic {
  severity: "error" | "warning" | "info";
  code: string; message: string; start: number; end: number;
  line: number; column: number; end_line: number; end_column: number;
}
export interface FileData { text: string; encoding: string; rel: string; file_type: string | null; diagnostics: Diagnostic[] }
export interface Report { rel: string; file_type: string | null; diagnostics: Diagnostic[] }
export interface Completion { label: string; kind: string; detail: string; doc: string }
export interface Hover { text: string; start: number; end: number; sprite?: [string, number] | null; picture?: string | null }
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
  sprite?: [string, number];
  picture?: string;
  value_kind?: "bool" | "number" | "enum" | "ref" | "loc" | "date" | "text" | "block";
  registry?: string | null; choices?: string[]; loc_text?: string | null;
}

export interface Box {
  name: string; x: number; y: number; w: number; h: number;
  category: string | null; line: number; outside: boolean; clipped: boolean;
}
/** An element of a game window (vic2toolmod/analysis/gui_tree.py). */
export interface GuiElement {
  kind: string; name: string; x: number; y: number; w: number; h: number; orientation: string;
  sprite: string; text: string; font: string; max_w: number; max_h: number; format: string;
  line: number; children: GuiElement[];
}
export interface SpriteInfo { frames: number; w: number; h: number; found: boolean }
export interface GuiWindow {
  file: string; tree: GuiElement; backdrop: GuiElement[];
  texts: Record<string, string>; sprites: Record<string, SpriteInfo>;
}
export interface ReformLayout {
  file: string; width: number; height: number; boxes: Box[];
  missing: Record<string, string[]>; unknown: string[]; categories: Record<string, string[]>;
  tree: GuiElement; backdrop: GuiElement[]; option_row: GuiElement | null;
  issues: Record<string, { text: string; options: { key: string; text: string }[] }>;
  texts: Record<string, string>; sprites: Record<string, SpriteInfo>;
}

export interface TemplateField { name: string; type: string; default: string }
export interface TemplateInfo {
  id: string; name: string; description: string; folder: string; builtin: boolean;
  body: string; loc: string[]; fields: TemplateField[];
}
/** A saved version of the whole mod (T025): a git commit or a zip copy. */
export interface ModVersion { id: string; name: string; description: string; date: string; files: number; auto: boolean; current: boolean }
export interface VersionsInfo { kind: "git" | "copies"; where: string; versions: ModVersion[]; changed: number; note: string }
export interface ModStep { value: string; factor: string; line: number; start: number; end: number; negated: boolean }
export interface ModGroup {
  id: string; rel: string; line: number; path: string[]; key: string; negated: boolean; compare: "gte" | "lte";
  context: string[]; combine: "multiply" | "add"; combine_note: string; base: string | null; base_key: string | null; steps: ModStep[]; signature: string;
}
export interface MetaRule {
  name: string; block: string; target: string; description: string; strata: string[]; pop_types: string[];
  group: boolean; modifiers: string; pops?: string[];
}
export interface MetaInfo {
  rules: MetaRule[]; pops: Record<string, string>; blocks: { pop: string[]; chance: string[] };
  names: Record<string, string[]>; folder: string;
}
export interface MetaPlan {
  diff: string; files: string[]; added: [string, string][]; updated: [string, string][]; removed: [string, string][];
  edited: [string, string][]; missing: [string, string, string][]; written?: boolean; backup?: string | null;
}
export interface FormatPlan {
  files: { rel: string; lines: number }[];
  skipped: { rel: string; reason: string }[];
  same: number;
}
export interface ScriptParam { name: string; type: "text" | "int" | "bool"; default: string; help: string }
export interface ScriptInfo { id: string; name: string; description: string; builtin: boolean; code: string; params: ScriptParam[] }
export interface ScriptRun { output: string; error: string; diff: string; files: string[]; backup?: string | null; written?: boolean }
export interface TemplateFill { text: string; diff: string; files: string[]; notes: string[]; backup?: string | null }

export const api = {
  project: () => call<Project>("project"),
  projects: () => call<Projects>("projects"),
  guiWindows: (rel: string) => call<{ windows: { name: string; line: number; depth: number }[] }>(`gui/windows?${q({ rel })}`),
  guiWindow: (rel: string, name: string) => call<GuiWindow>(`gui/window?${q({ rel, name })}`),
  guiPlan: (rel: string, changes: Record<number, { x?: number; y?: number; w?: number; h?: number }>, write: boolean) =>
    call<{ diff: string; backup?: string | null }>("gui/plan", { rel, changes, write }),
  openProject: (mod: string | null) => call<{ mod_dir: string | null }>("project/open", { mod }),
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
  changed: () => call<{ changed: string[]; stale: boolean; memory_mb: number | null }>("changed"),
  ping: () => call<{ stamp: string; stale: boolean; pid: number }>("ping"),
  restart: () => call<{ ok: boolean }>("restart", {}),
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
  createCountry: (spec: unknown, write: boolean) =>
    call<{ diff: string; files: string[]; notes: string[]; backup?: string | null }>("create/country", { spec, write }),
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
  versions: () => call<VersionsInfo>("versions"),
  versionFiles: (id: string, compare: boolean) =>
    call<{ files: { status: string; path: string }[] }>(`versions/files?${q({ id, compare: compare ? "1" : "" })}`),
  versionSave: (name: string, description: string) => call<ModVersion>("versions/save", { name, description }),
  versionRestore: (id: string, name: string) => call<{ version: ModVersion | null }>("versions/restore", { id, name }),
  git: () => call<{ repo: boolean; branch?: string; changed?: [string, string][]; error?: string }>("git"),
  gitDiff: (rel: string) => call<{ diff: string }>(`git?${q({ rel })}`),
  templates: () => call<{ dir: string; templates: TemplateInfo[] }>("templates"),
  templateValues: (id: string, file = "") =>
    call<{ defaults: Record<string, string>; choices: Record<string, string[]> }>(`template?${q({ id, file })}`),
  templateFill: (body: { id: string; values: Record<string, string>; file?: string | null; write: boolean }) =>
    call<TemplateFill>("template/fill", body),
  templateSave: (body: { name: string; body: string; description: string; folder: string; loc: string[]; overwrite?: boolean }) =>
    call<{ id: string }>("template/save", body),
  templateDelete: (id: string) => call<{ deleted: string }>("template/delete", { id }),
  modGroups: (rel = "") => call<{ groups: ModGroup[] }>(`modgroups?${q({ rel })}`),
  modGroupEdits: (rel: string, id: string, steps: [string, string, boolean][]) =>
    call<{ edits: { start: number; end: number; text: string }[] }>("modgroups/edits", { rel, id, steps }),
  modGroupPlan: (plans: { rel: string; id: string; steps: [string, string, boolean][] }[], write: boolean) =>
    call<{ diff: string; files: string[]; backup?: string | null; written?: boolean }>("modgroups/plan", { plans, write }),
  meta: () => call<MetaInfo>("meta"),
  metaPlan: (body: { rule?: MetaRule; old_name?: string; delete?: boolean; name?: string; force?: boolean; write?: boolean }) =>
    call<MetaPlan>("meta/plan", body),
  codeGroups: (text: string, block: string, target: string) => call<{ groups: ModGroup[] }>("modgroups/text", { text, block, target }),
  codeGroupEdit: (text: string, block: string, target: string, id: string, steps: [string, string, boolean][]) =>
    call<{ text: string }>("modgroups/text-edit", { text, block, target, id, steps }),
  stretchPicture: (body: { sprite: string; width: number; height: number; border: number | number[] | "auto"; inside?: number[]; write: boolean; rel?: string; line?: number }) =>
    call<{ file: string; from: [number, number]; to: [number, number]; border: number[]; preview?: string; written?: boolean; texture?: string; sprite?: string; backup?: string | null }>("picture/stretch", body),
  formatText: (text: string) => call<{ text: string }>("format/text", { text }),
  formatPlan: () => call<FormatPlan>("format/plan", {}),
  formatDiff: (rel: string) => call<{ diff: string }>(`format/diff?${q({ rel })}`),
  formatWrite: (rels: string[]) => call<{ written: number; backup: string | null }>("format/write", { rels }),
  scripts: () => call<{ dir: string; scripts: ScriptInfo[] }>("scripts"),
  scriptRun: (body: { id: string; code?: string | null; values: Record<string, string>; write: boolean }) =>
    call<ScriptRun>("script/run", body),
  scriptSave: (body: { name: string; code: string; overwrite?: boolean }) => call<{ id: string }>("script/save", body),
  scriptDelete: (id: string) => call<{ deleted: string }>("script/delete", { id }),
  reformWindow: () => call<ReformLayout>("reforms/window"),
  reformWindowPlan: (positions: Record<string, [number, number]>, write: boolean) =>
    call<{ diff: string; backup?: string | null }>("reforms/window", { positions, add_missing: true, write }),
};

/** URL of an event picture as PNG (an <img> cannot send the token header). */
export const pictureUrl = (name: string) => `/api/picture?${q({ name, token })}`;
/** One frame (from 1) of a sprite of interface/*.gfx as PNG (T003). */
export const spriteUrl = (name: string, frame: number) => `/api/sprite?${q({ name, frame, token })}`;
/** A picture file under gfx/ (.tga / .dds) as PNG (T006). */
export const imageUrl = (rel: string) => `/api/image?${q({ rel, token })}`;

/** Apply edits (offsets into `text`) - same semantics as vic2toolmod.edit.apply_edits. */
export function applyEdits(text: string, edits: TextEdit[]): string {
  const sorted = [...edits].sort((a, b) => b.start - a.start);
  let out = text;
  for (const e of sorted) out = out.slice(0, e.start) + e.new_text + out.slice(e.end);
  return out;
}
