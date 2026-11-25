// The current object (a character or a creature): chosen once on top, every step of its sections works on it.
// It is the handler modules' «current character» too (work_dir/current_character.txt).
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { Group, Text, UnstyledButton } from '@mantine/core';
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

// the characters (or the creatures) to pick with a click, for a step opened with none of its kind chosen
export function PickList({ creatures }: { creatures?: boolean }) {
  const o = useObjects();
  return <>{(creatures ? o.creatures : o.characters).map((x) => (
    <UnstyledButton key={x.id} className="ov-row" onClick={() => o.choose(x.id)}>
      <Group justify="space-between" wrap="nowrap"><Text size="sm" fw={600} truncate>{x.name}</Text><Text size="xs" c="dimmed">{x.tags}</Text></Group>
    </UnstyledButton>))}</>;
}
