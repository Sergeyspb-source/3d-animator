// Character → Weights (Robust Weight Transfer: the armpits' weights redone locally, a new model beside the old one)
// and Character → To the game (the Godot fitting room with every piece and clip).
import { useEffect, useState } from 'react';
import { Button, Group, ScrollArea, SegmentedControl, Slider, Stack, Text, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconFolder } from '@tabler/icons-react';
import { fileUrl, live, onTaskFinished, post, useStore } from '../api';
import { useT } from '../i18n';
import { useCurrent } from '../objects';
import type { Route } from '../nav';
import Viewer3D from '../components/Viewer3D';
import { useOverview } from './CharOverview';

export function CharWeights({ creature = false }: { creature?: boolean }) {
  const t = useT();
  const cur = useCurrent();
  const id = cur && cur.creature === creature ? cur.id : undefined;
  const [mesh, setMesh] = useState('');
  const [region, setRegion] = useState('auto');
  const [group, setGroup] = useState('');
  const [strength, setStrength] = useState(1);
  const [size, setSize] = useState(1);
  const [result, setResult] = useState<{ model: string; files: string[] } | null>(null);
  const running = useStore(live, (s) => Object.values(s.tasks).some((x) => x.kind === 'char' && x.meta?.char === id && (x.status === 'running' || x.status === 'queued')));
  useEffect(() => { setResult(null); }, [id]);
  useEffect(() => onTaskFinished((tk) => {
    if (tk.kind !== 'char' || tk.meta?.char !== id || tk.meta?.what !== 'weights') return;
    if (tk.status === 'done' && tk.result?.model) setResult(tk.result);
    if (tk.status === 'error') notifications.show({ color: 'rust', title: tk.title, message: tk.error || '' });
  }), [id]);
  if (!id) return <div className="placeholder"><Text c="ember.3">{t(creature ? 'web.need_creature' : 'web.need_character')}</Text></div>;
  const go = () => post('/api/char/weights', { id, mesh, group: region === 'group' ? group : '', strength, size });
  return (
    <div className="work two">
      <div className="stage"><Viewer3D url={result ? fileUrl(result.model, Date.now()) : cur?.rigged ? fileUrl(cur.rigged) : null} empty={t('web.ov_no_model')} person /></div>
      <ScrollArea className="panel">
        <Stack gap="sm" p="sm">
          <div className="panel-title">{t('web.step_weights')}</div>
          <div className="field-note">{t('rwt.smooths_the_armpit_weights_locally')}</div>
          <div className="field-note">{t('rwt.when_the_arms_are_raised_the')}</div>
          <TextInput size="sm" label={t('rwt.mesh_name_empty_the_body_with_finger')} value={mesh} onChange={(e) => setMesh(e.currentTarget.value)} />
          <div>
            <Text size="sm" fw={500} mb={4}>{t('rwt.how_to_choose_the_region')}</Text>
            <SegmentedControl fullWidth size="xs" value={region} onChange={setRegion}
              data={[{ value: 'auto', label: t('rwt.armpits_by_bones_experiment') }, { value: 'group', label: t('rwt.vertex_group_from_blender') }]} />
          </div>
          {region === 'group' && <TextInput size="sm" label={t('rwt.mask_group_name_for_blend_weight')} value={group} onChange={(e) => setGroup(e.currentTarget.value)} />}
          <Text size="xs">{t('rwt.correction_strength')}: {strength.toFixed(2)}</Text>
          <Slider min={0} max={1} step={0.05} value={strength} onChange={setStrength} />
          <Text size="xs">{t('rwt.size_of_the_automatic_region')}: {size.toFixed(2)}</Text>
          <Slider min={0.5} max={1.5} step={0.05} value={size} onChange={setSize} />
          <Button onClick={go} disabled={running || (region === 'group' && !group.trim())}>{t('rwt.recompute_the_chosen_region_in_a_new')}</Button>
          {result && <>
            <Text size="sm" fw={600} mt="sm">{t('rwt.result_glb_blender_report')}</Text>
            {result.files.map((f) => <div key={f} className="field-note">{f}</div>)}
            <Button variant="default" leftSection={<IconFolder size={16} />} onClick={() => post('/api/open', { path: result.model })}>{t('ui.char_open_folder')}</Button>
          </>}
        </Stack>
      </ScrollArea>
    </div>
  );
}

export function CharGame({ go }: { go: (r: Route) => void }) {
  const t = useT();
  const cur = useCurrent();
  const id = cur && !cur.creature ? cur.id : undefined;
  const o = useOverview(id);
  const running = useStore(live, (s) => Object.values(s.tasks).some((x) => x.kind === 'char' && x.meta?.what === 'wardrobe' && (x.status === 'running' || x.status === 'queued')));
  if (!id) return <div className="placeholder"><Text c="ember.3">{t('web.need_character')}</Text></div>;
  return (
    <div className="work two">
      <div className="stage"><Viewer3D url={o?.rigged ? fileUrl(o.rigged) : null} empty={t('web.ov_no_model')} person /></div>
      <ScrollArea className="panel">
        <Stack gap="sm" p="sm">
          <div className="panel-title">{t('web.step_game')}</div>
          <div className="field-note">{t('web.game_intro')}</div>
          <Button onClick={() => post('/api/char/wardrobe', { id })} disabled={running || !o?.rigged}>{t('ed.fitting_room_in_godot')}</Button>
          <div className="field-note">{o ? t('web.ov_worn', o.worn) : ''}</div>
          <Group grow>
            <Button variant="default" onClick={() => go({ section: 'equipment', step: 'workshop' })}>{t('web.sec_equipment')}</Button>
            {o && <Button variant="default" leftSection={<IconFolder size={16} />} onClick={() => post('/api/open', { path: o.dir })}>{t('ui.char_open_folder')}</Button>}
          </Group>
          <div className="field-note">{t('web.game_files_note')}</div>
        </Stack>
      </ScrollArea>
    </div>
  );
}
