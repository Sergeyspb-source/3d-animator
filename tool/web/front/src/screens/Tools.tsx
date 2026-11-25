// The menu's bottom: tasks with their logs on the whole screen, the video memory, the settings.
import { useEffect, useState } from 'react';
import { Alert, Button, Card, Group, Progress, ScrollArea, Stack, Table, Text, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconFolder } from '@tabler/icons-react';
import { get, live, post, useStore, type AppState } from '../api';
import { useT } from '../i18n';
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
        <Text className="side-title" size="xs" fw={600} c="dimmed" tt="uppercase">{t('web.tool_tasks')}</Text>
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

export function GpuScreen() {
  const t = useT();
  const gpu = useStore(live, (s) => s.gpu);
  const free = gpu.free ?? 0;
  const unload = async () => { const r = await post<{ ok: boolean; log: string }>('/api/gpu/unload'); notifications.show({ message: r.log, color: r.ok ? 'teal' : 'yellow' }); };
  return (
    <ScrollArea className="page">
      <Stack p="xl" maw={760} gap="md">
        <Title order={3}>{t('web.tool_gpu')}</Title>
        <Card withBorder>
          <Text size="sm">{gpu.total ? t('ui.video_memory_of_gb_used_gb_free', (gpu.used || 0) / 1024, gpu.total / 1024, free / 1024) : t('ui.could_not_read_the_gpu_data_nvidia')}</Text>
          <Progress mt="xs" value={gpu.total ? (100 * (gpu.used || 0)) / gpu.total : 0} />
          <Text size="xs" c="dimmed" mt={6}>{t('web.gpu_util', gpu.util ?? '—')} · {gpu.sf3d ? t('web.sf3d_loaded') : t('web.sf3d_not_loaded')}</Text>
        </Card>
        <Table>
          <Table.Tbody>{NEEDS.map((n) => (
            <Table.Tr key={n.key}><Table.Td>{t(n.key)}</Table.Td><Table.Td ff="monospace">{(n.mb / 1024).toFixed(1)} GB</Table.Td>
              <Table.Td c={free >= n.mb + 500 ? 'teal' : free >= n.mb ? 'yellow' : 'red'}>{free >= n.mb + 500 ? t('ui.fits') : free >= n.mb ? t('ui.tight_better_free_some') : t('ui.will_not_fit_another_gb_short', (n.mb - free) / 1024)}</Table.Td></Table.Tr>))}
          </Table.Tbody>
        </Table>
        <Group><Button variant="default" onClick={unload} disabled={!gpu.sf3d}>{t('ui.unload_sf3d_from_video_memory')}</Button></Group>
        <Text size="xs" c="dimmed">{t('web.gpu_queue_note')}</Text>
      </Stack>
    </ScrollArea>
  );
}

export function SettingsScreen({ state }: { state: AppState }) {
  const t = useT();
  const [st, setSt] = useState(state);
  useEffect(() => { get<AppState>('/api/state').then(setSt); }, []);
  const rows: [string, string | undefined][] = [[t('web.export_dir'), st.export_dir], [t('web.work_dir'), st.work_dir], [t('web.drafts_dir'), st.drafts_dir], [t('web.input_dir'), st.input_dir]];
  return (
    <ScrollArea className="page">
      <Stack p="xl" maw={820} gap="md">
        <Title order={3}>{t('ui.settings_2')}</Title>
        {st.test_bench && <Alert color="yellow">{t('web.test_bench_note')}</Alert>}
        <Table>
          <Table.Tbody>{rows.filter(([, v]) => v).map(([k, v]) => (
            <Table.Tr key={k}><Table.Td c="dimmed" w={200}>{k}</Table.Td><Table.Td ff="monospace" fz="sm" style={{ wordBreak: 'break-all' }}>{v}</Table.Td>
              <Table.Td w={60}><Button size="xs" variant="subtle" onClick={() => post('/api/open', { path: v })}><IconFolder size={14} /></Button></Table.Td></Table.Tr>))}
            <Table.Tr><Table.Td c="dimmed">OpenRouter</Table.Td><Table.Td>{st.has_openrouter_key ? t('web.key_set') : t('web.key_unset')}</Table.Td><Table.Td /></Table.Tr>
          </Table.Tbody>
        </Table>
        <Text size="sm" c="dimmed">{t('web.settings_note')}</Text>
        <Button component="a" href={st.gradio} target="_blank" rel="noreferrer" variant="default" w="fit-content">{t('web.open_gradio')}</Button>
      </Stack>
    </ScrollArea>
  );
}
