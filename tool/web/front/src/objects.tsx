// The current object (a character or a creature): chosen once on top, every step of its sections works on it.
// It is the Gradio app's «current character» too (work_dir/current_character.txt).
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { get, post, type SceneObject } from './api';

interface Objects {
  characters: SceneObject[]; creatures: SceneObject[]; current: string | null;
  choose: (id: string | null) => void; refresh: () => void;
}
const Ctx = createContext<Objects>({ characters: [], creatures: [], current: null, choose: () => {}, refresh: () => {} });

export function ObjectsProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<{ characters: SceneObject[]; creatures: SceneObject[]; current: string | null }>({ characters: [], creatures: [], current: null });
  const refresh = useCallback(() => { get<typeof data>('/api/objects').then(setData).catch(() => {}); }, []);
  useEffect(refresh, [refresh]);
  const choose = useCallback((id: string | null) => {
    setData((d) => ({ ...d, current: id }));
    if (id) post('/api/objects/current', { id }).catch(() => {});
  }, []);
  return <Ctx.Provider value={{ ...data, choose, refresh }}>{children}</Ctx.Provider>;
}
export const useObjects = () => useContext(Ctx);
export function useCurrent(): SceneObject | undefined {
  const o = useObjects();
  return [...o.characters, ...o.creatures].find((x) => x.id === o.current);
}
