// Character → Animations: watch the character's clips (own procedural ones, Mixamo's), with a weapon in hand and the
// clip check; make the 12 procedural clips in a chosen manner; carry Mixamo FBX motions onto the skeleton.
import { useEffect, useState } from 'react';
import { Button, Checkbox, Group, NumberInput, ScrollArea, SegmentedControl, Select, Stack, Table, Text, TextInput,
  useMantineColorScheme } from '@mantine/core';
import { useLocalStorage } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { get, live, onTaskFinished, post, useStore } from '../api';
import { useT } from '../i18n';
import { asCharacter, useCurrent } from '../objects';
import EditorFrame from '../components/EditorFrame';
import { ZoomImage } from '../components/Zoom';

type Mode = 'watch' | 'procedural' | 'mixamo';
interface Opts { clips: { id: string; label: string }[]; manners: { id: string; key: string }[]; deaths: { id: string; key: string }[]; weapons: string[]; fbx_dir: string }
interface ClipFile { path: string; when: number; clips: string[] }
type Row = [string, string, boolean, number, boolean, string];

export default function CharAnims() {
  const t = useT();
  const { colorScheme } = useMantineColorScheme();
  const cur = useCurrent();
  const id = asCharacter(cur) ? cur.id : undefined;
  const finished = useStore(live, (s) => s.finished);
  const running = useStore(live, (s) => Object.values(s.tasks).some((x) => x.kind === 'char' && x.meta?.char === id && (x.status === 'running' || x.status === 'queued')));
  const [mode, setMode] = useLocalStorage<Mode>({ key: 'sf3d.anim_mode', defaultValue: 'watch' });
  const [kind, setKind] = useLocalStorage({ key: 'sf3d.anim_kind', defaultValue: 'fbx' });
  const [weapon, setWeapon] = useState<string | null>(null);
  const [opt, setOpt] = useState<Opts | null>(null);
  const [st, setSt] = useState<{ anim: ClipFile | null; fbx: ClipFile | null } | null>(null);
  const [picked, setPicked] = useLocalStorage<string[] | null>({ key: 'sf3d.anim_clips', defaultValue: null });
  const [manner, setManner] = useLocalStorage({ key: 'sf3d.anim_manner', defaultValue: 'normal' });
  const [death, setDeath] = useLocalStorage({ key: 'sf3d.anim_death', defaultValue: 'back' });
  const [seed, setSeed] = useState('');
  const [shots, setShots] = useState<string[]>([]);
  const [check, setCheck] = useState<string>('');
  const [folder, setFolder] = useState('');
  const [rows, setRows] = useState<Row[]>([]);
  const [tableLog, setTableLog] = useState('');

  useEffect(() => { get<Opts>('/api/anim/options').then((o) => { setOpt(o); setFolder((f) => f || o.fbx_dir); setWeapon((w) => w ?? o.weapons[0]); }); }, []);
  useEffect(() => { if (id) get<typeof st>(`/api/anim/state?id=${encodeURIComponent(id)}`).then(setSt).catch(() => setSt(null)); }, [id, finished]);
  useEffect(() => { setShots([]); setCheck(''); }, [id]);
  useEffect(() => onTaskFinished((tk) => {
    if (tk.kind !== 'char' || tk.meta?.char !== id) return;
    if (tk.status === 'error') { notifications.show({ color: 'rust', title: tk.title, message: tk.error || '' }); return; }
    if (tk.status !== 'done') return;
    if (tk.meta?.what === 'anim') { setShots(tk.result?.shots || []); }
    if (tk.meta?.what === 'fbx') { setKind('fbx'); setMode('watch'); }
    if (tk.meta?.what === 'clipcheck') setCheck(tk.result?.md || '');
    notifications.show({ color: 'patina', message: tk.title });
  }), [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const readFolder = async () => {
    const r = await get<{ rows: Row[]; log: string }>(`/api/anim/fbx_table?folder=${encodeURIComponent(folder)}`);
    setRows(r.rows); setTableLog(r.log);
  };
  useEffect(() => { if (mode === 'mixamo' && opt && !rows.length) readFolder(); }, [mode, opt]); // eslint-disable-line react-hooks/exhaustive-deps
  const setCell = (i: number, j: number, v: unknown) => setRows(rows.map((r, k) => (k === i ? (r.map((c, m) => (m === j ? v : c)) as Row) : r)));

  if (!id) return <div className="placeholder"><Text c="ember.3">{t('web.need_character')}</Text></div>;
  if (!opt) return null;
  const has = (k: string) => !!(st && (st as any)[k]);
  const clips = picked ?? opt.clips.map((c) => c.id);
  const head = (
    <Group className="equip-head" gap="md" wrap="nowrap">
      <SegmentedControl size="xs" value={mode} onChange={(m) => setMode(m as Mode)} data={[
        { value: 'watch', label: t('web.anim_watch') }, { value: 'procedural', label: t('web.anim_proc') }, { value: 'mixamo', label: t('web.anim_mixamo') }]} />
      {mode === 'watch' && <>
        <SegmentedControl size="xs" value={kind} onChange={setKind} data={[
          { value: 'anim', label: `${t('web.anim_kind_anim')} (${st?.anim?.clips.length ?? 0})`, disabled: !has('anim') },
          { value: 'fbx', label: `${t('web.anim_kind_fbx')} (${st?.fbx?.clips.length ?? 0})`, disabled: !has('fbx') }]} />
        <Select size="xs" w={240} data={opt.weapons} value={weapon} onChange={setWeapon} allowDeselect={false} aria-label={t('ui.weapons_in_hand_only_for_viewing')} />
        <div style={{ flex: 1 }} />
        <Button size="compact-sm" variant="default" disabled={!has(kind) || running} onClick={() => post('/api/anim/check', { id, kind })}>{t('cc.button')}</Button>
      </>}
      {mode !== 'watch' && <Text size="xs" c="dimmed" truncate style={{ flex: 1 }}>{t(mode === 'procedural' ? 'ui.a_set_of_ready_clips_for_a_humanoid' : 'ui.animations_from_mixamo_fbx_without')}</Text>}
    </Group>
  );

  if (mode === 'watch') {
    const k = has(kind) ? kind : has('fbx') ? 'fbx' : has('anim') ? 'anim' : null;
    return (
      <div className="equip">
        {head}
        {check && <div className="checkbar"><pre>{check}</pre><Button size="compact-xs" variant="subtle" color="gray" onClick={() => setCheck('')}>×</Button></div>}
        {k ? <EditorFrame src={`/editor/clips?id=${encodeURIComponent(id)}&kind=${k}&weapon=${encodeURIComponent(weapon || '')}&theme=${colorScheme}&v=${(st as any)?.[k]?.when ?? 0}`} title={t('cr.anim_tab')} />
          : <div className="placeholder"><Text c="dimmed">{t('web.anim_none')}</Text></div>}
      </div>
    );
  }
  if (mode === 'procedural') {
    return (
      <div className="equip">
        {head}
        <div className="work two" style={{ flex: 1 }}>
          <ScrollArea className="stage sheets">
            {shots.length ? <Stack gap="xs" p="sm">{shots.map((s) => <ZoomImage key={s} src={s} group={shots} radius="sm" />)}</Stack>
              : <Text className="viewer-empty">{has('anim') ? t('web.anim_has', st!.anim!.clips.length) : t('web.anim_none')}</Text>}
          </ScrollArea>
          <ScrollArea className="panel">
            <Stack gap="sm" p="sm">
              <div className="panel-title">{t('web.anim_proc')}</div>
              <Text size="sm" fw={500}>{t('ui.which_clips_to_add')}</Text>
              <Checkbox.Group value={clips} onChange={setPicked}>
                <Stack gap={4}>{opt.clips.map((c) => <Checkbox key={c.id} size="xs" value={c.id} label={c.label} />)}</Stack>
              </Checkbox.Group>
              <Select size="sm" label={t('hanim.manner')} description={t('hanim.manner_info')} value={manner} allowDeselect={false} onChange={(v) => v && setManner(v)}
                data={opt.manners.map((m) => ({ value: m.id, label: t(m.key) }))} />
              <TextInput size="sm" label={t('hanim.seed')} description={t('hanim.seed_info')} value={seed} onChange={(e) => setSeed(e.currentTarget.value)} />
              <Select size="sm" label={t('hanim.death_kind')} value={death} allowDeselect={false} onChange={(v) => v && setDeath(v)}
                data={opt.deaths.map((m) => ({ value: m.id, label: t(m.key) }))} />
              <Button disabled={running || !clips.length || !cur?.rigged} onClick={() => post('/api/anim/procedural', { id, clips, manner, seed, death })}>{t('ui.add_the_animations')}</Button>
            </Stack>
          </ScrollArea>
        </div>
      </div>
    );
  }
  return (
    <div className="equip">
      {head}
      <div className="work two" style={{ flex: 1 }}>
        <ScrollArea className="stage table-stage">
          <Table stickyHeader highlightOnHover verticalSpacing={3} fz="xs">
            <Table.Thead><Table.Tr>{['fbx.file', 'fbx.clip_name', 'fbx.loop', 'fbx.speed', 'fbx.in_place', 'fbx.group'].map((k) => <Table.Th key={k}>{t(k)}</Table.Th>)}</Table.Tr></Table.Thead>
            <Table.Tbody>{rows.map((r, i) => (
              <Table.Tr key={r[0]}>
                <Table.Td style={{ maxWidth: 260, overflowWrap: 'anywhere' }}>{r[0]}</Table.Td>
                <Table.Td><TextInput size="xs" value={r[1]} onChange={(e) => setCell(i, 1, e.currentTarget.value)} /></Table.Td>
                <Table.Td><Checkbox size="xs" checked={r[2]} onChange={(e) => setCell(i, 2, e.currentTarget.checked)} /></Table.Td>
                <Table.Td><NumberInput size="xs" w={70} value={r[3]} step={0.05} min={0.1} onChange={(v) => setCell(i, 3, Number(v) || 1)} /></Table.Td>
                <Table.Td><Checkbox size="xs" checked={r[4]} onChange={(e) => setCell(i, 4, e.currentTarget.checked)} /></Table.Td>
                <Table.Td><TextInput size="xs" value={r[5]} onChange={(e) => setCell(i, 5, e.currentTarget.value)} /></Table.Td>
              </Table.Tr>))}
            </Table.Tbody>
          </Table>
          {!rows.length && <Text c="dimmed" p="md">{tableLog}</Text>}
        </ScrollArea>
        <ScrollArea className="panel">
          <Stack gap="sm" p="sm">
            <div className="panel-title">{t('web.anim_mixamo')}</div>
            <TextInput size="sm" label={t('ui.folder_with_fbx')} value={folder} onChange={(e) => setFolder(e.currentTarget.value)} />
            <Group grow>
              <Button variant="default" onClick={readFolder}>{t('ui.read_the_folder')}</Button>
              <Button variant="default" disabled={!rows.length} onClick={async () => { const r = await post<{ log: string }>('/api/anim/fbx_save', { folder, rows }); notifications.show({ message: r.log }); }}>{t('ui.save_the_settings')}</Button>
            </Group>
            <div className="field-note">{tableLog}</div>
            <Select size="sm" label={t('ui.weapons_in_hand_only_for_viewing')} data={opt.weapons} value={weapon} onChange={setWeapon} allowDeselect={false} />
            <Button disabled={running || !rows.length || !cur?.rigged} onClick={() => post('/api/anim/fbx', { id, folder, rows, weapon })}>{t('ui.retarget_onto_the_model')}</Button>
          </Stack>
        </ScrollArea>
      </div>
    </div>
  );
}
