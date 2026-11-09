// Monaco from the local bundle (no CDN, K45) + the Paradox script language,
// wired to the engine's language services through the API.
import * as monaco from "monaco-editor/editor/editor.api.js";
import "monaco-editor/features/register.all.js"; // suggest, hover, find, folding … (no other languages)
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";
import { api, type Completion } from "./api";

declare global {
  interface Window {
    MonacoEnvironment?: monaco.Environment;
  }
}

window.MonacoEnvironment = { getWorker: () => new EditorWorker() };

export const LANGUAGE = "paradox";

monaco.languages.register({ id: LANGUAGE, extensions: [".txt", ".gui", ".gfx"] });
monaco.languages.setLanguageConfiguration(LANGUAGE, {
  comments: { lineComment: "#" },
  brackets: [["{", "}"]],
  autoClosingPairs: [
    { open: "{", close: "}" },
    { open: '"', close: '"' },
  ],
  surroundingPairs: [
    { open: "{", close: "}" },
    { open: '"', close: '"' },
  ],
  wordPattern: /[A-Za-z0-9_.\-@]+/,
});
monaco.languages.setMonarchTokensProvider(LANGUAGE, {
  defaultToken: "",
  tokenizer: {
    root: [
      [/#.*$/, "comment"],
      [/"[^"]*"/, "string"],
      [/"[^"]*$/, "string.invalid"],
      [/[{}]/, "@brackets"],
      [/(<=|>=|=|<|>)/, "operator"],
      [/\d{1,4}\.\d{1,2}\.\d{1,2}\b/, "number.date"],
      [/-?\d*\.?\d+\b/, "number"],
      [/\b(yes|no)\b/, "keyword"],
      [/\b(AND|OR|NOT|THIS|FROM|limit|trigger|effect|option|immediate|potential|allow)\b/, "keyword.control"],
      [/[A-Za-z_][A-Za-z0-9_.\-@:']*(?=\s*(=|<|>))/, "variable"],
      [/[A-Za-z0-9_.\-@:']+/, "identifier"],
    ],
  },
});

/** Relative path of the file shown in a Monaco model (we use `file:///<rel>` URIs). */
export const relOf = (model: monaco.editor.ITextModel) => decodeURIComponent(model.uri.path.slice(1));
export const uriOf = (rel: string) => monaco.Uri.parse(`file:///${encodeURIComponent(rel).replace(/%2F/g, "/")}`);

const KINDS: Record<string, monaco.languages.CompletionItemKind> = {
  field: monaco.languages.CompletionItemKind.Field,
  "field (required)": monaco.languages.CompletionItemKind.Field,
  trigger: monaco.languages.CompletionItemKind.Function,
  effect: monaco.languages.CompletionItemKind.Method,
  scope: monaco.languages.CompletionItemKind.Module,
  modifier: monaco.languages.CompletionItemKind.Property,
  name: monaco.languages.CompletionItemKind.Reference,
  value: monaco.languages.CompletionItemKind.Value,
};

/** Hook the App sets so providers can make sure the server has the editor's text. */
export const hooks = {
  sync: async (_rel: string, _text: string): Promise<void> => {},
};

async function synced(model: monaco.editor.ITextModel) {
  await hooks.sync(relOf(model), model.getValue());
  return relOf(model);
}

monaco.languages.registerCompletionItemProvider(LANGUAGE, {
  triggerCharacters: ["=", " ", "_"],
  async provideCompletionItems(model, position) {
    const rel = await synced(model);
    const { items } = await api.complete(rel, model.getOffsetAt(position));
    const word = model.getWordUntilPosition(position);
    const range = new monaco.Range(position.lineNumber, word.startColumn, position.lineNumber, word.endColumn);
    return {
      suggestions: items.map((c: Completion) => ({
        label: c.label,
        kind: KINDS[c.kind] ?? monaco.languages.CompletionItemKind.Text,
        detail: [c.kind, c.detail].filter(Boolean).join(" · "),
        documentation: c.doc,
        insertText: c.label === "{ }" ? "{\n\t$0\n}" : c.label,
        insertTextRules: c.label === "{ }" ? monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet : undefined,
        range,
      })),
    };
  },
});

monaco.languages.registerHoverProvider(LANGUAGE, {
  async provideHover(model, position) {
    const rel = await synced(model);
    const { hover } = await api.hover(rel, model.getOffsetAt(position));
    if (!hover) return null;
    const a = model.getPositionAt(hover.start);
    const b = model.getPositionAt(hover.end);
    return {
      range: new monaco.Range(a.lineNumber, a.column, b.lineNumber, b.column),
      // Plain markdown from our own server; Monaco sanitises it (DOMPurify).
      contents: [{ value: hover.text, isTrusted: false, supportHtml: false }],
    };
  },
});

export { monaco };
