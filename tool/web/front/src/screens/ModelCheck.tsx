// Models → Check: the drafts made here, each in 3D beside a 1.75 m person, its numbers and previews; «Release»
// moves it into export (a model already there goes aside to web_drafts/replaced), «Remove» puts the draft aside.
import { useEffect, useState } from 'react';
import { Badge, Button, Group, Image, Modal, ScrollArea, Stack, Table, Text, UnstyledButton } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconFolder, IconTrash } from '@tabler/icons-react';
import { fileUrl, get, live, post, useStore, type ModelInfo } from '../api';
import { useT } from '../i18n';
import type { Route } from '../nav';
import Viewer3D from '../components/Viewer3D';
import { ZoomImage } from '../components/Zoom';

export const CAT_KEY: Record<string, string> = { item: 'ui.inventory_item', prop: 'ui.prop_environment', building: 'ui.building',
  character: 'ui.character', vegetation: 'ui.vegetation_trees_bushes_grass' };
const ENGINE: Record<string, string> = { sf3d: 'SF3D', hunyuan: 'Hunyuan3D', trellis2: 'TRELLIS.2', trellis: 'TRELLIS.2' };

export function ModelList({ items, sel, onPick, empty }: { items: ModelInfo[]; sel: string | null; onPick: (m: ModelInfo) => void; empty: string }) {
  const t = useT();
  return (
    <ScrollArea className="list">
      <Stack gap={4} p={6}>
        {items.length === 0 && <Text size="sm" c="dimmed" p="sm">{empty}</Text>}
        {items.map((m) => {
          const id = `${m.category}/${m.stem}`;
          return (
            <UnstyledButton key={id} className={'list-item' + (sel === id ? ' on' : '')} onClick={() => onPick(m)}>
              <Group gap={8} wrap="nowrap">
                <div className="icon">{m.icon ? <Image src={fileUrl(m.icon, m.time)} w={40} h={40} fit="contain" /> : null}</div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <Text size="sm" fw={600} truncate>{m.stem}</Text>
                  <Text size="xs" c="dimmed" truncate>{t(CAT_KEY[m.category] || m.category)}</Text>
                </div>
                <Stack gap={3} align="flex-end">
                  <span className="tag">{ENGINE[m.engine] || m.engine}</span>
                  {m.in_export && <span className="tag warm">{t('web.in_export')}</span>}
                </Stack>
              </Group>
            </UnstyledButton>
          );
        })}
      </Stack>
    </ScrollArea>
  );
}

export function ModelFacts({ m }: { m: ModelInfo }) {
  const t = useT();
  const rows: [string, string][] = [
    [t('ui.faces_2'), m.faces != null ? m.faces.toLocaleString() : '—'],
    [t('ui.size_m'), m.size_m ? m.size_m.join(' × ') : '—'],
    [t('ui.seconds'), m.seconds != null ? String(m.seconds) : '—'],
    [t('web.engine'), ENGINE[m.engine] || m.engine],
    [t('web.peak_vram'), m.peak_vram_mb ? `${m.peak_vram_mb} MB` : '—'],
    [t('web.folder'), m.dir],
  ];
  return (
    <Table withRowBorders={false} verticalSpacing={2} horizontalSpacing={0} fz="sm">
      <Table.Tbody>{rows.map(([k, v]) => <Table.Tr key={k}><Table.Td c="dimmed" w={130}>{k}</Table.Td><Table.Td style={{ wordBreak: 'break-all' }}>{v}</Table.Td></Table.Tr>)}</Table.Tbody>
    </Table>
  );
}

export default function ModelCheck({ go }: { go: (r: Route) => void }) {
  const t = useT();
  const finished = useStore(live, (s) => s.finished);
  const [items, setItems] = useState<ModelInfo[]>([]);
  const [sel, setSel] = useState<string | null>(() => localStorage.getItem('sf3d.check_sel'));
  const [ask, setAsk] = useState<string | null>(null);   // the draft asked about (kept while the dialog fades)
  const [busy, setBusy] = useState(false);
  const [askAll, setAskAll] = useState(false);
  const load = () => get<ModelInfo[]>('/api/models/drafts').then((d) => {
    setItems(d);
    setSel((s) => (s && d.some((m) => `${m.category}/${m.stem}` === s) ? s : d[0] ? `${d[0].category}/${d[0].stem}` : null));
  });
  useEffect(() => { load(); }, [finished]); // eslint-disable-line react-hooks/exhaustive-deps
  const m = items.find((x) => `${x.category}/${x.stem}` === sel);
  const pick = (x: ModelInfo) => { const id = `${x.category}/${x.stem}`; setSel(id); localStorage.setItem('sf3d.check_sel', id); };

  const release = async (replace: boolean) => {
    if (!m) return;
    setBusy(true);
    try {
      const r = await post<{ ok: boolean; exists?: boolean; log: string }>('/api/models/release', { category: m.category, stem: m.stem, replace });
      if (r.exists) { setAsk(`${m.category}/${m.stem}`); return; }
      setAsk(null);
      notifications.show({ color: r.ok ? 'teal' : 'red', message: r.log });
      if (r.ok) { try { localStorage.setItem('sf3d.release_sel', `${m.category}/${m.stem}`); } catch { /* */ } load(); }   // (Release opens on it)
    } finally { setBusy(false); }
  };
  const discard = async () => {
    if (!m) return;
    const r = await post<{ ok: boolean; log: string }>('/api/models/discard', { category: m.category, stem: m.stem });
    notifications.show({ color: r.ok ? 'gray' : 'red', message: r.log });
    load();
  };

  return (
    <div className="work three">
      <div className="side">
        <Group justify="space-between" pr={6} wrap="nowrap"><div className="side-title">{t('web.drafts')}</div>
          {items.some((x) => !x.in_export) && <Button size="compact-xs" variant="subtle" color="gray" onClick={() => setAskAll(true)}>{t('web.release_all')}</Button>}</Group>
        <ModelList items={items} sel={sel} onPick={pick} empty={t('web.no_drafts')} />
      </div>
      <div className="stage">
        <Viewer3D url={m ? fileUrl(m.glb, m.time) : null} empty={t('web.check_empty')} person />
      </div>
      <ScrollArea className="panel">
        {m ? (
          <Stack gap="sm" p="sm">
            <div><div className="panel-title">{m.stem}</div><div className="field-note">{t(CAT_KEY[m.category] || m.category)}</div></div>
            <ModelFacts m={m} />
            {m.preview && <ZoomImage src={m.preview} url={fileUrl(m.preview, m.time)} group={[m.preview, m.source].filter(Boolean) as string[]} captions={[t('web.zoom_views'), t('web.source_picture')]} radius="sm" />}
            {m.source && <Group gap={8} align="flex-start"><ZoomImage src={m.source} group={[m.preview, m.source].filter(Boolean) as string[]} captions={m.preview ? [t('web.zoom_views'), t('web.source_picture')] : [t('web.source_picture')]} w={96} h={96} fit="contain" radius="sm" /><Text size="xs" c="dimmed">{t('web.source_picture')}</Text></Group>}
            {m.rigged && <Badge variant="light" color="patina">{t('web.has_skeleton')}</Badge>}
            <Button onClick={() => release(false)} loading={busy}>{t('web.release_btn')}</Button>
            <div className="field-note">{t('web.release_to', `export/${m.category}/${m.stem}/`)}</div>
            <Group grow>
              <Button variant="default" leftSection={<IconFolder size={16} />} onClick={() => post('/api/open', { path: m.dir })}>{t('ui.char_open_folder')}</Button>
              <Button variant="default" color="red" leftSection={<IconTrash size={16} />} onClick={discard}>{t('web.discard')}</Button>
            </Group>
            <Button variant="subtle" color="gray" onClick={() => go({ section: 'models', step: 'create' })}>{t('web.make_again')}</Button>
          </Stack>
        ) : <Text p="md" c="dimmed" size="sm">{t('web.no_drafts')}</Text>}
      </ScrollArea>
      <Modal opened={askAll} onClose={() => setAskAll(false)} title={t('web.release_all')} centered>
        <Stack>
          <Text size="sm">{t('web.release_all_text', items.filter((x) => !x.in_export).length)}</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setAskAll(false)}>{t('web.cancel')}</Button>
            <Button onClick={async () => { const r = await post<{ log: string }>('/api/models/release_all'); setAskAll(false); notifications.show({ color: 'patina', message: r.log }); load(); }}>{t('web.release_all')}</Button>
          </Group>
        </Stack>
      </Modal>
      <Modal opened={!!ask} onClose={() => setAsk(null)} title={t('web.replace_title')} centered>
        <Stack>
          <Text size="sm">{ask ? t('web.replace_text', `export/${ask}`) : ''}</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setAsk(null)}>{t('web.cancel')}</Button>
            <Button color="yellow" onClick={() => release(true)} loading={busy}>{t('web.replace_btn')}</Button>
          </Group>
        </Stack>
      </Modal>
    </div>
  );
}
