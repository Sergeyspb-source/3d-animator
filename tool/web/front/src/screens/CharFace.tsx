// Character → Face: the face on the skeleton (a landmark rig has it from its markup; an auto-rig gets it marked and
// built here), the shared eyes / teeth / tongue set with its live view, the speech lines (lip-sync) played on the face.
import { useEffect, useRef, useState } from 'react';
import { Button, Checkbox, ColorInput, FileButton, Group, Image, NumberInput, ScrollArea, SegmentedControl, Select, Slider, Stack, Text,
  TextInput, Textarea, useMantineColorScheme } from '@mantine/core';
import { useLocalStorage } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconMicrophone } from '@tabler/icons-react';
import { fileUrl, get, live, onTaskFinished, post, upload, useStore } from '../api';
import { useT } from '../i18n';
import { useCurrent } from '../objects';
import type { Route } from '../nav';
import EditorFrame, { fieldValue } from '../components/EditorFrame';
import Viewer3D from '../components/Viewer3D';

type Mode = 'face' | 'parts' | 'speech';
interface FaceState { rigged: string | null; landmark: boolean; auto: boolean; summary: Record<string, any>; speech_model: string | null; clips: string[] }

const PARTS0 = { seed: 1, iris: '#4d8033', tongue: '#b8545c', eye_style: 'real', iris_size: 0, pupil: 0.42, slit: false, sclera: 0, veins: 0.35,
  per_side: 7, missing: '', missing_rand: 0, yellow: 0.15, crooked: 0.2, t_height: 1, t_volume: 1, canines: true, fangs: 0 };
type Parts = typeof PARTS0;

function Sl({ label, value, min, max, step, onChange, info }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; info?: string }) {
  return (
    <div>
      <Group justify="space-between" gap={4}><Text size="xs">{label}</Text><Text size="xs" c="dimmed">{value}</Text></Group>
      <Slider size="sm" min={min} max={max} step={step} value={value} onChange={onChange} label={null} />
      {info && <div className="field-note">{info}</div>}
    </div>
  );
}

function PartsPanel() {
  const t = useT();
  const [p, setP] = useLocalStorage<Parts>({ key: 'sf3d.face_parts', defaultValue: PARTS0 });
  const [name, setName] = useLocalStorage({ key: 'sf3d.face_parts_name', defaultValue: 'goblin' });
  const [view, setView] = useState<{ png?: string; glb?: string; log?: string }>({});
  const timer = useRef(0);
  const set = (patch: Partial<Parts>) => setP({ ...PARTS0, ...p, ...patch });
  const q = { ...PARTS0, ...p };
  useEffect(() => {   // the live view: remade a moment after the settings stop changing (made ones come at once)
    window.clearTimeout(timer.current);
    setView((v) => ({ ...v, log: t('face.preview_rendering') }));
    timer.current = window.setTimeout(async () => {
      try {
        const r = await post<{ png?: string; glb?: string; log?: string; skipped?: boolean }>('/api/face/parts/preview', q);
        if (!r.skipped) setView(r);
      } catch (e) { setView({ log: String(e) }); }
    }, 600);
  }, [JSON.stringify(q)]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = () => post('/api/face/parts/save', { name, params: q });
  return (
    <div className="work two" style={{ flex: 1 }}>
      <div className="stage">
        <Viewer3D url={view.glb ? fileUrl(view.glb, view.png) : null} empty={view.log || t('face.preview_rendering')} />
        {view.png && <div className="stage-strip"><div className="thumb"><Image src={fileUrl(view.png)} w={220} fit="contain" /></div></div>}
      </div>
      <ScrollArea className="panel">
        <Stack gap="xs" p="sm">
          <div className="panel-title">{t('web.face_parts')}</div>
          <div className="field-note">{t('face.procedural_eyes_a_ball_with_a_cornea')}</div>
          <Text size="xs" c="dimmed">{view.log}</Text>
          <Text size="sm" fw={600} mt="xs">{t('web.face_eyes')}</Text>
          <Group grow>
            <ColorInput size="xs" label={t('face.iris')} value={q.iris} onChange={(v) => set({ iris: v })} />
            <ColorInput size="xs" label={t('face.tongue')} value={q.tongue} onChange={(v) => set({ tongue: v })} />
          </Group>
          <div>
            <Text size="xs" mb={4}>{t('face.eye_style')}</Text>
            <SegmentedControl fullWidth size="xs" value={q.eye_style} onChange={(v) => set({ eye_style: v })}
              data={[{ value: 'real', label: t('face.realistic') }, { value: 'anime', label: t('face.anime') }]} />
          </div>
          <Sl label={t('face.iris_size_0_by_the_style_32_50')} value={q.iris_size} min={0} max={70} step={1} onChange={(v) => set({ iris_size: v })} />
          <Sl label={t('face.pupil_share_of_the_iris')} value={q.pupil} min={0.25} max={0.7} step={0.01} onChange={(v) => set({ pupil: v })} />
          <Checkbox size="xs" label={t('face.vertical_pupil_creatures')} checked={q.slit} onChange={(e) => set({ slit: e.currentTarget.checked })} />
          <Sl label={t('face.yellowness_of_the_white')} value={q.sclera} min={0} max={1} step={0.05} onChange={(v) => set({ sclera: v })} />
          <Sl label={t('face.veins_on_the_white')} value={q.veins} min={0} max={1} step={0.05} onChange={(v) => set({ veins: v })} />
          <Text size="sm" fw={600} mt="xs">{t('web.face_teeth')}</Text>
          <Sl label={t('face.teeth_per_half_arch')} value={q.per_side} min={4} max={8} step={1} onChange={(v) => set({ per_side: v })} />
          <TextInput size="xs" label={t('face.missing_teeth_e_g_u2_l4')} value={q.missing} onChange={(e) => set({ missing: e.currentTarget.value })} />
          <Sl label={t('face.random_gaps_share')} value={q.missing_rand} min={0} max={0.6} step={0.05} onChange={(v) => set({ missing_rand: v })} />
          <Sl label={t('face.teeth_yellowness_1_rotten_brown')} value={q.yellow} min={0} max={1} step={0.05} onChange={(v) => set({ yellow: v })} />
          <Sl label={t('face.teeth_crookedness')} value={q.crooked} min={0} max={1} step={0.05} onChange={(v) => set({ crooked: v })} />
          <Sl label={t('face.teeth_height')} value={q.t_height} min={0.5} max={1.6} step={0.05} onChange={(v) => set({ t_height: v })} />
          <Sl label={t('face.teeth_volume')} value={q.t_volume} min={0} max={1} step={0.05} onChange={(v) => set({ t_volume: v })} info={t('face.0_a_solid_white_strip_1_separate')} />
          <Checkbox size="xs" label={t('face.fangs_off_fangs_like_incisors')} checked={q.canines} onChange={(e) => set({ canines: e.currentTarget.checked })} />
          <Sl label={t('face.fang_length')} value={q.fangs} min={0} max={1} step={0.05} onChange={(v) => set({ fangs: v })} />
          <NumberInput size="xs" label={t('face.variant_random_seed')} value={q.seed} min={0} onChange={(v) => set({ seed: Number(v) || 0 })} />
          <TextInput size="sm" label={t('face.set_name_folder_export_face_parts')} value={name} onChange={(e) => setName(e.currentTarget.value)} mt="xs" />
          <Button onClick={save}>{t('face.generate_the_set')}</Button>
          <div className="field-note">{t('web.face_parts_note')}</div>
        </Stack>
      </ScrollArea>
    </div>
  );
}

export default function CharFace({ go, bridges }: { go: (r: Route) => void; bridges: { rigface: string } }) {
  const t = useT();
  const { colorScheme } = useMantineColorScheme();
  const cur = useCurrent();
  const id = cur && !cur.creature ? cur.id : undefined;
  const finished = useStore(live, (s) => s.finished);
  const [mode, setMode] = useLocalStorage<Mode>({ key: 'sf3d.face_mode', defaultValue: 'face' });
  const [st, setSt] = useState<FaceState | null>(null);
  const [v, setV] = useState(0);
  const [hasMarks, setHasMarks] = useState(false);
  const [clip, setClip] = useState<string | null>(null);
  const [audio, setAudio] = useState<{ name: string; path: string } | null>(null);
  const [text, setText] = useState('');
  const [lang, setLang] = useLocalStorage({ key: 'sf3d.lip_lang', defaultValue: 'ru' });
  const running = useStore(live, (s) => Object.values(s.tasks).some((x) => x.kind === 'char' && x.meta?.char === id && (x.status === 'running' || x.status === 'queued')));

  useEffect(() => { if (id) get<FaceState>(`/api/face/state?id=${encodeURIComponent(id)}`).then(setSt).catch(() => setSt(null)); }, [id, finished]);
  useEffect(() => { setClip(null); setHasMarks(false); }, [id]);
  useEffect(() => onTaskFinished((tk) => {
    if (tk.status === 'error') notifications.show({ color: 'rust', title: tk.title, message: tk.error || '' });
    else if (tk.status === 'done' && (tk.kind === 'face_parts' || (tk.kind === 'char' && tk.meta?.char === id))) notifications.show({ color: 'patina', message: tk.title });
    if (tk.kind === 'char' && tk.meta?.char === id && tk.status === 'done') {
      if (tk.meta?.what === 'lipsync' && tk.result?.clip) { setClip(tk.result.clip); setV(Date.now()); }
      if (tk.meta?.what === 'face') setV(Date.now());
    }
  }), [id]);

  if (!id) return <div className="placeholder"><Text c="ember.3">{t('web.need_character')}</Text></div>;
  const q = `id=${encodeURIComponent(id)}&theme=${colorScheme}&v=${v}`;
  const head = (
    <Group className="equip-head" gap="md" wrap="nowrap">
      <SegmentedControl size="xs" value={mode} onChange={(m) => setMode(m as Mode)} data={[
        { value: 'face', label: t('web.face_on_rig') }, { value: 'parts', label: t('web.face_parts') }, { value: 'speech', label: t('web.face_speech') }]} />
      <Text size="xs" c="dimmed" truncate style={{ flex: 1 }}>
        {mode === 'face' ? (st?.auto ? t('lm.rig_face_mark_hint') : '') : mode === 'speech' ? t('lm.the_model_is_taken_from_the_skeleton') : ''}
      </Text>
      {mode === 'face' && st?.auto && <Button size="compact-sm" disabled={!hasMarks || running}
        onClick={() => post('/api/face/build', { id, markup: fieldValue(bridges.rigface) })}>{t('lm.rig_face_build')}</Button>}
    </Group>
  );

  let body;
  if (mode === 'parts') body = <PartsPanel />;
  else if (mode === 'face') {
    if (st?.auto) body = <EditorFrame src={`/editor/face?${q}&mode=mark`} fields={[bridges.rigface]} onField={(_, val) => setHasMarks(!!val)} title={t('web.step_face')} />;
    else body = (
      <div className="placeholder">
        <Stack gap="sm" maw={560}>
          <Text fw={600}>{st?.landmark ? t('web.face_landmark_title') : t('web.face_no_rig_title')}</Text>
          <Text size="sm" c="dimmed">{st?.landmark ? t('lm.rig_face_landmark') : t('lm.rig_pose_needs_a_skeleton')}</Text>
          {st?.landmark && <Text size="sm">{[st.summary.mouth === 'cut' ? t('web.ov_mouth_cut') : st.summary.mouth === 'plate' ? t('web.ov_mouth_plate') : '',
            st.summary.eyes && t('web.ov_eyes'), st.summary.retopo && t('web.ov_retopo')].filter(Boolean).join(', ') || t('web.ov_none')}</Text>}
          <Group><Button variant="default" onClick={() => go({ section: 'character', step: 'skeleton' })}>{t('ui.skeleton')}</Button></Group>
        </Stack>
      </div>);
  } else {
    const clips = st?.clips || [];
    const shown = clip && clips.includes(clip) ? clip : clips[clips.length - 1] || null;
    body = (
      <div className="work two" style={{ flex: 1 }}>
        <div className="stage">
          {shown ? <EditorFrame src={`/editor/face?${q}&mode=say&clip=${encodeURIComponent(shown)}`} title={t('web.face_speech')} allow="autoplay" />
            : <Text className="viewer-empty">{st?.speech_model ? t('lm.no_lipsync_clips_yet') : t('lm.build_the_skeleton_from_the_markup')}</Text>}
        </div>
        <ScrollArea className="panel">
          <Stack gap="sm" p="sm">
            <div className="panel-title">{t('web.face_speech')}</div>
            <Select size="sm" label={t('lm.lipsync_clips')} data={clips} value={shown} onChange={setClip} placeholder={t('web.ov_none')} />
            <Text size="sm" fw={600} mt="sm">{t('lm.make_the_lipsync_clip')}</Text>
            <FileButton accept=".mp3,.wav,.ogg" onChange={async (f) => { if (f) { const [u] = await upload([f]); setAudio(u); } }}>
              {(pp) => <Button {...pp} variant="default" leftSection={<IconMicrophone size={16} />}>{audio ? audio.name : t('lm.voice_mp3_wav_ogg')}</Button>}
            </FileButton>
            <Textarea size="sm" label={t('lm.the_exact_text_of_the_line_empty_as')} value={text} onChange={(e) => setText(e.currentTarget.value)} autosize minRows={2} />
            <div>
              <Text size="xs" mb={4}>{t('face.tongue')}</Text>
              <SegmentedControl size="xs" value={lang} onChange={setLang} data={['ru', 'en']} />
            </div>
            <Button disabled={!audio || !st?.speech_model || running} onClick={() => post('/api/face/lipsync', { id, audio: audio!.path, text, lang })}>
              {t('lm.make_the_lipsync_clip')}</Button>
          </Stack>
        </ScrollArea>
      </div>
    );
  }
  return <div className="equip">{head}{body}</div>;
}
