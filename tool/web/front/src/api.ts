// The server's API (tool/web/server.py) and the live events from it.
import { useSyncExternalStore } from 'react';

export type TaskStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled';
export interface TaskSummary {
  id: string; kind: string; title: string; status: TaskStatus; gpu: boolean;
  created: number; started: number | null; finished: number | null;
  progress: number | null; result: any; error: string | null; meta: Record<string, any>; last: string;
}
export interface Gpu { used: number | null; total: number | null; free: number | null; util: number | null; sf3d: boolean }
export interface AppState {
  lang: string; langs: Record<string, string>; test_bench: boolean;
  export_dir: string; work_dir: string; input_dir?: string; drafts_dir: string; gradio: string;
  has_openrouter_key: boolean; gpu: Gpu; tasks: TaskSummary[]; bridges: { equip: [string, string]; markup: string; pose: string; rigface: string; creature: [string, string]; paint: [string, string] };
}
export interface SceneObject {
  id: string; name: string; creature: boolean; dir: string; rigged: string | null; source: string | null;
  landmark: boolean; auto: boolean; parts: boolean; speech: number; worn: number; tags: string;
}
export interface ModelInfo {
  stem: string; category: string; draft: boolean; glb: string; dir: string; time: number; stats: Record<string, any>;
  faces?: number; size_m?: number[]; seconds?: number; peak_vram_mb?: number | null; engine: string; icon: string | null; preview: string | null;
  source: string | null; rigged: string | null; files: string[]; in_export?: boolean;
}

async function check(r: Response) {
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = j.detail || j.error || msg; } catch { /* (not JSON) */ }
    throw new Error(msg);
  }
  return r.json();
}
export const get = <T,>(url: string): Promise<T> => fetch(url, { cache: 'no-store' }).then(check);
export const post = <T,>(url: string, body?: unknown): Promise<T> =>
  fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) }).then(check);

export async function upload(files: File[]): Promise<{ name: string; path: string }[]> {
  const fd = new FormData();
  files.forEach((f) => fd.append('files', f, f.name));
  return fetch('/api/upload', { method: 'POST', body: fd }).then(check);
}
export const fileUrl = (path: string, v?: number | string) =>
  `/api/file?path=${encodeURIComponent(path)}${v !== undefined ? `&v=${encodeURIComponent(String(v))}` : ''}`;

// ------------------------------------------------------------------ a tiny store (no extra library)
export function createStore<T>(init: T) {
  let state = init;
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    set(fn: (s: T) => T) { state = fn(state); listeners.forEach((l) => l()); },
    subscribe(l: () => void) { listeners.add(l); return () => { listeners.delete(l); }; },
  };
}
export function useStore<T, U>(store: ReturnType<typeof createStore<T>>, sel: (s: T) => U): U {
  return useSyncExternalStore(store.subscribe, () => sel(store.get()));
}

interface Live {
  connected: boolean;
  tasks: Record<string, TaskSummary>;
  logs: Record<string, string[]>;
  gpu: Gpu;
  finished: number;           // grows whenever a task ends (lists refresh on it)
  selected: string | null;    // the task whose log the dock shows
}
export const live = createStore<Live>({
  connected: false, tasks: {}, logs: {}, gpu: { used: null, total: null, free: null, util: null, sf3d: false },
  finished: 0, selected: null,
});
const ended = (t?: TaskSummary) => !!t && ['done', 'error', 'cancelled'].includes(t.status);
type Finish = (t: TaskSummary) => void;
const finishers = new Set<Finish>();
export function onTaskFinished(fn: Finish) { finishers.add(fn); return () => { finishers.delete(fn); }; }

export function connect() {
  let es: EventSource | null = null;
  const open = () => {
    es = new EventSource('/api/events');
    es.onopen = () => live.set((s) => ({ ...s, connected: true }));
    es.onerror = () => live.set((s) => ({ ...s, connected: false }));
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (ev.type === 'hello') {
        const tasks: Record<string, TaskSummary> = {};
        for (const t of ev.tasks as TaskSummary[]) tasks[t.id] = t;
        live.set((s) => ({ ...s, tasks, gpu: ev.gpu, connected: true }));
      } else if (ev.type === 'task') {
        const t = ev.task as TaskSummary;
        const was = live.get().tasks[t.id];
        const fin = ended(t) && !ended(was);
        live.set((s) => {
          // the dock follows the task that runs, unless another one the user picked still runs
          const sel = s.selected ? s.tasks[s.selected] : undefined;
          const keep = sel && sel.status === 'running' && sel.id !== t.id;
          return { ...s, tasks: { ...s.tasks, [t.id]: t }, finished: s.finished + (fin ? 1 : 0),
            selected: t.status === 'running' && !keep ? t.id : s.selected };
        });
        if (fin) finishers.forEach((f) => f(t));
      } else if (ev.type === 'log') {
        live.set((s) => {
          const old = s.logs[ev.id] || [];
          return { ...s, logs: { ...s.logs, [ev.id]: old.slice(0, ev.at).concat(ev.lines) } };
        });
      } else if (ev.type === 'gpu') {
        live.set((s) => ({ ...s, gpu: ev.gpu }));
      }
    };
  };
  open();
  return () => es?.close();
}

export async function loadLog(id: string) {
  const t = await get<TaskSummary & { lines: string[] }>(`/api/tasks/${id}`);
  live.set((s) => ({ ...s, logs: { ...s.logs, [id]: t.lines } }));
}
