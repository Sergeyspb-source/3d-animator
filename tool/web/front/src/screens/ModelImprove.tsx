// Models → Improve: a draft made closer to its pictures before release (tool/model_improve.py). The list: the drafts
// (as in Check); the stage: the draft in 3D (after / before), or the pins editor of one view; the panel: the pictures by
// side (the draft's own, uploaded, drawn by ChatGPT), the missing sides to draw, the steps (texture from the pictures,
// mirrored side, symmetry, relief), «Improve» (a queued task) and «Undo».
import { useEffect, useState } from 'react';
import { Button, Checkbox, FileButton, Group, ScrollArea, SegmentedControl, Slider, Stack, Switch, Text, Tooltip } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconPin, IconPhotoUp, IconX, IconCheck, IconArrowBackUp, IconSparkles } from '@tabler/icons-react';
import { fileUrl, get, live, post, upload, useStore, type ModelInfo } from '../api';
import { useT } from '../i18n';
import type { Route } from '../nav';
import Viewer3D from '../components/Viewer3D';
import PinEditor, { type AlignData, type Pin, type Stroke } from '../components/PinEditor';
import { CAT_KEY, ModelList } from './ModelCheck';
import './ModelImprove.css';
import { ZoomImage } from '../components/Zoom';

const VIEWS = ['front', 'back', 'left', 'right'] as const;
type ViewName = typeof VIEWS[number];
const VIEW_KEY: Record<ViewName, string> = { front: 'web.imp_front', back: 'web.imp_back', left: 'web.imp_left', right: 'web.imp_right' };
const KIND_KEY: Record<string, string> = { concept: 'web.imp_kind_concept', codex: 'web.imp_kind_codex', upload: 'web.imp_kind_upload' };
// the skins laid flat (a character's): the view the pins editor opens, the texts' key (web.imp_<key>, _note, _tip)
const SKINS = [['skin_head', 'skin'], ['skin_ears', 'ears'], ['skin_torso', 'torso'], ['skin_arms', 'arms'], ['skin_legs', 'legs']] as const;
type SkinView = typeof SKINS[number][0];
interface Opts { project: boolean; mirror: boolean; sharp: number; delight: number; sym: string; relief: boolean; face?: boolean }
interface Status {
  engine: string; category: string; pictures: Record<string, { path: string; kind: string }>;
  codex: Record<string, { path: string; render: string; accepted: boolean; seconds?: number }>; pins: Record<string, number>; marks?: Record<string, number>;
  options: Opts & { codex_missing?: string[] }; defaults: Opts & { codex_missing: string[] }; has_raw: boolean;
  improved: null | { steps: string[]; seconds: Record<string, number>; when: string; fit?: Record<string, number | null> };
  can_undo: boolean; before: string | null; fit: Record<string, number | null>;
  face?: { available: boolean; found?: boolean; on_picture?: boolean; on_model?: boolean };
}

export default function ModelImprove({ go }: { go: (r: Route) => void }) {
  const t = useT();
  const finished = useStore(live, (s) => s.finished);
  const [items, setItems] = useState<ModelInfo[]>([]);
  const [sel, setSel] = useState<string | null>(() => localStorage.getItem('sf3d.improve_sel') || localStorage.getItem('sf3d.check_sel'));
  const [st, setSt] = useState<Status | null>(null);
  const [opts, setOpts] = useState<Opts | null>(null);
  const [look, setLook] = useState<'after' | 'before'>('after');
  const [pinView, setPinView] = useState<ViewName | SkinView | null>(null);
  const [align, setAlign] = useState<AlignData | null>(null);
  const [aligning, setAligning] = useState(false);
  const [draw, setDraw] = useState<string[]>([]);
  const m = items.find((x) => `${x.category}/${x.stem}` === sel);
  const q = m ? `category=${encodeURIComponent(m.category)}&stem=${encodeURIComponent(m.stem)}` : '';

  const loadList = () => get<ModelInfo[]>('/api/models/drafts').then((d) => {
    setItems(d);
    setSel((s) => (s && d.some((x) => `${x.category}/${x.stem}` === s) ? s : d[0] ? `${d[0].category}/${d[0].stem}` : null));
  });
  const loadStatus = () => (m ? get<Status>(`/api/models/improve/status?${q}`).then((s) => {
    setSt(s);
    setOpts((o) => o ?? { ...s.defaults, ...s.options });
    setDraw((d) => (d.length ? d.filter((v) => !s.pictures[v]) : s.defaults.codex_missing || []));
  }) : Promise.resolve());
  useEffect(() => { loadList(); }, [finished]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setOpts(null); setDraw([]); setPinView(null); setLook('after'); }, [sel]);
  useEffect(() => { loadStatus(); }, [sel, finished, m?.time]); // eslint-disable-line react-hooks/exhaustive-deps
  const pick = (x: ModelInfo) => { const id = `${x.category}/${x.stem}`; setSel(id); localStorage.setItem('sf3d.improve_sel', id); };

  const openPins = async (v: ViewName | SkinView) => {
    if (!m) return;
    setAligning(true); setPinView(v); setAlign(null);
    try {
      const a = await get<AlignData & { ok: boolean }>(`/api/models/improve/align?${q}&view=${v}`);
      if (a.ok) setAlign(a);
      else {
        setPinView(null);
        if ((a as any).error) notifications.show({ color: 'yellow', message: t(v === 'skin_ears' ? 'web.imp_ears_none' : 'web.imp_body_none') });
      }
    } catch (e: any) { notifications.show({ color: 'red', message: String(e.message || e) }); setPinView(null); }
    finally { setAligning(false); }
  };
  const savePins = async (pins: Pin[], marks: Record<string, [number, number]>, brush?: Stroke[]) => {
    if (!m || !pinView) return;
    setSt(await post<Status>('/api/models/improve/pins', { category: m.category, stem: m.stem, view: pinView, pins, marks, brush }));
    notifications.show({ color: 'patina', message: t('web.imp_pins_saved') });
    if (brush) {   // (a skin: its picture layer drawn again with the strokes, as the projection will take them)
      try {
        const a = await get<AlignData & { ok: boolean }>(`/api/models/improve/align?${q}&view=${pinView}`);
        if (a.ok) setAlign(a);
      } catch { /* the old layer stays */ }
    }
  };
  // a landmark's model point moved: the server puts it back onto the model (3D) and draws the view's marks again
  const moveMark3d = async (name: string, x: number, y: number, mirror: boolean) => {
    if (!m || !pinView) return null;
    try {
      return await post<AlignData>('/api/models/improve/mark3d', { category: m.category, stem: m.stem, view: pinView, name, x, y, mirror });
    } catch (e: any) { notifications.show({ color: 'red', message: String(e.message || e) }); return null; }
  };
  const setPicture = async (v: ViewName, f: File | null) => {
    if (!m) return;
    let path: string | null = null;
    if (f) path = (await upload([f]))[0].path;
    setSt(await post<Status>('/api/models/improve/picture', { category: m.category, stem: m.stem, view: v, path }));
  };
  const accept = async (v: string, yes: boolean) => {
    if (!m) return;
    setSt(await post<Status>('/api/models/improve/codex_accept', { category: m.category, stem: m.stem, view: v, accept: yes }));
  };
  const runImprove = async () => {
    if (!m || !opts) return;
    const r = await post<{ ok: boolean; log?: string }>('/api/models/improve/run', { category: m.category, stem: m.stem, ...opts });
    notifications.show({ color: r.ok ? 'patina' : 'red', message: r.ok ? t('web.imp_queued') : r.log || '' });
  };
  const runCodex = async () => {
    if (!m || !draw.length) return;
    const r = await post<{ ok: boolean; log?: string }>('/api/models/improve/codex', { category: m.category, stem: m.stem, views: draw });
    notifications.show({ color: r.ok ? 'patina' : 'red', message: r.ok ? t('web.imp_codex_queued') : r.log || '' });
  };
  const undo = async () => {
    if (!m) return;
    const r = await post<Status & { ok: boolean }>('/api/models/improve/undo', { category: m.category, stem: m.stem });
    setSt(r); loadList();
    notifications.show({ color: r.ok ? 'gray' : 'red', message: t(r.ok ? 'web.imp_undone' : 'web.imp_nothing_to_undo') });
  };
  const set = (k: keyof Opts, v: any) => setOpts((o) => (o ? { ...o, [k]: v } : o));
  const missing = st ? VIEWS.filter((v) => !st.pictures[v]) : [];
  const char = st?.category === 'character' || st?.category === 'creature';

  return (
    <div className="work three">
      <div className="side">
        <div className="side-title">{t('web.drafts')}</div>
        <ModelList items={items} sel={sel} onPick={pick} empty={t('web.no_drafts')} />
      </div>
      <div className="stage">
        {pinView ? (align ? <PinEditor key={`${sel}/${pinView}`} data={align} onSave={savePins} onMark3d={moveMark3d} onClose={() => { setPinView(null); setAlign(null); }} />
          : <div className="stage-wait"><Text c="dimmed" size="sm">{aligning ? t('web.imp_fitting') : ''}</Text></div>) : (
          <>
            <Viewer3D url={m ? fileUrl(look === 'before' && st?.before ? st.before : m.glb, m.time) : null} empty={t('web.check_empty')} />
            {st?.can_undo && <div className="stage-look"><SegmentedControl size="xs" value={look} onChange={(x) => setLook(x as any)}
              data={[{ value: 'after', label: t('web.imp_after') }, { value: 'before', label: t('web.imp_before') }]} /></div>}
          </>)}
      </div>
      <ScrollArea className="panel">
        {m && st && opts ? (
          <Stack gap="sm" p="sm">
            <div><div className="panel-title">{m.stem}</div>
              <div className="field-note">{t(CAT_KEY[m.category] || m.category)} · {st.engine === 'hunyuan' ? 'Hunyuan3D' : st.engine === 'trellis' ? 'TRELLIS.2' : 'SF3D'}</div></div>

            <div className="imp-block">
              <div className="imp-head">{t('web.imp_pictures')}</div>
              <div className="field-note">{t('web.imp_pictures_note')}</div>
              {VIEWS.map((v) => {
                const p = st.pictures[v], c = st.codex[v];
                const mirrored = !p && opts.mirror && ((v === 'right' && st.pictures.left) || (v === 'left' && st.pictures.right));
                return (
                  <div key={v} className="imp-view">
                    <div className="imp-thumb">{p ? <ZoomImage src={p.path} group={VIEWS.map((x) => st.pictures[x]?.path).filter(Boolean) as string[]} caption={t(VIEW_KEY[v] || v)} fit="contain" h={64} w={52} />
                      : c ? <ZoomImage src={c.path} fit="contain" h={64} w={52} style={{ opacity: 0.7 }} /> : <span className="imp-none">—</span>}</div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <Group gap={6} wrap="nowrap"><Text size="sm" fw={600}>{t(VIEW_KEY[v])}</Text>
                        <span className={'tag' + (p?.kind === 'codex' ? ' warm' : '')}>{p ? t(KIND_KEY[p.kind] || p.kind) : mirrored ? t('web.imp_kind_mirror') : c ? t('web.imp_kind_candidate') : t('web.imp_kind_none')}</span></Group>
                      <Text size="xs" c="dimmed">{[st.fit[v] != null ? t('web.imp_fit', Math.round((st.fit[v] as number) * 100)) : null,
                        st.pins[v] ? t('web.imp_pins_n', st.pins[v]) : null, st.marks?.[v] ? t('web.imp_marks_n', st.marks[v]) : null].filter(Boolean).join(' · ') || ' '}</Text>
                    </div>
                    <Group gap={4} wrap="nowrap">
                      {p && <Tooltip label={t('web.imp_fit_by_hand')}><Button size="compact-xs" variant="default" onClick={() => openPins(v)} leftSection={<IconPin size={14} />}>{t('web.imp_pins')}</Button></Tooltip>}
                      {!p && c && <>
                        <Tooltip label={t('web.imp_accept')}><Button size="compact-xs" color="patina" variant="light" onClick={() => accept(v, true)}><IconCheck size={14} /></Button></Tooltip>
                        <Tooltip label={t('web.imp_reject')}><Button size="compact-xs" variant="default" onClick={() => accept(v, false)}><IconX size={14} /></Button></Tooltip></>}
                      <FileButton accept="image/png,image/jpeg,image/webp" onChange={(f) => f && setPicture(v, f)}>
                        {(props) => <Tooltip label={t('web.imp_upload')}><Button size="compact-xs" variant="default" {...props}><IconPhotoUp size={14} /></Button></Tooltip>}
                      </FileButton>
                      {p && <Tooltip label={t('web.imp_drop')}><Button size="compact-xs" variant="subtle" color="gray" onClick={() => setPicture(v, null)}><IconX size={14} /></Button></Tooltip>}
                    </Group>
                  </div>
                );
              })}
              {Object.entries(st.codex).filter(([v, c]) => !c.accepted && !st.pictures[v]).length > 0 && (
                <div className="field-note">{t('web.imp_candidates_note')}</div>)}
              {char && Object.keys(st.pictures).length > 0 && SKINS.map(([v, key]) => (   // the head, the ears, the body laid flat
                <div key={v} className="imp-view">
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Text size="sm" fw={600}>{t(`web.imp_${key}`)}</Text>
                    <Text size="xs" c="dimmed">{st.pins[v] ? t('web.imp_pins_n', st.pins[v]) : t(`web.imp_${key}_note`)}</Text>
                  </div>
                  <Tooltip label={t(`web.imp_${key}_tip`)} multiline w={300}><Button size="compact-xs" variant="default" onClick={() => openPins(v)}
                    leftSection={<IconPin size={14} />}>{t('web.imp_pins')}</Button></Tooltip>
                </div>))}
            </div>

            {missing.length > 0 && st.pictures.front && (
              <div className="imp-block">
                <div className="imp-head">{t('web.imp_codex')}</div>
                <div className="field-note">{t('web.imp_codex_note')}</div>
                <Group gap="sm">{missing.map((v) => <Checkbox key={v} size="xs" label={t(VIEW_KEY[v])} checked={draw.includes(v)}
                  onChange={(e) => setDraw((d) => (e.currentTarget.checked ? [...d, v] : d.filter((x) => x !== v)))} />)}</Group>
                <Button variant="default" leftSection={<IconSparkles size={16} />} disabled={!draw.length} onClick={runCodex}>{t('web.imp_codex_btn', draw.length)}</Button>
              </div>)}

            <div className="imp-block">
              <div className="imp-head">{t('web.imp_steps')}</div>
              <Switch label={t('web.imp_project')} description={t('web.imp_project_note')} checked={opts.project} onChange={(e) => set('project', e.currentTarget.checked)} />
              {char && <Switch label={t('web.imp_mirror')} checked={opts.mirror} disabled={!opts.project} onChange={(e) => set('mirror', e.currentTarget.checked)} />}
              {char && st.pictures.front && (   // the front picture's face fitted by its points (MediaPipe)
                <Switch label={t('web.imp_face')} checked={!!opts.face && !!st.face?.available} disabled={!opts.project || !st.face?.available}
                  onChange={(e) => set('face', e.currentTarget.checked)}
                  description={!st.face?.available ? t('web.imp_face_na') : st.face?.found === false ? t('web.imp_face_none')
                    : st.face?.found ? `${t('web.imp_face_found')} · ${t('web.imp_face_note')}` : t('web.imp_face_note')} />)}
              <div><Text size="sm">{t('web.imp_sym')}</Text><div className="field-note">{t('web.imp_sym_note')}</div>
                <SegmentedControl size="xs" mt={4} value={opts.sym} onChange={(x) => set('sym', x)} data={[
                  { value: 'off', label: t('web.imp_sym_off') }, { value: 'auto', label: t('web.imp_sym_auto') },
                  { value: 'pos', label: t('web.imp_sym_left') }, { value: 'neg', label: t('web.imp_sym_right') }]} /></div>
              <Switch label={t('web.imp_relief')} description={st.has_raw ? t('web.imp_relief_note') : t('web.imp_relief_none')} checked={opts.relief && st.has_raw}
                disabled={!st.has_raw} onChange={(e) => set('relief', e.currentTarget.checked)} />
              <div><Text size="sm">{t('web.imp_sharp')}</Text><div className="field-note">{t('web.imp_sharp_note')}</div>
                <Slider size="sm" min={1} max={8} step={0.5} value={opts.sharp} onChange={(x) => set('sharp', x)} disabled={!opts.project} /></div>
              <div><Text size="sm">{t('web.imp_delight')}</Text><div className="field-note">{t('web.imp_delight_note')}</div>
                <Slider size="sm" min={0} max={1} step={0.05} value={opts.delight} onChange={(x) => set('delight', x)} disabled={!opts.project} /></div>
            </div>

            <Button onClick={runImprove} disabled={!opts.project && opts.sym === 'off' && !(opts.relief && st.has_raw)}>{t('web.imp_run')}</Button>
            <Button variant="default" leftSection={<IconArrowBackUp size={16} />} disabled={!st.can_undo} onClick={undo}>{t('web.imp_undo')}</Button>
            <div className="field-note">{t('web.imp_time_note')}</div>
            {st.improved && <div className="field-note">{t('web.imp_last', st.improved.when, st.improved.seconds?.total ?? '—', st.improved.steps.join(', '))}</div>}
            <Button variant="subtle" color="gray" onClick={() => go({ section: 'models', step: 'check' })}>{t('web.imp_to_check')}</Button>
          </Stack>
        ) : <Text p="md" c="dimmed" size="sm">{t('web.no_drafts')}</Text>}
      </ScrollArea>
    </div>
  );
}
