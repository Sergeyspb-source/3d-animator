// Equipment (Workshop, Materials and textures, Fitting, Check, Release) and Character → Looks: one procedural editor
// for all of them, on the current character. Moving between the steps keeps the editor (its 3D scene, the piece on):
// the step goes to it as a message and its rail shows that step's part (tool/web/adapters/armour_editor.*).
// Its requests reach the server through the hidden field and button below (the editor's own way to talk to its page).
import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Group, Image, SegmentedControl, Text, useMantineColorScheme } from '@mantine/core';
import { useLocalStorage } from '@mantine/hooks';
import { WearPanel, OutfitPanel } from './EquipTools';
import { notifications } from '@mantine/notifications';
import { IconPhoto } from '@tabler/icons-react';
import { fileUrl, onTaskFinished } from '../api';
import { useI18n } from '../i18n';
import { asCharacter, useCurrent } from '../objects';
import LoadingVeil, { useFrameLoading } from '../components/LoadingVeil';
import type { Step } from '../nav';

interface Shot { path: string; caption: string }

export default function EquipWorkspace({ step, info, bridge, wear }: { step: string; info?: Step; bridge: [string, string]; wear: string[] }) {
  const { t, lang } = useI18n();
  const { colorScheme } = useMantineColorScheme();
  const cur = useCurrent();
  const frame = useRef<HTMLIFrameElement>(null);
  const stepNow = useRef(step);
  stepNow.current = step;
  const [piece, setPiece] = useState<{ label: string; piece: string | null } | null>(null);
  const [shots, setShots] = useState<Shot[]>([]);
  const [showShots, setShowShots] = useState(false);
  const [tool, setTool] = useLocalStorage<'make' | 'ready' | 'outfit'>({ key: 'sf3d.eq_tool', defaultValue: 'make' });
  const way = step === 'workshop' ? tool : 'make';
  const rigged = asCharacter(cur) ? cur.rigged : null;
  // a new page only for another character, theme or language (the step it opens on is the one shown then)
  const src = useMemo(() => (rigged ? `/editor/equip?rigged=${encodeURIComponent(rigged)}&step=${stepNow.current}&theme=${colorScheme}&lang=${lang}` : null),
    [rigged, colorScheme, lang]);

  const loading = useFrameLoading(frame, way === 'make' ? src : null);
  useEffect(() => { frame.current?.contentWindow?.postMessage({ type: 'sf3d-step', step }, location.origin); }, [step]);
  useEffect(() => {
    const on = (e: MessageEvent) => { if (e.origin === location.origin && e.data?.type === 'sf3d-piece') setPiece(e.data); };
    window.addEventListener('message', on);
    return () => window.removeEventListener('message', on);
  }, []);
  useEffect(() => onTaskFinished((tk) => {
    if (tk.kind === 'equip' && tk.result?.shots?.length) { setShots(tk.result.shots); setShowShots(true); }
    if (tk.kind === 'equip' && tk.status === 'error') notifications.show({ color: 'rust', title: tk.title, message: tk.error || '' });
  }), []);

  const send = async () => {   // the editor wrote its request into the field and «clicked» the button
    const ta = document.querySelector<HTMLTextAreaElement>(`#${bridge[0]} textarea`);
    if (!ta || !ta.value) return;
    try {
      const r = await fetch('/api/equip/action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: ta.value });
      const js = await r.json();
      if (!r.ok) throw new Error(js.detail || r.statusText);
      if (js.shots?.length) { setShots(js.shots); setShowShots(true); }
    } catch (e) {
      notifications.show({ color: 'rust', message: String(e) });
    }
  };

  return (
    <div className="equip">
      <Group className="equip-head" gap="md" wrap="nowrap">
        <Text size="sm" fw={600} style={{ whiteSpace: 'nowrap' }}>{t('web.piece')}: <Text span c={piece?.label ? undefined : 'dimmed'} fw={600}>{piece?.label || t('web.no_piece')}</Text></Text>
        <Text size="xs" c="dimmed" truncate style={{ flex: 1 }}>{info ? t(info.about) : ''}</Text>
        {step === 'workshop' && <SegmentedControl size="xs" value={tool} onChange={(v) => setTool(v as typeof tool)}
          data={[{ value: 'make', label: t('web.eq_make') }, { value: 'ready', label: t('web.eq_ready_glb') }, { value: 'outfit', label: t('web.eq_outfit') }]} />}
        {shots.length > 0 && <Button size="compact-sm" variant={showShots ? 'light' : 'subtle'} color="gray" leftSection={<IconPhoto size={14} />} onClick={() => setShowShots(!showShots)}>{t('web.shots', shots.length)}</Button>}
      </Group>
      {showShots && shots.length > 0 && (
        <div className="shots">{shots.map((s) => (
          <a key={s.path} href={fileUrl(s.path)} target="_blank" rel="noreferrer" title={s.caption}><Image src={fileUrl(s.path)} h={150} w="auto" fit="contain" /></a>))}
        </div>)}
      {way === 'ready' ? <WearPanel ids={wear} /> : way === 'outfit' ? <OutfitPanel /> :
        src ? <div className="frame-box"><iframe ref={frame} key={src} src={src} className="equip-frame" title={t('web.editor_title')} />{loading && <LoadingVeil text={t('web.loading_model')} />}</div>
        : <div className="placeholder"><Text c="ember.3">{asCharacter(cur) ? t('web.need_rig', cur.name) : t('web.need_character')}</Text></div>}
      <div id={bridge[0]} hidden><textarea defaultValue="" /></div>
      <button id={bridge[1]} type="button" hidden onClick={send} />
    </div>
  );
}
