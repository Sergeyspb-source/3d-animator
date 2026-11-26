// Models → Create a model: SF3D / Hunyuan3D (fast shape) / TRELLIS.2, the same options as the former Gradio tab, the
// result straight in the 3D view. It is made as a draft; «Release» puts it into export.
import { useEffect, useMemo, useState } from 'react';
import { Accordion, Alert, Button, CloseButton, Group, Image, Kbd, NumberInput, ScrollArea, SegmentedControl, Select, SimpleGrid,
  Slider, Stack, Switch, Text, TextInput } from '@mantine/core';
import { Dropzone, IMAGE_MIME_TYPE } from '@mantine/dropzone';
import { useHotkeys, useLocalStorage } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconPhotoPlus, IconCpu } from '@tabler/icons-react';
import { fileUrl, get, live, onTaskFinished, post, upload, useStore, type TaskSummary } from '../api';
import { useT } from '../i18n';
import type { Route } from '../nav';
import Viewer3D from '../components/Viewer3D';

interface Choice { id: string; key: string }
interface Options {
  engines: (Choice & { ok: boolean; why?: string })[]; categories: (Choice & { preset: Record<string, any> })[];
  pivots: Choice[]; collisions: Choice[]; namings: Choice[]; veg: Choice[]; hy_fast_categories: string[];
  defaults: { foreground_ratio: number; trellis_color_match: number }; gpu_needs: Record<string, number>;
}
type Pic = { name: string; path: string };
const VIEWS = ['front', 'back', 'left', 'right'] as const;
const VIEW_KEY = { front: 'ui.front_2', back: 'ui.back_2', left: 'ui.left_2', right: 'ui.right_2' };

const FORM0 = {
  engine: 'sf3d', category: 'prop', name: '', veg: 'tree',
  height: 0, width: 0, depth: 0, pivot: 'auto', collision: 'auto',
  override: false, metallic: 0, roughness: 0.8, color_match: 0, saturation: 1, brightness: 1, auto_materials: false,
  tex_res: '1024', fg_ratio: 0.85, remove_bg: true, remesh: 'none',
  paint: true, hy_tex: '2048', hy_faces: 50000, hy_steps: 50, hy_fast: false, hy_fast_set: false,   // (set: flipped by hand)
  tr_faces: 50000, tr_seed: 42,
  preview: true, overwrite: false, auto_rig: false, naming: 'mixamo', rig_tries: 3,
};
type Form = typeof FORM0;

function Drop({ onFiles, multiple, label, h = 92 }: { onFiles: (f: File[]) => void; multiple?: boolean; label: string; h?: number }) {
  return (
    <Dropzone onDrop={onFiles} accept={IMAGE_MIME_TYPE} multiple={multiple} mih={h} p={6} className="drop">
      <Stack align="center" justify="center" gap={2} mih={h - 14}>
        <IconPhotoPlus size={22} stroke={1.5} />
        <Text size="xs" c="dimmed" ta="center">{label}</Text>
      </Stack>
    </Dropzone>
  );
}

export default function ModelCreate({ go, vegetation }: { go: (r: Route) => void; vegetation?: boolean }) {
  const t = useT();
  const [opt, setOpt] = useState<Options | null>(null);
  const [saved, setSaved] = useLocalStorage<Form>({ key: 'sf3d.create_form', defaultValue: FORM0 });
  const f0: Form = { ...FORM0, ...saved, ...(vegetation ? { category: 'vegetation' } : {}) };
  // the fast shape follows the category until it is flipped by hand (a form opened on «Character» had it off: the
  // shape took the full 50 steps, ~200 s instead of ~23)
  const f: Form = f0.hy_fast_set || !opt ? f0 : { ...f0, hy_fast: opt.hy_fast_categories.includes(f0.category) };
  const set = (patch: Partial<Form>) => setSaved({ ...f, ...patch });
  const [pics, setPics] = useState<Pic[]>([]);
  const [views, setViews] = useState<Record<string, Pic | undefined>>({});
  const [busyUp, setBusyUp] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [result, setResult] = useState<{ glb: string; stem: string; category: string; v: number } | null>(null);
  const task = useStore(live, (s) => (taskId ? s.tasks[taskId] : undefined));

  useEffect(() => { get<Options>('/api/models/options').then(setOpt); }, []);
  useEffect(() => {   // pictures sent here from «Reference» (one picture: SF3D; with views: Hunyuan3D)
    try {
      const raw = localStorage.getItem('sf3d.create_prefill');
      if (!raw) return;
      localStorage.removeItem('sf3d.create_prefill');
      const pf = JSON.parse(raw);
      set({ engine: pf.engine || f.engine, category: pf.category || f.category, name: pf.name || f.name, ...(pf.category ? { hy_fast_set: false } : {}) });
      setPics(pf.pics || []);
      setViews(pf.views || {});
    } catch { /* (nothing sent) */ }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => onTaskFinished((tk: TaskSummary) => {
    if (tk.id !== taskId) return;
    const r = tk.result || {};
    if (tk.status === 'done' && r.last) {
      setResult({ glb: r.last, stem: (r.made || [])[0] || '', category: r.category, v: Date.now() });
      notifications.show({ color: 'teal', title: tk.title, message: (r.made || []).length ? t('web.made_drafts', (r.made || []).join(', ')) : t('web.made_none') });
    } else if (tk.status === 'error') {
      notifications.show({ color: 'red', title: tk.title, message: tk.error || '' });
    }
  }), [taskId, t]);

  const addFiles = async (files: File[], slot?: string) => {
    setBusyUp(true);
    try {
      const up = await upload(files);
      if (slot) setViews((v) => ({ ...v, [slot]: up[0] }));
      else setPics((p) => [...p, ...up]);
      if (!f.name && up.length === 1 && (!slot || slot === 'front')) set({ name: up[0].name.replace(/\.[^.]+$/, '').toLowerCase().replace(/[^a-z0-9_]+/g, '_') });
    } catch (e) {
      notifications.show({ color: 'red', message: String(e) });
    } finally { setBusyUp(false); }
  };

  const engine = opt?.engines.find((e) => e.id === f.engine);
  const cat = opt?.categories.find((c) => c.id === f.category);
  const canGo = !!engine?.ok && (f.engine === 'hunyuan' ? !!views.front : pics.length > 0) && !busyUp;
  const submit = async () => {
    if (!canGo) return;
    const body = { ...f, files: pics.map((p) => p.path), views: Object.fromEntries(VIEWS.map((k) => [k, views[k]?.path || null])),
      auto_rig: f.auto_rig && f.category === 'character' };
    const r = await post<{ ok: boolean; log?: string; task?: TaskSummary }>('/api/models/generate', body);
    if (!r.ok || !r.task) { notifications.show({ color: 'red', message: r.log || 'error' }); return; }
    setTaskId(r.task.id);
    live.set((s) => ({ ...s, selected: r.task!.id }));
  };
  useHotkeys([['mod+Enter', submit]], []);

  const choices = (list: Choice[] | undefined) => (list || []).map((c) => ({ value: c.id, label: t(c.key) }));
  const engineData = useMemo(() => (opt?.engines || []).map((e) => ({ value: e.id, disabled: !e.ok,
    label: { sf3d: 'SF3D', hunyuan: 'Hunyuan3D', trellis: 'TRELLIS.2' }[e.id] || e.id })), [opt]);
  const preset = cat?.preset || {};
  const running = task && (task.status === 'running' || task.status === 'queued');

  if (!opt) return null;
  return (
    <div className="work two">
      <div className="stage">
        <Viewer3D url={result ? fileUrl(result.glb, result.v) : null} empty={t('web.create_empty')} />
        {(pics.length > 0 || Object.values(views).some(Boolean)) && (
          <Group className="stage-strip" gap={6}>
            {(f.engine === 'hunyuan' ? VIEWS.filter((k) => views[k]).map((k) => ({ ...views[k]!, tag: t(VIEW_KEY[k]) })) : pics.map((p) => ({ ...p, tag: '' }))).map((p) => (
              <div key={p.path} className="thumb"><Image src={fileUrl(p.path)} h={64} w={64} fit="contain" />{p.tag && <Text size="xs" ta="center">{p.tag}</Text>}</div>))}
          </Group>
        )}
        {result && task?.status === 'done' && (
          <Button className="stage-next" variant="default" onClick={() => { localStorage.setItem('sf3d.check_sel', `${result.category}/${result.stem}`); go({ section: 'models', step: 'check' }); }}>
            {t('web.to_check')}
          </Button>)}
      </div>
      <ScrollArea className="panel">
        <Stack gap="sm" p="sm">
          <div className="panel-title">{vegetation ? t('web.step_vegetation') : t('ui.make_a_model')}</div>
          <div>
            <Text size="sm" fw={500} mb={4}>{t('ui.engine_2')}</Text>
            <SegmentedControl fullWidth value={f.engine} data={engineData}
              onChange={(v) => set({ engine: v, color_match: v === 'trellis' ? opt.defaults.trellis_color_match : f.engine === 'trellis' ? 0 : f.color_match })} />
            <div className="field-note" style={{ marginTop: 6 }}>{engine ? t(engine.key) : ''}</div>
            <Group gap={4} mt={2} wrap="nowrap"><IconCpu size={13} color="var(--ash)" /><span className="field-note">{t('web.gpu_need', ((opt.gpu_needs[f.engine] || 0) / 1024).toFixed(1))}</span></Group>
            {engine && !engine.ok && <Alert color="red" mt={6} p={6}><Text size="xs">{t('web.engine_missing', engine.why || '')}</Text></Alert>}
          </div>

          {f.engine === 'hunyuan' ? (
            <div>
              <Text size="sm" fw={500} mb={4}>{t('web.views')}</Text>
              <SimpleGrid cols={2} spacing={6}>
                {VIEWS.map((k) => views[k] ? (
                  <div key={k} className="slot"><Image src={fileUrl(views[k]!.path)} h={92} fit="contain" />
                    <Group justify="space-between" gap={2}><Text size="xs">{t(VIEW_KEY[k])}</Text><CloseButton size="xs" onClick={() => setViews({ ...views, [k]: undefined })} /></Group></div>
                ) : <Drop key={k} label={t(VIEW_KEY[k])} onFiles={(fs) => addFiles(fs.slice(0, 1), k)} />)}
              </SimpleGrid>
              <Text size="xs" c="dimmed" mt={4}>{t('web.views_hint')}</Text>
            </div>
          ) : (
            <div>
              <Text size="sm" fw={500} mb={4}>{t('ui.pictures_one_or_several')}</Text>
              <Drop multiple label={t('web.drop_pictures')} onFiles={(fs) => addFiles(fs)} h={pics.length ? 60 : 110} />
              {pics.length > 0 && (
                <Group gap={6} mt={6}>
                  {pics.map((p) => (
                    <div key={p.path} className="slot small"><Image src={fileUrl(p.path)} h={54} w={54} fit="contain" />
                      <CloseButton size="xs" className="slot-x" onClick={() => setPics(pics.filter((x) => x !== p))} /></div>))}
                </Group>)}
            </div>
          )}

          <Select label={t('ui.category_2')} data={choices(opt.categories)} value={f.category} allowDeselect={false}
            onChange={(v) => v && set({ category: v, hy_fast: opt.hy_fast_categories.includes(v), hy_fast_set: false })} disabled={vegetation} />
          {f.category === 'vegetation' && (
            <div><Text size="sm" fw={500} mb={4}>{t('ui.what_plant_it_is_for_the_wind_in')}</Text>
              <SegmentedControl fullWidth size="xs" value={f.veg} data={choices(opt.veg)} onChange={(v) => set({ veg: v })} /></div>)}
          <TextInput label={t('web.name')} description={t('web.name_hint')} value={f.name} onChange={(e) => set({ name: e.currentTarget.value })} />
          <Text className="field-note">{t('web.preset', preset.height_m ?? '—', t(opt.pivots.find((x) => x.id === preset.pivot)?.key || '—'),
            t(opt.collisions.find((x) => x.id === preset.collision)?.key || '—'))}</Text>

          <Accordion multiple variant="contained" defaultValue={[]} chevronPosition="right">
            <Accordion.Item value="size">
              <Accordion.Control>{t('ui.size_and_pivot')}</Accordion.Control>
              <Accordion.Panel><Stack gap="xs">
                <NumberInput label={t('ui.model_height_in_metres_0_the')} value={f.height} min={0} step={0.1} decimalScale={2} onChange={(v) => set({ height: Number(v) || 0 })} />
                <Group grow>
                  <NumberInput label={t('ui.width_along_x_m_0_unchanged')} value={f.width} min={0} step={0.1} decimalScale={2} onChange={(v) => set({ width: Number(v) || 0 })} />
                  <NumberInput label={t('ui.depth_along_z_m_0_unchanged')} value={f.depth} min={0} step={0.1} decimalScale={2} onChange={(v) => set({ depth: Number(v) || 0 })} />
                </Group>
                <Select label={t('ui.pivot_point')} data={choices(opt.pivots)} value={f.pivot} allowDeselect={false} onChange={(v) => v && set({ pivot: v })} />
                <Select label={t('ui.collision_for_godot_made')} data={choices(opt.collisions)} value={f.collision} allowDeselect={false} onChange={(v) => v && set({ collision: v })} />
              </Stack></Accordion.Panel>
            </Accordion.Item>
            <Accordion.Item value="look">
              <Accordion.Control>{t('ui.material_and_colour')}</Accordion.Control>
              <Accordion.Panel><Stack gap="xs">
                <Switch label={t('ui.set_metallic_and_roughness_by_hand')} checked={f.override} onChange={(e) => set({ override: e.currentTarget.checked })} />
                {f.override && <>
                  <Text size="xs">{t('ui.metallic')}: {f.metallic.toFixed(2)}</Text>
                  <Slider min={0} max={1} step={0.05} value={f.metallic} onChange={(v) => set({ metallic: v })} />
                  <Text size="xs">{t('ui.roughness_2')}: {f.roughness.toFixed(2)}</Text>
                  <Slider min={0} max={1} step={0.05} value={f.roughness} onChange={(v) => set({ roughness: v })} />
                </>}
                <Text size="xs">{t('ui.match_the_palette_to_your_pictures_0')}: {f.color_match.toFixed(2)}</Text>
                <Slider min={0} max={1} step={0.05} value={f.color_match} onChange={(v) => set({ color_match: v })} />
                <Text size="xs">{t('ui.saturation_1_unchanged')}: {f.saturation.toFixed(2)}</Text>
                <Slider min={0.3} max={1.5} step={0.05} value={f.saturation} onChange={(v) => set({ saturation: v })} />
                <Text size="xs">{t('ui.brightness_1_unchanged')}: {f.brightness.toFixed(2)}</Text>
                <Slider min={0.5} max={1.5} step={0.05} value={f.brightness} onChange={(v) => set({ brightness: v })} />
                <Switch label={t('ui.recognise_materials_wood_metal_stone')} checked={f.auto_materials} onChange={(e) => set({ auto_materials: e.currentTarget.checked })} />
              </Stack></Accordion.Panel>
            </Accordion.Item>
            <Accordion.Item value="engine">
              <Accordion.Control>{t(f.engine === 'hunyuan' ? 'ui.hunyuan3d_options' : f.engine === 'trellis' ? 'ui.trellis_options' : 'ui.sf3d_generation_options')}</Accordion.Control>
              <Accordion.Panel><Stack gap="xs">
                {f.engine === 'hunyuan' && <>
                  <Switch label={t('ui.hy_fast_shape')} description={t('ui.hy_fast_shape_info')} checked={f.hy_fast} onChange={(e) => set({ hy_fast: e.currentTarget.checked, hy_fast_set: true })} />
                  <Switch label={t('ui.paint_a_texture_without_it_a_grey')} checked={f.paint} onChange={(e) => set({ paint: e.currentTarget.checked })} />
                  <Select label={t('ui.texture_size')} data={['1024', '2048']} value={f.hy_tex} allowDeselect={false} onChange={(v) => v && set({ hy_tex: v })} />
                  <Text size="xs">{t('ui.target_face_count_after_simplifying')}: {f.hy_faces.toLocaleString()}</Text>
                  <Slider min={10000} max={100000} step={5000} value={f.hy_faces} onChange={(v) => set({ hy_faces: v })} />
                  <Text size="xs" c={f.hy_fast ? 'dimmed' : undefined}>{t('ui.diffusion_steps_fewer_faster')}: {f.hy_steps}</Text>
                  <Slider min={20} max={50} step={5} value={f.hy_steps} disabled={f.hy_fast} onChange={(v) => set({ hy_steps: v })} />
                </>}
                {f.engine === 'trellis' && <>
                  <Text size="xs">{t('ui.target_face_count_after_simplifying')}: {f.tr_faces.toLocaleString()}</Text>
                  <Slider min={10000} max={150000} step={5000} value={f.tr_faces} onChange={(v) => set({ tr_faces: v })} />
                  <NumberInput label={t('ui.trellis_seed')} description={t('ui.trellis_seed_info')} value={f.tr_seed} min={0} step={1} onChange={(v) => set({ tr_seed: Number(v) || 0 })} />
                </>}
                {f.engine === 'sf3d' && <>
                  <Select label={t('ui.texture_size_2048_may_not_fit_into_8')} data={['512', '1024', '2048']} value={f.tex_res} allowDeselect={false} onChange={(v) => v && set({ tex_res: v })} />
                  <Text size="xs">{t('ui.object_s_share_of_the_frame')}: {f.fg_ratio.toFixed(2)}</Text>
                  <Slider min={0.5} max={1} step={0.01} value={f.fg_ratio} onChange={(v) => set({ fg_ratio: v })} />
                  <Switch label={t('ui.remove_the_background_turn_off_if')} checked={f.remove_bg} onChange={(e) => set({ remove_bg: e.currentTarget.checked })} />
                  <Select label={t('ui.remesh_none_unchanged')} data={['none', 'triangle', 'quad']} value={f.remesh} allowDeselect={false} onChange={(v) => v && set({ remesh: v })} />
                </>}
              </Stack></Accordion.Panel>
            </Accordion.Item>
            {f.category === 'character' && (
              <Accordion.Item value="rig">
                <Accordion.Control>{t('ui.skeleton')}</Accordion.Control>
                <Accordion.Panel><Stack gap="xs">
                  <Switch label={t('ui.make_a_skeleton_for_a_humanoid')} checked={f.auto_rig} onChange={(e) => set({ auto_rig: e.currentTarget.checked })} />
                  {f.auto_rig && <>
                    <Select label={t('lm.bone_names')} data={choices(opt.namings)} value={f.naming} allowDeselect={false} onChange={(v) => v && set({ naming: v })} />
                    <NumberInput label={t('ui.attempts_to_get_a_skeleton_with')} value={f.rig_tries} min={1} max={6} onChange={(v) => set({ rig_tries: Number(v) || 3 })} />
                  </>}
                </Stack></Accordion.Panel>
              </Accordion.Item>)}
          </Accordion>

          <Switch label={t('ui.preview_and_icon_blender_10_s')} checked={f.preview} onChange={(e) => set({ preview: e.currentTarget.checked })} />
          <Switch label={t('web.overwrite_draft')} checked={f.overwrite} onChange={(e) => set({ overwrite: e.currentTarget.checked })} />
          <Button size="md" onClick={submit} disabled={!canGo} loading={busyUp} rightSection={<Kbd size="xs">Ctrl+Enter</Kbd>}>
            {running ? t('web.queue_another') : t('ui.make_a_model')}
          </Button>
          <div className="field-note">{t('web.draft_note')}</div>
          {f.engine !== 'sf3d' && <div className="field-note">{t('ui.engine_info')}</div>}
        </Stack>
      </ScrollArea>
    </div>
  );
}
