// Models → Release: what is in export (the game takes it from there), newest first, filtered by category.
import { useEffect, useState } from 'react';
import { Button, Image, ScrollArea, Select, Stack, Text, Title } from '@mantine/core';
import { IconFolder } from '@tabler/icons-react';
import { fileUrl, get, live, post, useStore, type ModelInfo } from '../api';
import { useT } from '../i18n';
import Viewer3D from '../components/Viewer3D';
import { CAT_KEY, ModelFacts, ModelList } from './ModelCheck';

export default function ModelRelease() {
  const t = useT();
  const finished = useStore(live, (s) => s.finished);
  const [items, setItems] = useState<ModelInfo[]>([]);
  const [cat, setCat] = useState('all');
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => { get<ModelInfo[]>('/api/models/released').then(setItems); }, [finished]);
  const shown = items.filter((m) => cat === 'all' || m.category === cat);
  const m = shown.find((x) => `${x.category}/${x.stem}` === sel) || shown[0];
  return (
    <div className="work three">
      <div className="side">
        <Select size="xs" m={6} value={cat} onChange={(v) => setCat(v || 'all')} allowDeselect={false} aria-label={t('ui.category_2')}
          data={[{ value: 'all', label: t('web.all') }, ...Object.keys(CAT_KEY).map((k) => ({ value: k, label: t('web.cat_short_' + k) }))]} />
        <ModelList items={shown} sel={m ? `${m.category}/${m.stem}` : null} onPick={(x) => setSel(`${x.category}/${x.stem}`)} empty={t('web.no_released')} />
      </div>
      <div className="stage"><Viewer3D url={m ? fileUrl(m.glb, m.time) : null} empty={t('web.no_released')} person /></div>
      <ScrollArea className="panel">
        {m && (
          <Stack gap="sm" p="md">
            <Title order={4}>{m.stem}</Title>
            <Text size="xs" c="dimmed">{t(CAT_KEY[m.category] || m.category)} · {new Date(m.time * 1000).toLocaleString()}</Text>
            <ModelFacts m={m} />
            {m.preview && <Image src={fileUrl(m.preview, m.time)} radius="sm" />}
            <Text size="xs" c="dimmed">{m.files.join(' · ')}</Text>
            <Button variant="default" leftSection={<IconFolder size={16} />} onClick={() => post('/api/open', { path: m.dir })}>{t('ui.char_open_folder')}</Button>
            <Text size="xs" c="dimmed">{t('web.release_game_note')}</Text>
          </Stack>)}
      </ScrollArea>
    </div>
  );
}
