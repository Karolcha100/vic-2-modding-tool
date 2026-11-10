// Navigation history and undo targets (T012).
//
// * Navigation: views, the open file, editor modes, tabs and selected items are
//   kept in the browser's history (history.pushState). The mouse's back / forward
//   buttons and Alt+Left / Alt+Right then move through them like in a web browser.
//   A component asks for such a value with `useNav(key, initial)`.
// * Undo: Ctrl+Z / Ctrl+Shift+Z (and Ctrl+Y) outside text fields go to the
//   view that is shown: the code editor, or a view that registered an undo
//   target with `useUndoTarget` (the window editors). `useUndoable` is a state
//   with its own undo / redo stack for such views.
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

type NavState = Record<string, unknown>;

const KEY = "vic2nav";
let state: NavState = ((history.state ?? {}) as Record<string, NavState>)[KEY] ?? {};
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

history.replaceState({ ...(history.state ?? {}), [KEY]: state }, "");
window.addEventListener("popstate", (e) => {
  state = ((e.state ?? {}) as Record<string, NavState>)[KEY] ?? {};
  notify();
});

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

let lastPush = 0;

/**
 * Change navigation values: a new history entry (`push`) or the current one (`replace`).
 * Pushes right after each other (one click that changes the view and opens a file) make one step.
 */
export function navSet(values: NavState, how: "push" | "replace" = "push"): void {
  if (Object.entries(values).every(([k, v]) => same(state[k], v))) return;
  state = { ...state, ...values };
  const now = performance.now();
  if (how === "push" && now - lastPush < 100) how = "replace";
  if (how === "push") lastPush = now;
  if (how === "push") history.pushState({ [KEY]: state }, "");
  else history.replaceState({ [KEY]: state }, "");
  notify();
}

/** Read a navigation value without subscribing. */
export const navGet = <T,>(key: string): T | undefined => state[key] as T | undefined;

/** A value kept in the navigation history: setting it makes a step that "back" undoes. */
export function useNav<T>(key: string, initial: T): [T, (v: T) => void] {
  const value = useSyncExternalStore(
    (l) => { listeners.add(l); return () => listeners.delete(l); },
    () => state[key],
  );
  const set = useCallback((v: T) => navSet({ [key]: v }), [key]);
  return [(value === undefined ? initial : value) as T, set];
}

/**
 * A dialog that "back" closes: `open(data)` shows it as a navigation step,
 * `close()` goes back one step (when the dialog is the current step).
 */
export function useNavModal<T>(id: string): [T | null, (data: T) => void, () => void] {
  const [shown] = useNav<string | null>("modal", null);
  const [data, setData] = useState<T | null>(null);
  const open = useCallback((d: T) => { setData(d); navSet({ modal: id }); }, [id]);
  const close = useCallback(() => { if (state.modal === id) history.back(); }, [id]);
  return [shown === id ? data : null, open, close];
}

/** `useNav` whose value is also remembered in this browser (the last choice comes back next time). */
export function useNavStored<T>(key: string, initial: T): [T, (v: T) => void] {
  const [start] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  const [value, set] = useNav<T>(key, start);
  const setBoth = useCallback((v: T) => {
    set(v);
    try { window.localStorage.setItem(key, JSON.stringify(v)); } catch { /* not remembered */ }
  }, [key, set]);
  return [value, setBoth];
}

// -- undo targets ----------------------------------------------------------------------------
export interface UndoTarget { undo: () => void; redo: () => void }
let target: UndoTarget | null = null;

/** While mounted, Ctrl+Z / Ctrl+Shift+Z outside text fields go to this view. */
export function useUndoTarget(t: UndoTarget | null): void {
  const ref = useRef(t);
  ref.current = t;
  useEffect(() => {
    const me: UndoTarget = { undo: () => ref.current?.undo(), redo: () => ref.current?.redo() };
    target = me;
    return () => { if (target === me) target = null; };
  }, []);
}

/** The registered undo target of the shown view, if any. */
export const undoTarget = (): UndoTarget | null => target;

/** Is the key event an undo (1), a redo (-1) or neither (0)? Ctrl+Z, Ctrl+Shift+Z, Ctrl+Y. */
export function undoKey(e: KeyboardEvent): 1 | -1 | 0 {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return 0;
  const k = e.key.toLowerCase();
  if (k === "z") return e.shiftKey ? -1 : 1;
  if (k === "y" && !e.shiftKey) return -1;
  return 0;
}

/** Text fields keep their own undo. */
export function inTextField(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  return el.isContentEditable || el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT"
    || el.closest(".monaco-editor") !== null;
}

/**
 * A state with undo / redo (the window editors). `set` makes a step; `setQuiet`
 * changes the value without one (e.g. while dragging, with a step made at the start).
 */
export function useUndoable<T>(initial: T) {
  const [value, setValue] = useState<T>(initial);
  const past = useRef<T[]>([]);
  const future = useRef<T[]>([]);
  const current = useRef(value);
  current.current = value;
  const set = useCallback((next: T | ((v: T) => T)) => {
    const v = typeof next === "function" ? (next as (v: T) => T)(current.current) : next;
    if (same(v, current.current)) return;
    past.current.push(current.current);
    future.current = [];
    setValue(v);
  }, []);
  const setQuiet = useCallback((next: T | ((v: T) => T)) => {
    setValue((old) => (typeof next === "function" ? (next as (v: T) => T)(old) : next));
  }, []);
  /** Remember the present value as a step (call when a drag starts). */
  const mark = useCallback(() => { past.current.push(current.current); future.current = []; }, []);
  /** Start over (another file or window was loaded): no steps to undo. */
  const reset = useCallback((v: T) => { past.current = []; future.current = []; setValue(v); }, []);
  const undo = useCallback(() => {
    const prev = past.current.pop();
    if (prev === undefined) return;
    future.current.push(current.current);
    setValue(prev);
  }, []);
  const redo = useCallback(() => {
    const next = future.current.pop();
    if (next === undefined) return;
    past.current.push(current.current);
    setValue(next);
  }, []);
  return { value, set, setQuiet, mark, reset, undo, redo };
}
