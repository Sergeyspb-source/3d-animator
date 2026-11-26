// Creatures: the current creature's overview, its skeleton (UniRig with names and a jaw, the rest pose straightened,
// the markup viewer whose requests move the joints, mark the jaw and put the eyes in), its clips, its colouring, the
// Godot view. Each page of the app works here unchanged; its requests come through the hidden fields below it.
import { useEffect, useRef, useState } from 'react';
import { Button, Checkbox, FileButton, Group, Image, Modal, ScrollArea, SegmentedControl, Stack, Text, UnstyledButton, useMantineColorScheme } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconFolder, IconPlus, IconTrash } from '@tabler/icons-react';
import { fileUrl, get, live, onTaskFinished, post, upload, useStore, type TaskSummary } from '../api';
import { plain, useT } from '../i18n';
import { asCreature, PickList, useCurrent, useObjects } from '../objects';
import type { Route } from '../nav';
import EditorFrame from '../components/EditorFrame';
import Viewer3D from '../components/Viewer3D';

interface CrOverview {
  id: string; name: string; dir: string; source: string | null; rigged: string | null;
  rig: { file: string; when: string; bones: number; paws: Record<string, number>; tail: number; head: boolean; jaw: boolean } | null;
  humanoid: boolean; clips: number; clips_file: string | null; paints: { id: string; title: string }[]; jaw_pictures: string[];
  template?: { id: string; built: boolean } | null; tpl_pictures?: string[];
  files: { name: string; when: string }[];
}

function useCreature() {
  const cur = useCurrent();
  const finished = useStore(live, (s) => s.finished);
  const id = asCreature(cur) ? cur.id : undefined;
  const [o, setO] = useState<CrOverview | null>(null);
  useEffect(() => { if (!id) { setO(null); return; } get<CrOverview>(`/api/cr/overview?id=${encodeURIComponent(id)}`).then(setO).catch(() => setO(null)); }, [id, finished]);
  const running = useStore(live, (s) => Object.values(s.tasks).some((x) => x.kind === 'char' && x.meta?.char === id && (x.status === 'running' || x.status === 'queued')));
  return { id, o, running };
}

function useDone(id: string | undefined, cb: (t: TaskSummary) => void) {
  const ref = useRef(cb);
  ref.current = cb;
  useEffect(() => onTaskFinished((tk) => {
    if (tk.kind !== 'char' || tk.meta?.char !== id) return;
    if (tk.status === 'error') notifications.show({ color: 'rust', title: tk.title, message: tk.error || '' });
    else if (tk.status === 'done') notifications.show({ color: 'patina', message: tk.title });
    ref.current(tk);
  }), [id]);
}

const Need = () => { const t = useT(); return <div className="placeholder"><Text c="ember.3">{t('web.need_creature')}</Text></div>; };

export function CrOverviewScreen({ go }: { go: (r: Route) => void }) {
  const t = useT();
  const objs = useObjects();
  const { id, o } = useCreature();
  const [ask, setAsk] = useState(false);
  const add = async (f: File | null) => {
    if (!f) return;
    const [up] = await upload([f]);
    const r = await post<{ ok: boolean; id?: string; log?: string }>('/api/cr/add', { path: up.path });
    if (!r.ok || !r.id) { notifications.show({ color: 'rust', message: r.log || '' }); return; }
    objs.refresh(); objs.choose(r.id);
  };
  const del = async () => {
    if (!o) return;
    const r = await post<{ ok: boolean; log: string }>('/api/char/delete', { id: o.id });
    setAsk(false); notifications.show({ color: r.ok ? 'gray' : 'rust', message: r.log });
    if (r.ok) { objs.choose(null); objs.refresh(); }
  };
  const row = (title: string, state: string, ok: boolean, step: string, note?: string) => (
    <UnstyledButton className="ov-row" onClick={() => go({ section: 'creatures', step })}>
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <div style={{ minWidth: 0 }}><Text size="sm" fw={600}>{title}</Text><Text size="sm" c={ok ? 'patina.4' : 'dimmed'}>{state}</Text>{note && <Text size="xs" c="dimmed">{note}</Text>}</div>
        <Text size="xs" c="dimmed">{t('web.open')}</Text>
      </Group>
    </UnstyledButton>);
  const rig = o?.rig;
  const model = o ? o.rigged || o.source : null;
  return (
    <div className="work two">
      <div className="stage"><Viewer3D url={model ? fileUrl(model, o?.files.length) : null} empty={t(id ? 'web.ov_no_model' : 'web.need_creature')} person /></div>
      <ScrollArea className="panel">
        <Stack gap="sm" p="sm">
          <div><div className="panel-title">{o?.name || t('cr.section')}</div>{o && <div className="field-note">{o.dir}</div>}</div>
          {!id && <PickList creatures />}
          {o && <>
            {row(t('ui.skeleton'), rig ? t('web.cr_rig_state', rig.bones, Object.entries(rig.paws).map(([k, n]) => `${k} ${n}`).join(', ') || '—', rig.tail) : t('web.ov_none'), !!rig, 'skeleton',
              rig ? `${rig.jaw ? t('web.cr_jaw') : t('web.cr_no_jaw')}, ${rig.file}, ${rig.when}` : t('web.ov_skeleton_hint'))}
            {row(t('cr.anim_tab'), o.clips ? t('web.cr_clips', o.clips) : t('web.ov_none'), o.clips > 0, 'anim', o.humanoid ? t('cr.anim_humanoid') : undefined)}
            {row(t('web.step_paint'), o.paints.length ? o.paints.map((x) => x.title).join(', ') : t('web.ov_none'), o.paints.length > 0, 'paint')}
            {row(t('web.step_game'), t('cr.godot_btn'), false, 'game')}
          </>}
          <Group grow>
            <FileButton onChange={add} accept=".glb">{(p) => <Button {...p} variant="default" leftSection={<IconPlus size={16} />}>{t('ui.char_add')}</Button>}</FileButton>
            {o && <Button variant="default" leftSection={<IconFolder size={16} />} onClick={() => post('/api/open', { path: o.dir })}>{t('ui.char_open_folder')}</Button>}
          </Group>
          {o && <Button variant="subtle" color="rust" leftSection={<IconTrash size={16} />} onClick={() => setAsk(true)}>{t('ui.char_delete')}</Button>}
        </Stack>
      </ScrollArea>
      <Modal opened={ask} onClose={() => setAsk(false)} title={t('web.delete_title')} centered>
        <Stack>
          <Text size="sm">{o ? t('web.delete_text', o.name, o.dir) : ''}</Text>
          <Group justify="flex-end"><Button variant="default" onClick={() => setAsk(false)}>{t('web.cancel')}</Button><Button color="rust" onClick={del}>{t('ui.char_delete')}</Button></Group>
        </Stack>
      </Modal>
    </div>
  );
}

// the template markup page's hidden field and button (creatures.TPL_ID / TPL_GO)
const TPL_BRIDGE: [string, string] = ['sf3d_template_req', 'sf3d_template_go'];

export function CrSkeleton({ bridge, eyes }: { bridge: [string, string]; eyes?: boolean }) {
  const t = useT();
  const { colorScheme } = useMantineColorScheme();
  const { id, o, running } = useCreature();
  const [v, setV] = useState(0);
  // the skeleton by a template (a quadruped, a bird, a serpent: its joints placed on the model) or the viewer of the
  // skeleton there is (UniRig's or a template's: bones, weights, the jaw); at first the template while there is none
  const [how, setHow] = useState<string | null>(null);
  useEffect(() => setHow(null), [id]);
  // (chosen once a creature's overview comes: a build does not switch the page under the user)
  useEffect(() => { if (o && o.id === id && how === null) setHow(o.rigged ? 'viewer' : 'template'); }, [o, id, how]);
  useDone(id, () => setV(Date.now()));
  if (!id) return <Need />;
  const q = `id=${encodeURIComponent(id)}&theme=${colorScheme}&v=${v}`;
  const mode = eyes ? 'viewer' : how ?? (o && !o.rigged ? 'template' : 'viewer');
  return (
    <div className="equip">
      <Group className="equip-head" gap="sm" wrap="nowrap">
        {!eyes && <SegmentedControl size="xs" value={mode} onChange={setHow}
          data={[{ value: 'template', label: t('ct.mode_template') }, { value: 'viewer', label: t('ct.mode_viewer') }]} />}
        {mode === 'template' && <Text size="xs" c="dimmed" truncate style={{ flex: 1 }}>{plain(t('ct.mode_template_hint'))}</Text>}
        {mode === 'viewer' && !eyes && <>
          <Button size="compact-sm" disabled={running} onClick={() => post('/api/cr/rig', { id })}>{t('ui.make_the_skeleton_3_6_minutes_3_5_gb')}</Button>
          <Button size="compact-sm" variant="default" disabled={running || !o?.rigged} onClick={() => post('/api/cr/straighten', { id })}>{t('cr.straighten')}</Button>
          <Button size="compact-sm" variant="subtle" color="gray" disabled={running || !o?.rigged} onClick={() => post('/api/cr/restore', { id })}>{t('cr.restore')}</Button>
        </>}
        {mode === 'viewer' && <Text size="xs" c="dimmed" truncate style={{ flex: 1 }}>{plain(t(eyes ? 'web.cr_eyes_hint' : 'cr.view_info'))}</Text>}
      </Group>
      {mode === 'template' && o && (o.tpl_pictures || []).length > 0 && (
        <div className="shots">{(o.tpl_pictures || []).map((s) => <a key={s} href={fileUrl(s)} target="_blank" rel="noreferrer"><Image src={fileUrl(s, v)} h={110} w="auto" fit="contain" /></a>)}</div>)}
      {mode === 'template' ? (o?.source || o?.rigged
        ? <EditorFrame src={`/editor/creature?${q}&what=template`} fields={[TPL_BRIDGE[0]]} title={t('ct.title')}
          go={[{ id: TPL_BRIDGE[1], field: TPL_BRIDGE[0], onGo: (text) => post('/api/cr/template', { id, text }) }]} />
        : <div className="placeholder"><Text c="dimmed">{t('web.ov_no_model')}</Text></div>)
      : <>
      {!eyes && o && o.jaw_pictures.length > 0 && (
        <div className="shots">{o.jaw_pictures.map((s) => <a key={s} href={fileUrl(s)} target="_blank" rel="noreferrer"><Image src={fileUrl(s, v)} h={110} w="auto" fit="contain" /></a>)}</div>)}
      {o?.rigged ? <EditorFrame src={`/editor/creature?${q}&what=viewer`} fields={[bridge[0]]} title={t('cr.section')}
        go={[{ id: bridge[1], field: bridge[0], onGo: (text) => post('/api/cr/request', { id, text }) }]} />
        : <div className="placeholder"><Text c="dimmed">{plain(t('cr.rig_intro'))}</Text></div>}
      </>}
    </div>
  );
}

export function CrAnims() {
  const t = useT();
  const { colorScheme } = useMantineColorScheme();
  const { id, o, running } = useCreature();
  const [srcs, setSrcs] = useState<{ id: string; key: string; clips: string[]; picked: string[] }[]>([]);
  const [check, setCheck] = useState('');
  useEffect(() => { if (id) get<{ sources: typeof srcs }>(`/api/cr/clip_options?id=${encodeURIComponent(id)}`).then((r) => setSrcs(r.sources)); }, [id]);
  useDone(id, (tk) => { if (tk.meta?.what === 'clipcheck' && tk.status === 'done') setCheck(tk.result?.md || ''); });
  if (!id) return <Need />;
  const picks = Object.fromEntries(srcs.map((s) => [s.id, s.picked]));
  return (
    <div className="equip">
      <Group className="equip-head" gap="sm" wrap="nowrap">
        <Button size="compact-sm" disabled={running || !o?.rigged || o?.humanoid} onClick={() => post('/api/cr/animate', { id, picks })}>{t('cr.anim_go')}</Button>
        <Button size="compact-sm" variant="default" disabled={running || !o?.clips} onClick={() => post('/api/cr/check', { id })}>{t('cc.button')}</Button>
        <Button size="compact-sm" variant="default" disabled={running || !o?.rigged} onClick={() => post('/api/cr/godot', { id })}>{t('cr.godot_btn')}</Button>
        <Text size="xs" c="dimmed" truncate style={{ flex: 1 }}>{plain(o?.humanoid ? t('cr.anim_humanoid') : t('cr.anim_intro'))}</Text>
      </Group>
      {check && <div className="checkbar"><pre>{check}</pre><Button size="compact-xs" variant="subtle" color="gray" onClick={() => setCheck('')}>×</Button></div>}
      <div className="work two" style={{ flex: 1 }}>
        <div className="stage">
          {o?.clips ? <EditorFrame src={`/editor/creature?id=${encodeURIComponent(id)}&what=clips&theme=${colorScheme}&v=${o.clips}`} title={t('cr.anim_tab')} />
            : <Text className="viewer-empty">{t('cr.anim_view_none')}</Text>}
        </div>
        <ScrollArea className="panel">
          <Stack gap="sm" p="sm">
            <div className="panel-title">{t('cr.anim_tab')}</div>
            {srcs.map((s, i) => (
              <Checkbox.Group key={s.id} label={t(s.key)} value={s.picked} onChange={(val) => setSrcs(srcs.map((x, k) => (k === i ? { ...x, picked: val } : x)))}>
                <Stack gap={3} mt={4}>{s.clips.map((c) => <Checkbox key={c} size="xs" value={c} label={c} />)}</Stack>
              </Checkbox.Group>))}
          </Stack>
        </ScrollArea>
      </div>
    </div>
  );
}

export function CrPaint({ bridge }: { bridge: [string, string] }) {
  const t = useT();
  const { colorScheme } = useMantineColorScheme();
  const { id, o, running } = useCreature();
  const [cur, setCur] = useState('');
  const [v, setV] = useState(0);
  useDone(id, (tk) => { if (tk.status === 'done') { if (tk.meta?.what === 'paint') setCur(tk.result?.variant || ''); setV(Date.now()); } });
  if (!id) return <Need />;
  return (
    <div className="equip">
      <Group className="equip-head" gap="sm" wrap="nowrap">
        <Button size="compact-sm" variant="default" disabled={running || !o?.rigged} onClick={() => post('/api/cr/mend', { id, what: 'holes' })}>{t('cr.mend_holes')}</Button>
        <Button size="compact-sm" variant="default" disabled={running || !o?.rigged} onClick={() => post('/api/cr/mend', { id, what: 'normals' })}>{t('cr.mend_normals')}</Button>
        <Text size="xs" c="dimmed" truncate style={{ flex: 1 }}>{plain(t('cr.paint_intro'))}</Text>
      </Group>
      {o?.rigged ? <EditorFrame src={`/editor/creature?id=${encodeURIComponent(id)}&what=paint&current=${encodeURIComponent(cur)}&theme=${colorScheme}&v=${v}`}
        fields={[bridge[0]]} title={t('web.step_paint')} go={[{ id: bridge[1], field: bridge[0], onGo: (text) => post('/api/cr/paint', { id, text }) }]} />
        : <div className="placeholder"><Text c="dimmed">{t('cr.view_needs_skeleton')}</Text></div>}
    </div>
  );
}

export function CrGame() {
  const t = useT();
  const { id, o, running } = useCreature();
  if (!id) return <Need />;
  return (
    <div className="work two">
      <div className="stage"><Viewer3D url={o?.clips_file ? fileUrl(o.clips_file) : o?.rigged ? fileUrl(o.rigged) : null} empty={t('web.ov_no_model')} /></div>
      <ScrollArea className="panel">
        <Stack gap="sm" p="sm">
          <div className="panel-title">{t('web.step_game')}</div>
          <div className="field-note">{t('web.cr_game_intro')}</div>
          <Button disabled={running || !o?.rigged} onClick={() => post('/api/cr/godot', { id })}>{t('cr.godot_btn')}</Button>
          {o && <Button variant="default" leftSection={<IconFolder size={16} />} onClick={() => post('/api/open', { path: o.dir })}>{t('ui.char_open_folder')}</Button>}
        </Stack>
      </ScrollArea>
    </div>
  );
}
