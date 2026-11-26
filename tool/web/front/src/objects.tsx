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
// whether a model works in the «Character» sections or in «Creatures» (a model may do both: one with no skeleton yet,
// a creature with a humanoid's skeleton); «creature» itself is only the group it is listed under
export const asCharacter = (o?: SceneObject | null): o is SceneObject => !!o && o.as_character;
export const asCreature = (o?: SceneObject | null): o is SceneObject => !!o && o.as_creature;

// the characters (or the creatures) to pick with a click, for a step opened with none of its kind chosen
export function PickList({ creatures }: { creatures?: boolean }) {
  const o = useObjects();
  return <>{[...o.characters, ...o.creatures].filter(creatures ? asCreature : asCharacter).map((x) => (
    <UnstyledButton key={x.id} className="ov-row" onClick={() => o.choose(x.id)}>
      <Group justify="space-between" wrap="nowrap"><Text size="sm" fw={600} truncate>{x.name}</Text><Text size="xs" c="dimmed">{x.tags}</Text></Group>
    </UnstyledButton>))}</>;
}
