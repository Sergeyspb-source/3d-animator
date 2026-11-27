// Models → Release: what is in export (the game takes it from there), newest first, filtered by category. It opens on
// the model released last from Check; the draft worked on in Check, while it is not released, is named on top.
import { useEffect, useState } from 'react';
import { Alert, Button, ScrollArea, Select, Stack, Text } from '@mantine/core';
import { IconFolder } from '@tabler/icons-react';
import { fileUrl, get, live, post, useStore, type ModelInfo } from '../api';
import { useT } from '../i18n';
import Viewer3D from '../components/Viewer3D';
import { CAT_KEY, ModelFacts, ModelList } from './ModelCheck';
import type { Route } from '../nav';
import { ZoomImage } from '../components/Zoom';

const stored = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };

export default function ModelRelease({ go }: { go: (r: Route) => void }) {
  const t = useT();
  const finished = useStore(live, (s) => s.finished);
  const [items, setItems] = useState<ModelInfo[]>([]);
  const [cat, setCat] = useState('all');
  const [sel, setSel] = useState<string | null>(() => stored('sf3d.release_sel'));
  const [drafts, setDrafts] = useState<ModelInfo[]>([]);
  useEffect(() => { get<ModelInfo[]>('/api/models/released').then(setItems); get<ModelInfo[]>('/api/models/drafts').then(setDrafts).catch(() => setDrafts([])); }, [finished]);
  const checking = stored('sf3d.check_sel');
  const draft = drafts.find((d) => `${d.category}/${d.stem}` === checking) ?? null;   // (the one worked on in Check, not released yet)
  const shown = items.filter((m) => cat === 'all' || m.category === cat);
  const m = shown.find((x) => `${x.category}/${x.stem}` === sel) || shown[0];
  return (
    <div className="work three">
      <div className="side">
        <Select size="xs" m={6} value={cat} onChange={(v) => setCat(v || 'all')} allowDeselect={false} aria-label={t('ui.category_2')}
          data={[{ value: 'all', label: t('web.all') }, ...Object.keys(CAT_KEY).map((k) => ({ value: k, label: t('web.cat_short_' + k) }))]} />
        {draft && (
          <Alert m={6} p="xs" color="yellow" variant="light">
            <Text size="xs">{t('web.release_still_draft', draft.stem)}</Text>
            <Button size="compact-xs" mt={6} variant="default" onClick={() => go({ section: 'models', step: 'check' })}>{t('web.release_to_check')}</Button>
          </Alert>)}
        <ModelList items={shown} sel={m ? `${m.category}/${m.stem}` : null} onPick={(x) => setSel(`${x.category}/${x.stem}`)} empty={t('web.no_released')} />
      </div>
      <div className="stage"><Viewer3D url={m ? fileUrl(m.glb, m.time) : null} empty={t('web.no_released')} person /></div>
      <ScrollArea className="panel">
        {m && (
          <Stack gap="sm" p="sm">
            <div><div className="panel-title">{m.stem}</div><div className="field-note">{t(CAT_KEY[m.category] || m.category)}, {new Date(m.time * 1000).toLocaleString()}</div></div>
            <ModelFacts m={m} />
            {m.preview && <ZoomImage src={m.preview} url={fileUrl(m.preview, m.time)} caption={t('web.zoom_views')} radius="sm" />}
            <div className="field-note">{m.files.join(', ')}</div>
            <Button variant="default" leftSection={<IconFolder size={16} />} onClick={() => post('/api/open', { path: m.dir })}>{t('ui.char_open_folder')}</Button>
            <Text size="xs" c="dimmed">{t('web.release_game_note')}</Text>
          </Stack>)}
      </ScrollArea>
    </div>
  );
}
