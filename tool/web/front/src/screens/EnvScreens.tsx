// Environment (surfaces, effects, dungeons, destructibles), Models → Reference and Models → Model materials: each a
// panel of the former Gradio tab's settings on the right and its pictures (or the model) on the stage; long jobs are tasks.
import { useEffect, useState } from 'react';
import { Button, Checkbox, ColorInput, FileButton, Group, Image, NumberInput, ScrollArea, SegmentedControl, Select, Slider, Stack, Switch,
  Text, TextInput, Textarea, UnstyledButton } from '@mantine/core';
import { useLocalStorage } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconPhotoPlus } from '@tabler/icons-react';
import { fileUrl, get, live, onTaskFinished, post, upload, useStore } from '../api';
import { plain, useT } from '../i18n';
import type { Route } from '../nav';
import Viewer3D from '../components/Viewer3D';

type Pic = { path: string; caption: string };
interface Opts {
  providers: { id: string; key: string }[]; ref_cats: { id: string; key: string }[]; fx: { id: string; key: string }[]; views: { id: string; key: string }[];
  materials: string[]; kit_sample: string; assets: string[]; mat_assets: string[]; mat_choices: { id: string; label: string }[];
  has_key: boolean; style: { text: string; refs: string[] | null };
}

function useOpts() {
  const finished = useStore(live, (s) => s.finished);
  const [o, setO] = useState<Opts | null>(null);
  useEffect(() => { get<Opts>('/api/env/options').then(setO); }, [finished]);
  return o;
}

// the pictures the last task of these jobs made (and its extra result)
function useJobResult(jobs: string[]) {
  const [res, setRes] = useState<any>(null);
  useEffect(() => onTaskFinished((tk) => {
    if (tk.kind !== 'env' || !jobs.includes(tk.meta?.job)) return;
    if (tk.status === 'error') notifications.show({ color: 'rust', title: tk.title, message: tk.error || '' });
    if (tk.status === 'done') { setRes({ ...tk.result, job: tk.meta?.job }); notifications.show({ color: 'patina', message: tk.title }); }
  }), [jobs.join()]); // eslint-disable-line react-hooks/exhaustive-deps
  return [res, setRes] as const;
}

function useBusy(jobs: string[]) {
  return useStore(live, (s) => Object.values(s.tasks).some((x) => x.kind === 'env' && jobs.includes(x.meta?.job) && (x.status === 'running' || x.status === 'queued')));
}

export function Gallery({ pics, empty, onPick, picked }: { pics: Pic[]; empty: string; onPick?: (p: Pic) => void; picked?: string | null }) {
  if (!pics.length) return <Text className="viewer-empty">{empty}</Text>;
  return (
    <ScrollArea className="gallery">
      <div className="gallery-grid">
        {pics.map((p) => (
          <UnstyledButton key={p.path} className={'gal-item' + (picked === p.path ? ' on' : '')} onClick={() => (onPick ? onPick(p) : window.open(fileUrl(p.path)))}>
            <Image src={fileUrl(p.path)} fit="contain" radius="sm" />
            {p.caption && <Text size="xs" c="dimmed" ta="center" truncate>{p.caption}</Text>}
          </UnstyledButton>))}
      </div>
    </ScrollArea>
  );
}

const Provider = ({ o, value, onChange }: { o: Opts; value: string; onChange: (v: string) => void }) => {
  const t = useT();
  return (
    <div>
      <Text size="sm" fw={500} mb={4}>{t('ui.generate_with')}</Text>
      <SegmentedControl fullWidth size="xs" value={value} onChange={onChange} data={o.providers.map((p) => ({ value: p.id, label: t(p.key) }))} />
      <div className="field-note" style={{ marginTop: 4 }}>{t('web.ext_service')}</div>
    </div>
  );
};

function Sl({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void }) {
  return (<div><Group justify="space-between"><Text size="xs">{label}</Text><Text size="xs" c="dimmed">{value}</Text></Group>
    <Slider size="sm" min={min} max={max} step={step} value={value} onChange={onChange} label={null} /></div>);
}

async function upOne(f: File | null) { if (!f) return null; const [u] = await upload([f]); return u; }

export function Surfaces() {
  const t = useT();
  const o = useOpts();
  const [p, setP] = useLocalStorage({ key: 'sf3d.surface', defaultValue: { provider: 'codex', desc: '', tile: 4, strength: 1, size: '1024', name: '' } });
  const [own, setOwn] = useState<{ name: string; path: string } | null>(null);
  const [res] = useJobResult(['surface']);
  const busy = useBusy(['surface']);
  if (!o) return null;
  return (
    <div className="work two">
      <div className="stage plainstage"><Gallery pics={res?.pics || []} empty={plain(t('ui.a_seamless_material_for_terrain'))} /></div>
      <ScrollArea className="panel"><Stack gap="sm" p="sm">
        <div className="panel-title">{t('web.step_surfaces')}</div>
        <Textarea label={t('ui.surface')} placeholder={t('ui.for_example_an_old_cobbled_road_moss')} value={p.desc} autosize minRows={2} onChange={(e) => setP({ ...p, desc: e.currentTarget.value })} />
        <FileButton accept="image/*" onChange={async (f) => setOwn(await upOne(f))}>{(b) => <Button {...b} variant="default" leftSection={<IconPhotoPlus size={16} />}>{own ? own.name : t('ui.or_your_own_picture_top_view')}</Button>}</FileButton>
        {!own && <Provider o={o} value={p.provider} onChange={(v) => setP({ ...p, provider: v })} />}
        <Sl label={t('ui.the_tile_repeats_every_m')} value={p.tile} min={0.5} max={10} step={0.5} onChange={(v) => setP({ ...p, tile: v })} />
        <Sl label={t('ui.relief_strength')} value={p.strength} min={0.2} max={3} step={0.1} onChange={(v) => setP({ ...p, strength: v })} />
        <Select label={t('ui.texture_size_2')} data={['512', '1024', '2048']} value={p.size} allowDeselect={false} onChange={(v) => v && setP({ ...p, size: v })} />
        <TextInput label={t('ui.name_folder_in_materials')} value={p.name} onChange={(e) => setP({ ...p, name: e.currentTarget.value })} />
        <Button disabled={busy || (!p.desc && !own)} onClick={() => post('/api/env/surface', { ...p, own: own?.path })}>{t('ui.make_the_material')}</Button>
      </Stack></ScrollArea>
    </div>
  );
}

export function Effects() {
  const t = useT();
  const o = useOpts();
  const [p, setP] = useLocalStorage({ key: 'sf3d.fx', defaultValue: { kind: 'explosion', color: '#ffffff', grid: '8', size: '128', seed: 1, speed: 1, name: '',
    provider: 'codex', desc: '', sname: '' } });
  const [res] = useJobResult(['fx_flip', 'fx_sprite', 'fx_scenes']);
  const busy = useBusy(['fx_flip', 'fx_sprite', 'fx_scenes']);
  if (!o) return null;
  return (
    <div className="work two">
      <div className="stage plainstage"><Gallery pics={res?.pics || []} empty={t('web.env_results_here')} /></div>
      <ScrollArea className="panel"><Stack gap="sm" p="sm">
        <div className="panel-title">{t('web.step_fx')}</div>
        <div className="field-note">{plain(t('ui.1_an_animated_sheet_for_godot'))}</div>
        <Select label={t('ui.what_to_draw')} value={p.kind} allowDeselect={false} onChange={(v) => v && setP({ ...p, kind: v })} data={o.fx.map((x) => ({ value: x.id, label: t(x.key) }))} />
        <Group grow>
          <ColorInput label={t('ui.hue')} value={p.color} onChange={(v) => setP({ ...p, color: v })} />
          <Select label={t('ui.frame_grid')} data={['4', '8']} value={p.grid} allowDeselect={false} onChange={(v) => v && setP({ ...p, grid: v })} />
          <Select label={t('ui.frame_size_px')} data={['64', '128', '256']} value={p.size} allowDeselect={false} onChange={(v) => v && setP({ ...p, size: v })} />
        </Group>
        <Group grow>
          <NumberInput label={t('ui.variant_seed')} value={p.seed} min={0} onChange={(v) => setP({ ...p, seed: Number(v) || 0 })} />
          <NumberInput label={t('fbx.speed')} value={p.speed} min={0.5} max={2} step={0.1} decimalScale={1} onChange={(v) => setP({ ...p, speed: Number(v) || 1 })} />
        </Group>
        <TextInput label={t('ui.file_name_empty_by_the_kind')} value={p.name} onChange={(e) => setP({ ...p, name: e.currentTarget.value })} />
        <Button disabled={busy} onClick={() => post('/api/env/fx_flip', p)}>{t('ui.make_the_sheet')}</Button>
        <div className="field-note" style={{ marginTop: 8 }}>{plain(t('ui.2_a_glowing_sprite_from_a'))}</div>
        <Provider o={o} value={p.provider} onChange={(v) => setP({ ...p, provider: v })} />
        <Textarea label={t('ui.description')} placeholder={t('ui.a_summoning_circle_with_runes_blue')} value={p.desc} autosize minRows={2} onChange={(e) => setP({ ...p, desc: e.currentTarget.value })} />
        <TextInput label={t('ui.file_name_magic_circle_for_the')} value={p.sname} onChange={(e) => setP({ ...p, sname: e.currentTarget.value })} />
        <Button variant="default" disabled={busy || !p.desc} onClick={() => post('/api/env/fx_sprite', { provider: p.provider, desc: p.desc, name: p.sname })}>{t('ui.generate_the_sprite')}</Button>
        <div className="field-note" style={{ marginTop: 8 }}>{plain(t('ui.3_godot_scenes_from_the_sheets'))}</div>
        <Button variant="default" disabled={busy} onClick={() => post('/api/env/fx_scenes', {})}>{t('ui.build_the_godot_scenes')}</Button>
      </Stack></ScrollArea>
    </div>
  );
}

export function Dungeons() {
  const t = useT();
  const o = useOpts();
  const [p, setP] = useLocalStorage({ key: 'sf3d.kit', defaultValue: { cell: 4, height: 3, seed: 1, wall: 'proc', floor: '', wood: '', plan: '', ceilings: true } });
  const [res] = useJobResult(['kit_build', 'kit_scene']);
  const busy = useBusy(['kit_build', 'kit_scene']);
  if (!o) return null;
  const mats = o.materials;
  const floor = p.floor || (mats.includes('dungeon_floor') ? 'dungeon_floor' : mats[0] || '');
  const wood = p.wood || (mats.includes('dungeon_wood') ? 'dungeon_wood' : mats[0] || '');
  return (
    <div className="work two">
      <div className="stage plainstage"><Gallery pics={res?.pics || []} empty={plain(t('ui.a_set_of_pieces_that_join_on_a_grid'))} /></div>
      <ScrollArea className="panel"><Stack gap="sm" p="sm">
        <div className="panel-title">{t('web.step_dungeons')}</div>
        <Text size="sm" fw={600}>{plain(t('ui.1_kit_pieces'))}</Text>
        <Group grow>
          <NumberInput label={t('ui.cell_m')} value={p.cell} min={1} step={0.5} onChange={(v) => setP({ ...p, cell: Number(v) || 4 })} />
          <NumberInput label={t('ui.storey_height_m')} value={p.height} min={2} step={0.5} onChange={(v) => setP({ ...p, height: Number(v) || 3 })} />
          <NumberInput label={t('ui.masonry_variant')} value={p.seed} min={0} onChange={(v) => setP({ ...p, seed: Number(v) || 0 })} />
        </Group>
        <Select label={t('ui.wall_stone')} value={p.wall} allowDeselect={false} onChange={(v) => v && setP({ ...p, wall: v })} data={[{ value: 'proc', label: t('ui.procedural_stone') }, ...mats.map((m) => ({ value: m, label: m }))]} />
        <Group grow>
          <Select label={t('ui.floor_and_stairs')} value={floor} allowDeselect={false} onChange={(v) => v && setP({ ...p, floor: v })} data={mats} />
          <Select label={t('ui.wood_door_beams')} value={wood} allowDeselect={false} onChange={(v) => v && setP({ ...p, wood: v })} data={mats} />
        </Group>
        <Button disabled={busy} onClick={() => post('/api/env/kit_build', { ...p, floor, wood })}>{t('ui.build_the_pieces')}</Button>
        <Text size="sm" fw={600} mt="sm">{plain(t('ui.2_floor_plan_godot_scene_rows_are'))}</Text>
        <Textarea label={t('ui.plan')} value={p.plan || o.kit_sample} autosize minRows={10} maxRows={24} styles={{ input: { fontFamily: 'var(--mantine-font-family-monospace)', fontSize: 12 } }}
          onChange={(e) => setP({ ...p, plan: e.currentTarget.value })} />
        <Switch label={t('ui.ceilings')} checked={p.ceilings} onChange={(e) => setP({ ...p, ceilings: e.currentTarget.checked })} />
        <Button variant="default" disabled={busy} onClick={() => post('/api/env/kit_scene', { plan: p.plan || o.kit_sample, ceilings: p.ceilings })}>{t('ui.build_the_scene')}</Button>
      </Stack></ScrollArea>
    </div>
  );
}

export function Destructibles() {
  const t = useT();
  const o = useOpts();
  const [p, setP] = useLocalStorage({ key: 'sf3d.destr', defaultValue: { asset: '', chunks: 14, seed: 1, auto: true, color: '#6b4a2e', mass: 20, health: 20, burst: 3.5, name: '' } });
  const [model, setModel] = useState<string | null>(null);
  const [res] = useJobResult(['destr']);
  const busy = useBusy(['destr']);
  useEffect(() => { if (p.asset) get<{ model: string | null }>(`/api/env/asset_model?asset=${encodeURIComponent(p.asset)}`).then((r) => setModel(r.model)); }, [p.asset]);
  if (!o) return null;
  return (
    <div className="work two">
      <div className="stage">
        <Viewer3D url={model ? fileUrl(model) : null} empty={plain(t('ui.the_model_a_barrel_a_crate_a_vase_a'))} person />
        {res?.pics?.length > 0 && <Group className="stage-strip" gap={6}>{res.pics.map((x: Pic) => <div key={x.path} className="thumb"><Image src={fileUrl(x.path)} h={120} w="auto" fit="contain" /></div>)}</Group>}
      </div>
      <ScrollArea className="panel"><Stack gap="sm" p="sm">
        <div className="panel-title">{t('web.step_destructibles')}</div>
        <Select label={t('ui.finished_model_category_name')} searchable value={p.asset || null} data={o.assets} onChange={(v) => setP({ ...p, asset: v || '' })} />
        <Sl label={t('ui.chunks')} value={p.chunks} min={4} max={40} step={1} onChange={(v) => setP({ ...p, chunks: v })} />
        <NumberInput label={t('ui.fracture_variant')} value={p.seed} min={0} onChange={(v) => setP({ ...p, seed: Number(v) || 0 })} />
        <Switch label={t('ui.fracture_colour_from_the_texture')} checked={p.auto} onChange={(e) => setP({ ...p, auto: e.currentTarget.checked })} />
        {!p.auto && <ColorInput label={t('ui.or_your_own_fracture_colour')} value={p.color} onChange={(v) => setP({ ...p, color: v })} />}
        <Group grow>
          <NumberInput label={t('ui.mass_kg')} value={p.mass} min={0.1} onChange={(v) => setP({ ...p, mass: Number(v) || 20 })} />
          <NumberInput label={t('ui.toughness')} value={p.health} min={1} onChange={(v) => setP({ ...p, health: Number(v) || 20 })} />
          <NumberInput label={t('ui.fly_apart_speed_m_s')} value={p.burst} min={0} step={0.5} decimalScale={1} onChange={(v) => setP({ ...p, burst: Number(v) || 0 })} />
        </Group>
        <TextInput label={t('ui.name_empty_as_the_model_s')} value={p.name} onChange={(e) => setP({ ...p, name: e.currentTarget.value })} />
        <Button disabled={busy || !p.asset} onClick={() => post('/api/env/destr', p)}>{t('ui.make_destructible')}</Button>
      </Stack></ScrollArea>
    </div>
  );
}

export function Reference({ go }: { go: (r: Route) => void }) {
  const t = useT();
  const o = useOpts();
  const [p, setP] = useLocalStorage({ key: 'sf3d.ref', defaultValue: { provider: 'codex', obj: '', cat: 'prop', n: 1, want: ['back', 'left', 'right'] } });
  const [style, setStyle] = useState<string | null>(null);
  const [refs, setRefs] = useState<{ name: string; path: string }[] | null>(null);
  const [front, setFront] = useState<string | null>(null);
  const [res, setRes] = useJobResult(['ref', 'ref_views']);
  const [variants, setVariants] = useState<Pic[]>([]);
  const [views, setViews] = useState<Record<string, string>>({});
  const busy = useBusy(['ref', 'ref_views']);
  useEffect(() => { if (res?.job === 'ref') { setVariants(res.pics || []); setFront(null); } if (res?.job === 'ref_views') setViews(res.views || {}); }, [res]);
  useEffect(() => { if (o && style === null) { setStyle(o.style.text || ''); setRefs((o.style.refs || []).map((x) => ({ name: x.split(/[\\/]/).pop() || x, path: x }))); } }, [o]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!o) return null;
  const refPaths = (refs || []).map((r) => r.path);
  const send = () => {   // the views (or the one picture) into «Make a model»
    const all: Record<string, string | null> = { ...views, front: views.front || front };
    const multi = ['back', 'left', 'right'].some((k) => all[k]);
    const cat = ({ item: 'item', prop: 'prop', building: 'building', character: 'character', vegetation: 'vegetation', creature: 'character' } as Record<string, string>)[p.cat] || 'prop';
    const pic = (x: string) => ({ name: x.split(/[\\/]/).pop() || x, path: x });
    localStorage.setItem('sf3d.create_prefill', JSON.stringify({ engine: multi ? 'hunyuan' : 'sf3d', category: cat, name: p.obj.toLowerCase().replace(/[^a-z0-9_]+/g, '_').slice(0, 40),
      pics: multi ? [] : [pic(all.front!)], views: multi ? Object.fromEntries(Object.entries(all).filter(([, v]) => v).map(([k, v]) => [k, pic(v as string)])) : {} }));
    setRes(null);
    go({ section: 'models', step: 'create' });
  };
  const shown: Pic[] = Object.keys(views).length > 1 ? Object.entries(views).filter(([, v]) => v).map(([k, v]) => ({ path: v, caption: k })) : variants;
  return (
    <div className="work two">
      <div className="stage plainstage">
        <Gallery pics={shown} empty={plain(t('ui.1_what_is_needed_describe_the_object'))} picked={front}
          onPick={Object.keys(views).length > 1 ? undefined : (x) => { setFront(x.path); setViews({}); }} />
      </div>
      <ScrollArea className="panel"><Stack gap="sm" p="sm">
        <div className="panel-title">{t('ui.reference')}</div>
        <Textarea label={t('ui.object')} placeholder={t('ui.for_example_a_crooked_wooden_fence')} value={p.obj} autosize minRows={2} onChange={(e) => setP({ ...p, obj: e.currentTarget.value })} />
        <Group grow>
          <Select label={t('ui.type')} value={p.cat} allowDeselect={false} onChange={(v) => v && setP({ ...p, cat: v })} data={o.ref_cats.map((c) => ({ value: c.id, label: t(c.key) }))} />
          <NumberInput label={t('ui.variants')} value={p.n} min={1} max={4} onChange={(v) => setP({ ...p, n: Number(v) || 1 })} />
        </Group>
        <Provider o={o} value={p.provider} onChange={(v) => setP({ ...p, provider: v })} />
        <Button disabled={busy || !p.obj.trim()} onClick={() => post('/api/env/ref', { ...p, style_text: style, style_files: refPaths })}>{t('ui.generate')}</Button>
        <details className="files">
          <summary>{t('ui.project_style_shared_by_all')}</summary>
          <Stack gap="xs" mt="xs">
            <div className="field-note">{plain(t('ui.reference_pictures_3_5_good_assets'))}</div>
            <Textarea label={t('ui.style_description_more_precise_in')} value={style || ''} autosize minRows={3} onChange={(e) => setStyle(e.currentTarget.value)} />
            <FileButton multiple accept="image/*" onChange={async (fs) => { if (fs?.length) setRefs(await upload(fs)); }}>
              {(b) => <Button {...b} variant="default" size="xs">{t('ui.style_reference_pictures')}: {refs?.length || 0}</Button>}
            </FileButton>
            <Group grow>
              <Button size="xs" variant="default" disabled={!refs?.length} onClick={async () => { const r = await post<{ text?: string; log: string }>('/api/ref/describe', { provider: p.provider, files: refPaths }); if (r.text) setStyle(r.text); notifications.show({ message: r.log }); }}>{t('ui.describe_from_the_pictures')}</Button>
              <Button size="xs" variant="default" onClick={async () => { const r = await post<{ log: string }>('/api/ref/style_save', { text: style, files: refPaths }); notifications.show({ message: r.log }); }}>{t('ui.save_the_style')}</Button>
            </Group>
          </Stack>
        </details>
        <Text size="sm" fw={600} mt="sm">{front ? t('web.ref_chosen') : t('ui.variants_click_the_best')}</Text>
        <Checkbox.Group label={t('ui.extra_views_for_hunyuan3d_the_best')} value={p.want} onChange={(v) => setP({ ...p, want: v })}>
          <Group gap="sm" mt={4}>{o.views.map((v) => <Checkbox key={v.id} size="xs" value={v.id} label={t(v.key)} />)}</Group>
        </Checkbox.Group>
        <Button variant="default" disabled={busy || !front || !p.want.length} onClick={() => post('/api/env/ref_views', { ...p, front, style_text: style, style_files: refPaths })}>{t('ui.make_views_of_the_chosen_variant')}</Button>
        <Button disabled={!front && !views.front} onClick={send}>{t('ui.send_to_3d')}</Button>
      </Stack></ScrollArea>
    </div>
  );
}

export function ModelMaterials() {
  const t = useT();
  const o = useOpts();
  const [asset, setAsset] = useLocalStorage<string | null>({ key: 'sf3d.mat_asset', defaultValue: null });
  const [model, setModel] = useState<string | null>(null);
  const [an, setAn] = useState<{ overlay: string | null; log: string; groups: { value: string; label: string }[] } | null>(null);
  const [vals, setVals] = useState<string[]>([]);
  const [v, setV] = useState(0);
  const [res] = useJobResult(['mat']);
  const busy = useBusy(['mat']);
  useEffect(() => { setAn(null); if (asset) get<{ model: string | null }>(`/api/env/asset_model?asset=${encodeURIComponent(asset)}`).then((r) => setModel(r.model)); }, [asset]);
  useEffect(() => { if (res) setV(Date.now()); }, [res]);
  if (!o) return null;
  const analyze = async () => { if (!asset) return; const r = await get<typeof an>(`/api/mat/analyze?asset=${encodeURIComponent(asset)}`); setAn(r); setVals(r!.groups.map((g) => g.value)); };
  return (
    <div className="work two">
      <div className="stage">
        <Viewer3D url={model ? fileUrl(model, v) : null} empty={plain(t('ui.1_choose_a_model_2_analyse_the'))} />
        {an?.overlay && <div className="stage-strip"><div className="thumb"><Image src={fileUrl(an.overlay, v)} w={240} fit="contain" /></div></div>}
      </div>
      <ScrollArea className="panel"><Stack gap="sm" p="sm">
        <div className="panel-title">{t('web.step_model_materials')}</div>
        <div className="field-note">{plain(t('ui.1_choose_a_model_2_analyse_the'))}</div>
        <Select label={t('ui.model_category_name')} searchable value={asset} data={o.mat_assets} onChange={setAsset} />
        <Button variant="default" disabled={!asset} onClick={analyze}>{t('ui.analyse')}</Button>
        {an && <div className="field-note">{plain(an.log)}</div>}
        {an?.groups.map((g, i) => (
          <Select key={i} size="xs" label={g.label} value={vals[i]} allowDeselect={false} data={o.mat_choices.map((c) => ({ value: c.id, label: c.label }))}
            onChange={(x) => setVals(vals.map((y, k) => (k === i ? x || y : y)))} />))}
        <Button disabled={busy || !an?.groups.length} onClick={() => post('/api/mat/apply', { asset, values: vals })}>{t('ui.apply_the_materials')}</Button>
        {res?.pics?.length > 0 && <Gallery pics={res.pics} empty="" />}
      </Stack></ScrollArea>
    </div>
  );
}
