// Character → Skeleton: four ways at it on the current character — automatic (UniRig, with the seams and the body
// split in parts), by landmarks (the markup editor, then the build), the pose and the fist (any skeleton), the bones
// and their weights (a viewer). Long jobs go into the shared task queue.
import { useEffect, useRef, useState } from 'react';
import { Button, Group, Kbd, NumberInput, Popover, ScrollArea, SegmentedControl, Select, Slider, Stack, Switch, Text, useMantineColorScheme } from '@mantine/core';
import { useHotkeys, useLocalStorage } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconAdjustments } from '@tabler/icons-react';
import { fileUrl, get, live, onTaskFinished, post, useStore, type TaskSummary } from '../api';
import { plain, useT } from '../i18n';
import { asCharacter, useCurrent, useObjects } from '../objects';
import EditorFrame, { fieldValue } from '../components/EditorFrame';
import Viewer3D from '../components/Viewer3D';
import { useOverview } from './CharOverview';

type Mode = 'auto' | 'markup' | 'pose' | 'bones';
interface Opts { naming: string; weld: boolean; mouth: string; eyes: boolean; eye_colour: boolean; face_topo: boolean; face_smooth: number; kit: string; kits: { value: string; label: string }[] }

function useCharTask(id: string | undefined, onDone: (t: TaskSummary) => void) {
  const cb = useRef(onDone);
  cb.current = onDone;
  useEffect(() => onTaskFinished((tk) => { if (tk.kind === 'char' && tk.meta?.char === id) cb.current(tk); }), [id]);
}

export default function CharSkeleton({ bridges }: { bridges: { markup: string; pose: string } }) {
  const t = useT();
  const { colorScheme } = useMantineColorScheme();
  const cur = useCurrent();
  const objs = useObjects();
  const id = asCharacter(cur) ? cur.id : undefined;
  const o = useOverview(id);
  const [mode, setMode] = useLocalStorage<Mode>({ key: 'sf3d.rig_mode', defaultValue: 'markup' });
  const [naming, setNaming] = useLocalStorage({ key: 'sf3d.rig_naming', defaultValue: 'mixamo' });
  const [tries, setTries] = useLocalStorage({ key: 'sf3d.rig_tries', defaultValue: 3 });
  const [opts, setOpts] = useState<Opts | null>(null);
  const [pageMode, setPageMode] = useState<'markup' | 'pose'>('markup');
  const [v, setV] = useState(0);   // a new frame after a build
  const [hasMarkup, setHasMarkup] = useState(false);
  const [note, setNote] = useState('');
  const fistTimer = useRef(0);
  const running = useStore(live, (s) => Object.values(s.tasks).some((x) => x.kind === 'char' && x.meta?.char === id && (x.status === 'running' || x.status === 'queued')));

  useEffect(() => { get<Opts>('/api/char/options').then(setOpts); }, []);
  useEffect(() => { setPageMode('markup'); setHasMarkup(false); setNote(''); }, [id]);
  useCharTask(id, (tk) => {
    objs.refresh();
    if (tk.status === 'error') notifications.show({ color: 'rust', title: tk.title, message: tk.error || '' });
    else if (tk.status === 'done') notifications.show({ color: 'patina', message: tk.title });
    if (tk.meta?.what === 'landmarks' && tk.status === 'done') { setPageMode('pose'); setV(Date.now()); }
  });

  const setOpt = async (patch: Partial<Opts>) => {
    const next = { ...opts!, ...patch, ...(patch.mouth && patch.mouth !== 'cut' ? { face_topo: false } : {}) };
    setOpts(next);
    setOpts(await post<Opts>('/api/char/options', next));
  };
  const build = async () => {
    const markup = fieldValue(bridges.markup);
    if (!id || !markup) return;
    await post('/api/char/landmark_build', { id, markup, options: opts });
  };
  const job = (path: string, body: object) => async () => { if (id) await post(path, { id, ...body }); };
  useHotkeys([['mod+Enter', () => { if (mode === 'markup') build(); }]], []);

  const onField = (fid: string, value: string) => {   // the markup / the pose sent by the editor: the fist kept at once
    if (fid === bridges.markup) setHasMarkup(!!value);
    window.clearTimeout(fistTimer.current);
    fistTimer.current = window.setTimeout(async () => {
      const r = await post<{ ok: boolean; log?: string }>('/api/char/keep_fist', { id, markup: value, rig: fid === bridges.pose });
      if (r.log) setNote(r.log);
    }, 800);
  };

  if (!id) return <div className="placeholder"><Text c="ember.3">{t('web.need_character')}</Text></div>;
  const q = `id=${encodeURIComponent(id)}&theme=${colorScheme}&v=${v}`;
  const head = (
    <Group className="equip-head" gap="md" wrap="nowrap">
      <SegmentedControl size="xs" value={mode} onChange={(m) => setMode(m as Mode)} data={[
        { value: 'markup', label: t('web.rig_markup') }, { value: 'auto', label: t('web.rig_auto') },
        { value: 'pose', label: t('web.rig_pose'), disabled: !cur?.rigged }, { value: 'bones', label: t('web.rig_bones'), disabled: !cur?.rigged }]} />
      <Text size="xs" c="dimmed" truncate style={{ flex: 1 }}>
        {mode === 'markup' ? t(pageMode === 'pose' ? 'web.rig_markup_pose' : 'web.rig_markup_hint') : mode === 'pose' ? note || plain(t('lm.rig_pose_info')) : mode === 'bones' ? plain(t('cr.view_any_info')) : ''}
      </Text>
      {mode === 'markup' && opts && <>
        {pageMode === 'pose' && <Button size="compact-sm" variant="subtle" color="gray" onClick={() => setPageMode('markup')}>{t('web.rig_back_to_markup')}</Button>}
        <Popover position="bottom-end" width={360} shadow="md">
          <Popover.Target><Button size="compact-sm" variant="default" leftSection={<IconAdjustments size={14} />}>{t('lm.build_options')}</Button></Popover.Target>
          <Popover.Dropdown>
            <Stack gap="xs">
              <Select size="xs" label={t('lm.bone_names')} value={opts.naming} allowDeselect={false} onChange={(x) => x && setOpt({ naming: x })}
                data={[{ value: 'mixamo', label: t('lm.mixamo_for_mixamo_animations') }, { value: 'godot', label: t('lm.godot_humanoid_profile') }]} />
              <Switch size="xs" label={t('lm.stitch_the_seams_between_parts')} checked={opts.weld} onChange={(e) => setOpt({ weld: e.currentTarget.checked })} />
              <Select size="xs" label={t('lm.speech_mouth_if_the_face_is_marked')} value={opts.mouth} allowDeselect={false} onChange={(x) => x && setOpt({ mouth: x })}
                data={[{ value: 'cut', label: t('lm.cut_lips_cavity_teeth_tongue') }, { value: 'plate', label: t('lm.plate_fast_for_distant_shots') }, { value: 'none', label: t('fbx.none') }]} />
              <Switch size="xs" label={t('lm.insert_eyeballs_if_the_eyes_are')} checked={opts.eyes} onChange={(e) => setOpt({ eyes: e.currentTarget.checked })} />
              <Switch size="xs" label={t('lm.iris_colour_from_the_model_s_painted')} checked={opts.eye_colour} onChange={(e) => setOpt({ eye_colour: e.currentTarget.checked })} />
              <Switch size="xs" label={t('lm.face_retopology_an_even_mesh_around')} checked={opts.face_topo} disabled={opts.mouth !== 'cut'} onChange={(e) => setOpt({ face_topo: e.currentTarget.checked })} />
              <Text size="xs">{t('lm.face_mesh_smoothing_0_off')}: {opts.face_smooth}</Text>
              <Slider size="sm" min={0} max={3} step={1} value={opts.face_smooth} onChange={(x) => setOpt({ face_smooth: x })} />
              <Select size="xs" label={t('lm.face_parts_set_empty_the_standard')} value={opts.kit} allowDeselect={false} onChange={(x) => setOpt({ kit: x ?? '' })} data={opts.kits} />
            </Stack>
          </Popover.Dropdown>
        </Popover>
        <Button size="compact-sm" onClick={build} disabled={!hasMarkup || running} rightSection={<Kbd size="xs">Ctrl+Enter</Kbd>}>{t('web.rig_build')}</Button>
      </>}
    </Group>
  );

  if (mode === 'auto') {
    const model = o?.rigged || o?.source;
    return (
      <div className="equip">
        {head}
        <div className="work two" style={{ flex: 1 }}>
          <div className="stage"><Viewer3D url={model ? fileUrl(model, v || o?.files.length) : null} empty={t('web.ov_no_model')} person /></div>
          <ScrollArea className="panel">
            <Stack gap="sm" p="sm">
              <div className="panel-title">{t('web.rig_auto')}</div>
              <div className="field-note">{t('cr.char_rig_note')}</div>
              <Select size="sm" label={t('lm.bone_names')} value={naming} allowDeselect={false} onChange={(x) => x && setNaming(x)}
                data={[{ value: 'mixamo', label: t('lm.mixamo_for_mixamo_animations') }, { value: 'godot', label: t('lm.godot_humanoid_profile') }]} />
              <NumberInput size="sm" label={t('ui.attempts_to_get_a_skeleton_with')} value={tries} min={1} max={6} onChange={(x) => setTries(Number(x) || 3)} />
              <Button onClick={job('/api/char/rig', { naming, tries })} disabled={running}>{t('ui.make_the_skeleton_3_6_minutes_3_5_gb')}</Button>
              <Text size="sm" fw={600} mt="sm">{t('ui.for_humanoids_seams_and_body_parts')}</Text>
              <Button variant="default" onClick={job('/api/char/seams', {})} disabled={running}>{t('ui.fix_the_seams_between_parts_the')}</Button>
              <Button variant="default" onClick={job('/api/char/split', {})} disabled={running || !cur?.rigged}>{t('ui.split_the_body_into_parts_for_armour')}</Button>
            </Stack>
          </ScrollArea>
        </div>
      </div>
    );
  }
  const src = mode === 'markup' ? `/editor/landmarks?${q}&mode=${pageMode}` : mode === 'pose' ? `/editor/landmarks?${q}&mode=view` : `/editor/bones?${q}`;
  const fields = mode === 'markup' ? [bridges.markup] : mode === 'pose' ? [bridges.pose] : [];
  return (
    <div className="equip">
      {head}
      <EditorFrame src={src} fields={fields} onField={onField} title={t('ui.skeleton')} />
    </div>
  );
}
