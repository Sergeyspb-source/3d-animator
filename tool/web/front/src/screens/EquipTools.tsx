// Equipment → Workshop, the two other ways to a piece: «A finished piece (GLB)» — the markup editor's armour mode
// («Броня»: place a GLB piece on the character and put it on), and «Off a dressed model» — a dressed model split into
// segments, each given a slot, the set carried onto the character's body in parts.
import { useEffect, useState } from 'react';
import { Button, FileButton, Group, Image, ScrollArea, Select, Stack, Text, TextInput, useMantineColorScheme } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconUpload } from '@tabler/icons-react';
import { fileUrl, live, onTaskFinished, post, upload, useStore } from '../api';
import { plain, useT } from '../i18n';
import { asCharacter, useCurrent } from '../objects';
import EditorFrame from '../components/EditorFrame';

export function WearPanel({ ids }: { ids: string[] }) {
  const t = useT();
  const { colorScheme } = useMantineColorScheme();
  const cur = useCurrent();
  const id = asCharacter(cur) ? cur.id : undefined;
  if (!id) return <div className="placeholder"><Text c="ember.3">{t('web.need_character')}</Text></div>;
  return <EditorFrame src={`/editor/wear?id=${encodeURIComponent(id)}&theme=${colorScheme}`} fields={[ids[0], ids[2]]} title={t('web.eq_ready_glb')}
    go={[{ id: ids[1], field: ids[0], onGo: (text) => post('/api/char/wear', JSON.parse(text)) }]} />;
}

interface Seg { name: string; slot: string; title: string }

export function OutfitPanel() {
  const t = useT();
  const cur = useCurrent();
  const id = asCharacter(cur) ? cur.id : undefined;
  const [model, setModel] = useState<{ name: string; path: string } | null>(null);
  const [scan, setScan] = useState<{ log: string; pics: { path: string; caption: string }[]; segs: Seg[]; set_name: string; slots: string[] } | null>(null);
  const [busyScan, setBusyScan] = useState(false);
  const [result, setResult] = useState<{ path: string; caption: string }[]>([]);
  const running = useStore(live, (s) => Object.values(s.tasks).some((x) => x.meta?.what === 'outfit' && (x.status === 'running' || x.status === 'queued')));
  useEffect(() => onTaskFinished((tk) => {
    if (tk.meta?.what !== 'outfit') return;
    if (tk.status === 'done') { setResult(tk.result?.pics || []); notifications.show({ color: 'patina', message: tk.title }); }
    if (tk.status === 'error') notifications.show({ color: 'rust', title: tk.title, message: tk.error || '' });
  }), []);
  if (!id) return <div className="placeholder"><Text c="ember.3">{t('web.need_character')}</Text></div>;
  const doScan = async (m: { name: string; path: string }) => {
    setBusyScan(true);
    try { setScan(await post('/api/outfit/scan', { model: m.path })); } finally { setBusyScan(false); }
  };
  const pics = result.length ? result : scan?.pics || [];
  return (
    <div className="work two" style={{ flex: 1 }}>
      <ScrollArea className="stage plainstage">
        {pics.length ? <div className="gallery-grid">{pics.map((p) => (
          <div key={p.path} className="gal-item"><Image src={fileUrl(p.path)} fit="contain" radius="sm" /><Text size="xs" c="dimmed" ta="center" truncate>{p.caption}</Text></div>))}</div>
          : <Text className="viewer-empty">{plain(t('ui.generate_the_same_character_in_the'))}</Text>}
      </ScrollArea>
      <ScrollArea className="panel"><Stack gap="sm" p="sm">
        <div className="panel-title">{t('web.eq_outfit')}</div>
        <FileButton accept=".glb" onChange={async (f) => { if (!f) return; const [u] = await upload([f]); setModel(u); setScan(null); setResult([]); doScan(u); }}>
          {(b) => <Button {...b} variant="default" leftSection={<IconUpload size={16} />} loading={busyScan}>{model ? model.name : t('ui.glb_of_the_dressed_model_with')}</Button>}
        </FileButton>
        {scan && <div className="field-note">{plain(scan.log)}</div>}
        {scan && <TextInput label={t('ui.set_name_folder_in_equipment')} value={scan.set_name} onChange={(e) => setScan({ ...scan, set_name: e.currentTarget.value })} />}
        {scan?.segs.map((s, i) => (
          <Select key={s.name} size="xs" label={s.title} value={s.slot} allowDeselect={false} data={scan.slots}
            onChange={(v) => setScan({ ...scan, segs: scan.segs.map((x, k) => (k === i ? { ...x, slot: v || x.slot } : x)) })} />))}
        {scan && (
          <Group>
            <Button disabled={running || !cur?.parts} onClick={() => post('/api/outfit/run', { id, model: model!.path, set_name: scan.set_name, names: scan.segs.map((s) => s.name), slots: scan.segs.map((s) => s.slot) })}>
              {t('ui.transfer_the_set')}</Button>
          </Group>)}
        {!cur?.parts && <div className="field-note">{t('web.outfit_needs_parts')}</div>}
      </Stack></ScrollArea>
    </div>
  );
}
