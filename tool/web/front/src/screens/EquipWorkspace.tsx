// Equipment: Catalog → Workshop (shape, fit, materials) → Check → Release, and Character → Looks. One procedural editor
// (tool/armour_gen_editor.html) stays loaded under all of them, on the current character: the Workshop and Looks show it
// with their part of its rail, Check shows its stage beside the shell's report, Catalog and Release cover it with pages
// of their own (EquipSteps). It talks to the shell by messages (adapters/armour_editor.js): the piece on and its
// catalogue come from it; the shell asks it to take a piece, to open one made before, to press its buttons. Its
// requests reach the server through the hidden field and button below (the editor's own way to talk to its page).
import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Group, Image, SegmentedControl, Text, useMantineColorScheme } from '@mantine/core';
import { useLocalStorage } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconPhoto } from '@tabler/icons-react';
import { WearPanel, OutfitPanel } from './EquipTools';
import { CatalogPage, CheckPanel, ReleasePage, WorkshopEmpty, type CatBlock, type Made, type PieceOn } from './EquipSteps';
import { fileUrl, get, onTaskFinished } from '../api';
import { useI18n } from '../i18n';
import { asCharacter, useCurrent } from '../objects';
import LoadingVeil, { useFrameLoading } from '../components/LoadingVeil';
import type { Route, Step } from '../nav';

interface Shot { path: string; caption: string }
type Tab = 'shape' | 'fit' | 'materials';
const TABS: Tab[] = ['shape', 'fit', 'materials'];

export default function EquipWorkspace({ step, info, bridge, wear, go }:
  { step: string; info?: Step; bridge: [string, string]; wear: string[]; go: (r: Route) => void }) {
  const { t, lang } = useI18n();
  const { colorScheme } = useMantineColorScheme();
  const cur = useCurrent();
  const frame = useRef<HTMLIFrameElement>(null);
  const [tab, setTab] = useLocalStorage<Tab>({ key: 'sf3d.eq_tab', defaultValue: 'shape' });
  const [mode, setMode] = useLocalStorage<'make' | 'ready' | 'outfit'>({ key: 'sf3d.eq_tool', defaultValue: 'make' });
  const [catalog, setCatalog] = useLocalStorage<CatBlock[]>({ key: 'sf3d.eq_catalog', defaultValue: [] });
  const [piece, setPiece] = useState<PieceOn | null>(null);
  const [made, setMade] = useState<Made | null>(null);
  const [shots, setShots] = useState<Shot[]>([]);
  const [showShots, setShowShots] = useState(false);
  const rigged = asCharacter(cur) ? cur.rigged : null;
  const editorStep = step === 'workshop' ? (TABS.includes(tab) ? tab : 'shape') : step;   // (what the editor shows)
  const stepNow = useRef(editorStep);
  stepNow.current = editorStep;
  // a new page only for another character, theme or language (the step it opens on is the one shown then)
  const src = useMemo(() => (rigged ? `/editor/equip?rigged=${encodeURIComponent(rigged)}&step=${stepNow.current}&theme=${colorScheme}&lang=${lang}` : null),
    [rigged, colorScheme, lang]);
  const loading = useFrameLoading(frame, src);
  const toEditor = (msg: object) => frame.current?.contentWindow?.postMessage(msg, location.origin);

  useEffect(() => { toEditor({ type: 'sf3d-step', step: editorStep }); }, [editorStep]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const on = (e: MessageEvent) => {
      if (e.origin !== location.origin || e.source !== frame.current?.contentWindow) return;
      if (e.data?.type === 'sf3d-piece') setPiece(e.data);
      else if (e.data?.type === 'sf3d-catalog' && Array.isArray(e.data.blocks) && e.data.blocks.length) setCatalog(e.data.blocks);
    };
    window.addEventListener('message', on);
    return () => window.removeEventListener('message', on);
  }, [setCatalog]);
  useEffect(() => { setPiece(null); }, [rigged]);
  const loadMade = () => { if (rigged) get<Made>(`/api/equip/made?rigged=${encodeURIComponent(rigged)}`).then(setMade).catch(() => setMade(null)); };
  useEffect(() => { setMade(null); loadMade(); }, [rigged]); // eslint-disable-line react-hooks/exhaustive-deps
  const goStep = (s: string) => go({ section: 'equipment', step: s });
  useEffect(() => onTaskFinished((tk) => {
    if (tk.kind !== 'equip') return;
    loadMade();
    if (tk.result?.shots?.length && tk.meta?.action !== 'qa') { setShots(tk.result.shots); setShowShots(true); }
    if (tk.status === 'error') notifications.show({ color: 'rust', title: tk.title, message: tk.error || '' });
    else if (tk.status === 'done' && tk.meta?.action === 'generate')   // the bake made: the check is next
      notifications.show({ color: 'patina', title: tk.title, message: (
        <Group gap="xs" justify="space-between"><Text size="sm">{t('web.eq_baked_next')}</Text>
          <Button size="compact-xs" onClick={() => goStep('check')}>{t('web.eq_to_check')}</Button></Group>) });
  }), []); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (p: string, style: string | null) => { toEditor({ type: 'sf3d-pick', piece: p, style }); if (step !== 'workshop') goStep('workshop'); };
  const open = (item: string) => { toEditor({ type: 'sf3d-open', item }); goStep('workshop'); };
  const check = (item: string) => { toEditor({ type: 'sf3d-open', item }); goStep('check'); };
  const press = (id: string) => toEditor({ type: 'sf3d-click', id });

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

  const pieceName = <Text size="sm" fw={600} style={{ whiteSpace: 'nowrap' }}>{t('web.piece')}: <Text span c={piece?.label ? undefined : 'dimmed'} fw={600}>{piece?.label || t('web.no_piece')}</Text></Text>;
  const about = step === 'workshop' ? t(`web.eq_tab_${editorStep}_about`) : info ? t(info.about) : '';
  const cover = step === 'catalog' || step === 'release' || (step === 'workshop' && !!src && !piece?.piece && !loading);
  return (
    <div className="equip">
      <Group className="equip-head" gap="md" wrap="nowrap">
        {step === 'catalog'
          ? <SegmentedControl size="xs" value={mode} onChange={(v) => setMode(v as typeof mode)}
              data={[{ value: 'make', label: t('web.eq_make') }, { value: 'ready', label: t('web.eq_ready_glb') }, { value: 'outfit', label: t('web.eq_outfit') }]} />
          : step !== 'release' && pieceName}
        {step === 'workshop' && <SegmentedControl size="xs" value={editorStep} onChange={(v) => setTab(v as Tab)}
          data={TABS.map((k) => ({ value: k, label: t(`web.eq_tab_${k}`) }))} />}
        <Text size="xs" c="dimmed" truncate style={{ flex: 1 }}>{about}</Text>
        {step === 'workshop' && piece?.piece && <Button size="compact-sm" variant="subtle" color="gray" onClick={() => goStep('catalog')}>{t('web.eq_change_piece')}</Button>}
        {(step === 'workshop' || step === 'look') && shots.length > 0 && <Button size="compact-sm" variant={showShots ? 'light' : 'subtle'} color="gray"
          leftSection={<IconPhoto size={14} />} onClick={() => setShowShots(!showShots)}>{t('web.shots', shots.length)}</Button>}
      </Group>
      {(step === 'workshop' || step === 'look') && showShots && shots.length > 0 && (
        <div className="shots">{shots.map((s) => (
          <a key={s.path} href={fileUrl(s.path)} target="_blank" rel="noreferrer" title={s.caption}><Image src={fileUrl(s.path)} h={150} w="auto" fit="contain" /></a>))}
        </div>)}
      <div className={'eq-body' + (step === 'check' ? ' check' : '')}>
        <div className="eq-editor">
          {src ? <div className="frame-box">
            <iframe ref={frame} key={src} src={src} className="equip-frame" title={t('web.editor_title')} onLoad={() => toEditor({ type: 'sf3d-hello' })} />
            {loading && !cover && <LoadingVeil text={t('web.loading_model')} />}
          </div>
            : <div className="placeholder"><Text c="ember.3">{asCharacter(cur) ? t('web.need_rig', cur.name) : t('web.need_character')}</Text></div>}
        </div>
        {step === 'check' && rigged && <CheckPanel rigged={rigged} piece={piece} press={press} />}
        {src && cover && (
          <div className="eq-cover">
            {step === 'catalog' && (mode === 'ready' ? <WearPanel ids={wear} /> : mode === 'outfit' ? <OutfitPanel />
              : <CatalogPage catalog={catalog} made={made} current={piece} pick={pick} open={open} />)}
            {step === 'release' && <ReleasePage made={made} reload={loadMade} open={open} check={check} press={press} toCatalog={() => goStep('catalog')} />}
            {step === 'workshop' && <WorkshopEmpty toCatalog={() => goStep('catalog')} />}
          </div>)}
      </div>
      <div id={bridge[0]} hidden><textarea defaultValue="" /></div>
      <button id={bridge[1]} type="button" hidden onClick={send} />
    </div>
  );
}
