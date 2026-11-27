// Undo / redo, the same in every editor of the app: Ctrl+Z undoes, Ctrl+Shift+Z and Ctrl+Y redo (by the key's place,
// so any keyboard layout), ↶ ↷ buttons with the keys in their tooltip, greyed when there is nothing to undo; a drag, a
// slider's pull or a brush's stroke is one step; about 100 steps; another object starts the history anew. In a text
// field the keys stay the browser's: there they undo the typing.
// The three.js editors (tool/*.html, in frames) keep their own histories; when the app's page has the focus (a click on
// its panel), the keys are passed on to the editor shown as a message {type: 'sf3d-undo', redo}.
import { useEffect, useRef } from 'react';

export const UNDO_MAX = 100;

export function isTyping(t: EventTarget | null): boolean {
  const el = t as Element | null;
  return !!(el && el.closest && el.closest('input:not([type]), input[type=text], input[type=number], input[type=search], input[type=email], input[type=password], textarea, [contenteditable]'));
}

// 'undo' | 'redo' for the keys, else null (not those keys, or typing in a field)
export function undoKey(e: KeyboardEvent): 'undo' | 'redo' | null {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || (e.code !== 'KeyZ' && e.code !== 'KeyY') || isTyping(e.target)) return null;
  return e.code === 'KeyY' || e.shiftKey ? 'redo' : 'undo';
}

// the keys for a React editor while it is mounted (run sees the newest closure)
export function useUndoKeys(run: (redo: boolean) => void, on = true) {
  const cb = useRef(run);
  cb.current = run;
  useEffect(() => {
    if (!on) return;
    const kd = (e: KeyboardEvent) => { const k = undoKey(e); if (!k) return; e.preventDefault(); e.stopPropagation(); cb.current(k === 'redo'); };
    window.addEventListener('keydown', kd, true);
    return () => window.removeEventListener('keydown', kd, true);
  }, [on]);
}

// the app's page: the keys pressed on it (not in a field, not taken by a React editor) go to the editor frame on screen
export function useUndoToFrames() {
  useEffect(() => {
    const kd = (e: KeyboardEvent) => {
      const k = undoKey(e); if (!k || e.defaultPrevented) return;
      const f = [...document.querySelectorAll<HTMLIFrameElement>('iframe')].find((x) => x.offsetParent !== null && x.getClientRects().length);
      if (!f || !f.contentWindow) return;
      e.preventDefault();
      f.contentWindow.postMessage({ type: 'sf3d-undo', redo: k === 'redo' }, location.origin);
    };
    window.addEventListener('keydown', kd);
    return () => window.removeEventListener('keydown', kd);
  }, []);
}

// a history of snapshots of one value (an editor's state): mark(before) once per step (before the change), step(back)
// gives the value to put back or null; clear() for another object
export class Snapshots<T> {
  undo: T[] = [];
  redo: T[] = [];
  mark(before: T) { this.undo.push(before); if (this.undo.length > UNDO_MAX) this.undo.shift(); this.redo.length = 0; }
  step(back: boolean, now: T): T | null {
    const from = back ? this.undo : this.redo, to = back ? this.redo : this.undo;
    const x = from.pop();
    if (x === undefined) return null;
    to.push(now);
    return x;
  }
  clear() { this.undo.length = 0; this.redo.length = 0; }
}
