// The menu's bottom: tasks with their logs on the whole screen, the video memory, the settings.
import { useEffect, useRef, useState } from 'react';
import { Alert, Autocomplete, Button, Card, Code, Group, Modal, PasswordInput, Paper, Progress, ScrollArea, Select, Stack, Switch, Table, Text, TextInput, Title } from '@mantine/core';
import { useLocalStorage } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { IconFolder } from '@tabler/icons-react';
import { get, live, post, useStore, type AppState } from '../api';
import { plain, useT } from '../i18n';
import type { Route } from '../nav';
import { LogView, TaskRow } from '../components/Dock';

export function TasksScreen() {
  const t = useT();
  const tasks = useStore(live, (s) => s.tasks);
  const selected = useStore(live, (s) => s.selected);
  const list = Object.values(tasks).sort((a, b) => Number(b.id) - Number(a.id));
  const shown = selected ?? list[0]?.id ?? null;
  return (
    <div className="work tasks">
      <ScrollArea className="side">
        <div className="side-title">{t('web.tool_tasks')}</div>
        {list.map((x) => <TaskRow key={x.id} task={x} selected={x.id === shown} onPick={() => live.set((s) => ({ ...s, selected: x.id }))} />)}
        {!list.length && <Text size="sm" c="dimmed" p="sm">{t('web.no_tasks')}</Text>}
      </ScrollArea>
      <div className="stage log-stage"><LogView id={shown} grow /></div>
    </div>
  );
}

interface Need { key: string; mb: number }
const NEEDS: Need[] = [{ key: 'ui.sf3d_item_prop_character', mb: 6400 }, { key: 'ui.hunyuan3d_shape', mb: 6200 },
  { key: 'ui.hunyuan3d_texture_painting', mb: 7000 }, { key: 'ui.trellis_gpu_need', mb: 5500 }, { key: 'ui.rigging_unirig', mb: 4500 }];

interface Holder { pid: number; mb: number | null; name: string; label: string; kind: string }

export function GpuScreen() {
  const t = useT();
  const gpu = useStore(live, (s) => s.gpu);
  const free = gpu.free ?? 0;
  const [holders, setHolders] = useState<Holder[] | null>(null);
  const [ask, setAsk] = useState<Holder | null>(null);
  const [force, setForce] = useState(false);
  const load = () => { setHolders(null); get<Holder[]>('/api/gpu/holders').then(setHolders); };
  useEffect(load, []);
  const unload = async () => { const r = await post<{ ok: boolean; log: string }>('/api/gpu/unload'); notifications.show({ message: r.log, color: r.ok ? 'patina' : 'yellow' }); };
  const close = async () => {
    if (!ask) return;
    const r = await post<{ log: string }>('/api/gpu/close', { pid: ask.pid, force });
    setAsk(null); setForce(false); notifications.show({ message: r.log }); load();
  };
  return (
    <ScrollArea className="page">
      <Stack p="xl" maw={820} gap="md">
        <Title order={3}>{t('web.tool_gpu')}</Title>
        <Card withBorder>
          <Text size="sm">{plain(gpu.total ? t('ui.video_memory_of_gb_used_gb_free', (gpu.used || 0) / 1024, gpu.total / 1024, free / 1024) : t('ui.could_not_read_the_gpu_data_nvidia'))}</Text>
          <Progress mt="xs" value={gpu.total ? (100 * (gpu.used || 0)) / gpu.total : 0} />
          <Text size="xs" c="dimmed" mt={6}>{t('web.gpu_util', gpu.util ?? '—')}. {gpu.sf3d ? t('web.sf3d_loaded') : t('web.sf3d_not_loaded')}</Text>
        </Card>
        <Table>
          <Table.Tbody>{NEEDS.map((n) => (
            <Table.Tr key={n.key}><Table.Td>{t(n.key)}</Table.Td><Table.Td>{(n.mb / 1024).toFixed(1)} GB</Table.Td>
              <Table.Td c={free >= n.mb + 500 ? 'patina.4' : free >= n.mb ? 'yellow' : 'rust.4'}>{free >= n.mb + 500 ? t('ui.fits') : free >= n.mb ? t('ui.tight_better_free_some') : t('ui.will_not_fit_another_gb_short', (n.mb - free) / 1024)}</Table.Td></Table.Tr>))}
          </Table.Tbody>
        </Table>
        <Group><Button variant="default" onClick={unload} disabled={!gpu.sf3d}>{t('ui.unload_sf3d_from_video_memory')}</Button>
          <Button variant="subtle" color="gray" onClick={load}>{t('ui.refresh_show_the_video_memory_use')}</Button></Group>
        <Text size="sm" fw={600}>{plain(t('ui.what_uses_the_memory_according_to'))}</Text>
        {holders === null ? <Text size="sm" c="dimmed">…</Text> : (
          <Table verticalSpacing={4}>
            <Table.Tbody>{holders.map((h) => (
              <Table.Tr key={h.pid}>
                <Table.Td>{h.label}</Table.Td><Table.Td c="dimmed">PID {h.pid}</Table.Td><Table.Td>{h.mb != null ? `${h.mb} MB` : '—'}</Table.Td>
                <Table.Td w={110}>{(h.kind === 'other' || h.kind === 'ours') && <Button size="compact-xs" variant="subtle" color="rust" onClick={() => setAsk(h)}>{t('web.close_program')}</Button>}</Table.Td>
              </Table.Tr>))}
            </Table.Tbody>
          </Table>)}
        <Text size="xs" c="dimmed">{t('web.gpu_queue_note')}</Text>
      </Stack>
      <Modal opened={!!ask} onClose={() => setAsk(null)} title={t('web.close_program_title')} centered>
        <Stack>
          <Text size="sm">{ask ? t('web.close_program_text', ask.label, ask.pid) : ''}</Text>
          <Switch label={t('ui.force_unsaved_work_is_lost')} checked={force} onChange={(e) => setForce(e.currentTarget.checked)} />
          <Group justify="flex-end"><Button variant="default" onClick={() => setAsk(null)}>{t('web.cancel')}</Button><Button color="rust" onClick={close}>{t('ui.close_the_chosen_program')}</Button></Group>
        </Stack>
      </Modal>
    </ScrollArea>
  );
}

interface Settings { export_dir: string; input_dir: string; has_key: boolean; image_model: string; text_model: string; godot_exe: string; blender_exe: string; codex: string | null }
interface OrModel { id: string; name: string }

export function SettingsScreen({ state }: { state: AppState }) {
  const t = useT();
  const [st, setSt] = useState(state);
  const [cfg, setCfg] = useState<Settings | null>(null);
  const [key, setKey] = useState('');
  const [models, setModels] = useState<{ image: OrModel[]; text: OrModel[] } | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);
  const prov = useRef<HTMLDivElement>(null);
  const [lit, setLit] = useState(false);
  useEffect(() => {   // opened from a provider list: that section in view, lit for a moment
    let focus: string | null = null;
    try { focus = localStorage.getItem('sf3d.settings_focus'); localStorage.removeItem('sf3d.settings_focus'); } catch { /* */ }
    if (focus !== 'providers' || !cfg) return;
    prov.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setLit(true);
    const h = window.setTimeout(() => setLit(false), 2200);
    return () => window.clearTimeout(h);
  }, [cfg === null]); // eslint-disable-line react-hooks/exhaustive-deps
  const loadModels = async () => {
    setLoadingModels(true);
    try {
      const r = await get<{ image: OrModel[]; text: OrModel[] }>('/api/settings/openrouter_models');
      setModels(r);
      notifications.show({ color: 'patina', message: t('web.or_models_loaded', r.image.length, r.text.length) });
    } catch (e) {
      notifications.show({ color: 'rust', message: t('web.or_models_failed', String(e)) });
    } finally { setLoadingModels(false); }
  };
  const opts = (list: OrModel[] | undefined, cur: string) => [...new Set([cur, ...(list ?? []).map((m) => m.id)].filter(Boolean))];
  const load = () => { get<AppState>('/api/state').then(setSt); get<Settings>('/api/settings').then(setCfg); };
  useEffect(load, []);
  const save = async () => {
    const r = await post<{ ok: boolean; log: string }>('/api/settings', { export_dir: cfg?.export_dir, key, image_model: cfg?.image_model, text_model: cfg?.text_model });
    notifications.show({ color: r.ok ? 'patina' : 'yellow', message: r.log }); setKey(''); load();
  };
  const rows: [string, string | undefined][] = [[t('web.work_dir'), st.work_dir], [t('web.drafts_dir'), st.drafts_dir], [t('web.input_dir'), st.input_dir]];
  return (
    <ScrollArea className="page">
      <Stack p="xl" maw={820} gap="md">
        <Title order={3}>{t('ui.settings_2')}</Title>
        {st.test_bench && <Alert color="yellow">{t('web.test_bench_note')}</Alert>}
        {cfg && <>
          <Group align="flex-end" wrap="nowrap">
            <TextInput style={{ flex: 1 }} label={t('ui.export_folder_later_point_it_to_the')} value={cfg.export_dir} onChange={(e) => setCfg({ ...cfg, export_dir: e.currentTarget.value })} />
            <Button variant="default" onClick={() => post('/api/open', { path: st.export_dir })}><IconFolder size={16} /></Button>
          </Group>
          <div ref={prov} style={{ scrollMarginTop: 16 }}>
            <Title order={4} mt="md">{t('web.providers')}</Title>
            <div className="field-note">{t('web.providers_note')}</div>
          </div>
          <Paper withBorder p="md" radius="md" className={lit ? 'lit' : undefined}>
            <Stack gap={6}>
              <Group justify="space-between"><Text fw={600}>{t('web.prov_codex')}</Text>
                <Text size="xs" c={cfg.codex ? 'patina.4' : 'yellow.5'}>{cfg.codex ? t('web.codex_found') : t('web.prov_no_codex_short')}</Text></Group>
              {cfg.codex ? <Code style={{ wordBreak: 'break-all' }}>{cfg.codex}</Code> : <Text size="sm">{t('web.codex_missing')}</Text>}
            </Stack>
          </Paper>
          <Paper withBorder p="md" radius="md" className={lit ? 'lit' : undefined}>
            <Stack gap="sm">
              <Group justify="space-between"><Text fw={600}>OpenRouter</Text>
                <Text size="xs" c={cfg.has_key ? 'patina.4' : 'yellow.5'}>{cfg.has_key ? t('web.key_set') : t('web.key_unset')}</Text></Group>
              <div className="field-note">{plain(t('ui.openrouter_for_references_with_a_key'))}</div>
              <PasswordInput label={t('ui.openrouter_key')} placeholder={cfg.has_key ? t('web.key_set_keep') : t('web.key_unset')} value={key} onChange={(e) => setKey(e.currentTarget.value)} autoComplete="off" />
              <Group grow align="flex-start">
                <Autocomplete label={t('ui.model_for_pictures')} value={cfg.image_model} data={opts(models?.image, cfg.image_model)} limit={60}
                  onChange={(v) => setCfg({ ...cfg, image_model: v })} />
                <Autocomplete label={t('ui.model_for_the_style_description')} value={cfg.text_model} data={opts(models?.text, cfg.text_model)} limit={60}
                  onChange={(v) => setCfg({ ...cfg, text_model: v })} />
              </Group>
              <Group gap="xs"><Button size="xs" variant="default" loading={loadingModels} onClick={loadModels}>{t('web.or_models_load')}</Button>
                <Text size="xs" c="dimmed">{t('web.or_models_note')}</Text></Group>
            </Stack>
          </Paper>
          <Group><Button onClick={save} disabled={st.test_bench}>{t('web.settings_save')}</Button></Group>
        </>}
        <Table>
          <Table.Tbody>{rows.filter(([, v]) => v).map(([k, v]) => (
            <Table.Tr key={k}><Table.Td c="dimmed" w={200}>{k}</Table.Td><Table.Td ff="monospace" fz="sm" style={{ wordBreak: 'break-all' }}>{v}</Table.Td>
              <Table.Td w={60}><Button size="xs" variant="subtle" onClick={() => post('/api/open', { path: v })}><IconFolder size={14} /></Button></Table.Td></Table.Tr>))}
          </Table.Tbody>
        </Table>
      </Stack>
    </ScrollArea>
  );
}

interface BatchRow { 0: string; 1: string; 2: string; 3: string; 4: string }

export function BatchScreen({ go }: { go: (r: Route) => void }) {
  const t = useT();
  const [p, setP] = useLocalStorage({ key: 'sf3d.batch', defaultValue: { root: '', category: 'prop', overwrite: false, preview: true, materials: false, rig: false, naming: 'mixamo', tries: 3 } });
  const [rows, setRows] = useState<BatchRow[]>([]);
  const [info, setInfo] = useState('');
  const [st, setSt] = useState<AppState | null>(null);
  const running = useStore(live, (s) => Object.values(s.tasks).some((x) => x.meta?.engine === 'batch' && (x.status === 'running' || x.status === 'queued')));
  useEffect(() => { get<AppState>('/api/state').then((x) => { setSt(x); if (!p.root) setP({ ...p, root: x.input_dir || '' }); }); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const scan = async () => { const r = await get<{ rows: BatchRow[]; log: string }>(`/api/batch/scan?root=${encodeURIComponent(p.root)}&category=${p.category}`); setRows(r.rows); setInfo(r.log); };
  const cats = ['item', 'prop', 'building', 'character', 'vegetation'];
  const catKey: Record<string, string> = { item: 'ui.inventory_item', prop: 'ui.prop_environment', building: 'ui.building', character: 'ui.character', vegetation: 'ui.vegetation_trees_bushes_grass' };
  return (
    <div className="work two">
      <ScrollArea className="stage table-stage">
        <Table stickyHeader verticalSpacing={3} fz="xs">
          <Table.Thead><Table.Tr>{['ui.name', 'ui.category', 'ui.engine', 'ui.source', 'ui.status_2'].map((k) => <Table.Th key={k}>{t(k)}</Table.Th>)}</Table.Tr></Table.Thead>
          <Table.Tbody>{rows.map((r, i) => <Table.Tr key={i}>{[0, 1, 2, 3, 4].map((j) => <Table.Td key={j} style={{ overflowWrap: 'anywhere' }}>{String((r as any)[j] ?? '')}</Table.Td>)}</Table.Tr>)}</Table.Tbody>
        </Table>
        {!rows.length && <Text c="dimmed" p="md">{plain(t('ui.folder_scheme_picture_png_sf3d_front'))}</Text>}
      </ScrollArea>
      <ScrollArea className="panel"><Stack gap="sm" p="sm">
        <div className="panel-title">{t('ui.batch_processing_2')}</div>
        <TextInput label={t('ui.root_folder')} value={p.root} onChange={(e) => setP({ ...p, root: e.currentTarget.value })} />
        <Select label={t('ui.default_category')} value={p.category} allowDeselect={false} onChange={(v) => v && setP({ ...p, category: v })} data={cats.map((c) => ({ value: c, label: t(catKey[c]) }))} />
        <Switch label={t('ui.overwrite_finished_ones')} checked={p.overwrite} onChange={(e) => setP({ ...p, overwrite: e.currentTarget.checked })} />
        <Switch label={t('ui.previews_and_icons')} checked={p.preview} onChange={(e) => setP({ ...p, preview: e.currentTarget.checked })} />
        <Switch label={t('ui.recognise_materials')} checked={p.materials} onChange={(e) => setP({ ...p, materials: e.currentTarget.checked })} />
        <Switch label={t('ui.skeletons_for_characters_at_the_end')} checked={p.rig} onChange={(e) => setP({ ...p, rig: e.currentTarget.checked })} />
        <Group grow>
          <Button variant="default" onClick={scan}>{t('ui.scan_the_folder')}</Button>
          <Button disabled={running || !p.root} onClick={() => post('/api/batch/run', p)}>{t('ui.run_the_batch')}</Button>
        </Group>
        <div className="field-note">{info}</div>
        <div className="field-note">{t('web.batch_note')}</div>
        <Button variant="subtle" color="gray" onClick={() => go({ section: 'models', step: 'check' })}>{t('web.step_check')}</Button>
        {st?.test_bench && <div className="field-note">{t('web.test_bench')}</div>}
      </Stack></ScrollArea>
    </div>
  );
}
