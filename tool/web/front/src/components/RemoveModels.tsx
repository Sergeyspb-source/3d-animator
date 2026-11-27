// Deleting models (web/remove.py): askRemove([{id: '<category>/<name>', draft}]) from any list; <RemoveHost /> once
// in the app asks first - every path each model takes and their size, a task working on one (that one is left), the
// game's own copy (it stays: the game is never touched) - then sends it all to the Windows Recycle Bin and reads the
// lists and the current object again. <ObjectsChecklist> is the objects' list with ticks for the overviews.
import { useEffect, useState } from 'react';
import { Alert, Badge, Button, Checkbox, Group, Loader, Modal, ScrollArea, Stack, Text, UnstyledButton } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconTrash } from '@tabler/icons-react';
import { live, post, type SceneObject } from '../api';
import { useT } from '../i18n';
import { useObjects } from '../objects';

export interface RemoveItem { id: string; draft: boolean }
interface PlanItem extends RemoveItem { busy: string | null; bytes: number; paths: { path: string; bytes: number; dir: boolean }[]; game: string[] }
const EV = 'sf3d-remove';

export function askRemove(items: RemoveItem[], done?: (removed: string[]) => void) {
  if (items.length) window.dispatchEvent(new CustomEvent(EV, { detail: { items, done } }));
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const u = ['KB', 'MB', 'GB'];
  let v = n / 1024, i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${u[i]}`;
}

export function RemoveHost() {
  const t = useT();
  const objs = useObjects();
  const [req, setReq] = useState<{ items: RemoveItem[]; done?: (r: string[]) => void } | null>(null);
  const [plan, setPlan] = useState<{ items: PlanItem[]; bytes: number } | null>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent).detail;
      setReq(d); setPlan(null); setErr('');
      post<{ items: PlanItem[]; bytes: number }>('/api/models/remove/plan', { items: d.items }).then(setPlan).catch((x) => setErr(String(x.message || x)));
    };
    window.addEventListener(EV, on);
    return () => window.removeEventListener(EV, on);
  }, []);
  const close = () => { if (!busy) setReq(null); };
  const ready = plan ? plan.items.filter((x) => !x.busy && x.paths.length) : [];
  const bytes = ready.reduce((a, x) => a + x.bytes, 0);
  const go = async () => {
    setBusy(true);
    try {
      const r = await post<{ ok: boolean; done: string[]; left: string[]; log: string }>('/api/models/remove', { items: ready.map(({ id, draft }) => ({ id, draft })) });
      notifications.show({ color: r.ok ? 'teal' : 'yellow', title: t('web.rm_title'), message: r.log, autoClose: r.ok ? 5000 : false });
      live.set((s) => ({ ...s, objects: s.objects + 1, finished: s.finished + 1 }));   // (this page's lists at once; the server tells the others)
      objs.refresh();
      req?.done?.(r.done);
      setReq(null);
    } catch (x: any) { setErr(String(x.message || x)); } finally { setBusy(false); }
  };
  return (
    <Modal opened={!!req} onClose={close} size="xl" centered title={<Group gap={8}><IconTrash size={18} /><Text fw={700}>{t('web.rm_title')}</Text></Group>}>
      {!plan && !err && <Group gap={8} p="md"><Loader size="sm" /><Text size="sm">{t('web.rm_counting')}</Text></Group>}
      {err && <Alert color="red" variant="light">{err}</Alert>}
      {plan && (
        <Stack gap="sm">
          <Text size="sm">{t('web.rm_intro')}</Text>
          <ScrollArea.Autosize mah="52vh">
            <Stack gap="sm" className="rm-list">
              {plan.items.map((x) => (
                <div key={`${x.id}|${x.draft}`} className={'rm-item' + (x.busy || !x.paths.length ? ' off' : '')}>
                  <Group justify="space-between" wrap="nowrap">
                    <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                      <Text fw={700} size="sm" truncate>{x.id.split('/').slice(1).join('/')}</Text>
                      <Badge size="xs" variant="light" color={x.draft ? 'gray' : 'patina'}>{t(x.draft ? 'web.rm_draft' : 'web.rm_released')}</Badge>
                    </Group>
                    <Text size="sm" c="dimmed" style={{ flex: 'none' }}>{fmtBytes(x.bytes)}</Text>
                  </Group>
                  {x.busy && <Text size="xs" c="red">{t('web.rm_busy_note', x.busy)}</Text>}
                  {!x.paths.length && <Text size="xs" c="dimmed">{t('web.rm_none_note')}</Text>}
                  {x.game.length > 0 && <Text size="xs" c="yellow">{t('web.rm_game_note')} {x.game.join(', ')}</Text>}
                  {x.paths.map((p) => (
                    <Group key={p.path} justify="space-between" wrap="nowrap" gap={8} className="rm-path">
                      <Text size="xs" ff="monospace" style={{ wordBreak: 'break-all' }}>{p.path}{p.dir ? '/' : ''}</Text>
                      <Text size="xs" c="dimmed" style={{ flex: 'none' }}>{fmtBytes(p.bytes)}</Text>
                    </Group>))}
                </div>))}
            </Stack>
          </ScrollArea.Autosize>
          <Text size="xs" c="dimmed">{t('web.rm_bin_note')}</Text>
          <Group justify="space-between">
            <Text size="sm" fw={600}>{t('web.rm_total', ready.length, fmtBytes(bytes))}</Text>
            <Group gap={8}>
              <Button variant="default" onClick={close} disabled={busy}>{t('web.cancel')}</Button>
              <Button color="rust" leftSection={<IconTrash size={16} />} onClick={go} loading={busy} disabled={!ready.length}>{t('web.rm_go', ready.length)}</Button>
            </Group>
          </Group>
        </Stack>)}
    </Modal>
  );
}

// the characters' or creatures' list with ticks: delete several at once (an overview's «Manage the list»)
export function ObjectsChecklist({ list }: { list: SceneObject[] }) {
  const t = useT();
  const [on, setOn] = useState<Set<string>>(new Set());
  const ids = list.map((x) => x.id);
  useEffect(() => { setOn((s) => new Set([...s].filter((x) => ids.includes(x)))); }, [ids.join('|')]); // eslint-disable-line react-hooks/exhaustive-deps
  const flip = (id: string) => setOn((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  return (
    <Stack gap={4}>
      <Group justify="space-between">
        <Checkbox size="xs" label={t('web.rm_all')} checked={on.size > 0 && on.size === list.length} indeterminate={on.size > 0 && on.size < list.length}
          onChange={() => setOn(on.size === list.length ? new Set() : new Set(ids))} />
        <Button size="compact-xs" color="rust" variant="light" leftSection={<IconTrash size={14} />} disabled={!on.size}
          onClick={() => askRemove([...on].map((id) => ({ id, draft: false })), () => setOn(new Set()))}>{t('web.rm_some', on.size)}</Button>
      </Group>
      {list.map((x) => (
        <UnstyledButton key={x.id} className="ov-row" onClick={() => flip(x.id)}>
          <Group gap={8} wrap="nowrap"><Checkbox size="xs" checked={on.has(x.id)} onChange={() => flip(x.id)} onClick={(e) => e.stopPropagation()} aria-label={x.name} />
            <Text size="sm" truncate style={{ flex: 1 }}>{x.name}</Text><Text size="xs" c="dimmed">{x.tags}</Text></Group>
        </UnstyledButton>))}
    </Stack>
  );
}
