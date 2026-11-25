// The dock at the bottom: every task (one at a time on the GPU, the rest wait) and the log of the one picked.
import { useEffect, useRef } from 'react';
import { ActionIcon, Badge, Group, Progress, ScrollArea, Text, Tooltip, UnstyledButton } from '@mantine/core';
import { IconChevronDown, IconChevronUp, IconPlayerStop } from '@tabler/icons-react';
import { live, loadLog, post, useStore, type TaskSummary } from '../api';
import { useT } from '../i18n';

const COLOR: Record<string, string> = { queued: 'gray', running: 'bronze', done: 'teal', error: 'red', cancelled: 'gray' };
export const since = (t0: number | null, t1?: number | null) => {
  if (!t0) return '';
  const s = Math.max(0, Math.round((t1 || Date.now() / 1000) - t0));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

export function TaskRow({ task, selected, onPick }: { task: TaskSummary; selected?: boolean; onPick?: () => void }) {
  const t = useT();
  return (
    <UnstyledButton className={'task-row' + (selected ? ' on' : '')} onClick={onPick}>
      <Group gap={8} wrap="nowrap">
        <Badge size="xs" color={COLOR[task.status]} variant={task.status === 'running' ? 'filled' : 'light'} w={84}>{t('web.st_' + task.status)}</Badge>
        <Text size="xs" fw={600} truncate style={{ flex: 1 }}>{task.title}</Text>
        <Text size="xs" c="dimmed" ff="monospace">{since(task.started || task.created, task.finished)}</Text>
        {(task.status === 'running' || task.status === 'queued') && (
          <Tooltip label={t('web.cancel')}><ActionIcon size="xs" variant="subtle" color="red" onClick={(e) => { e.stopPropagation(); post(`/api/tasks/${task.id}/cancel`); }}><IconPlayerStop size={12} /></ActionIcon></Tooltip>)}
      </Group>
      {task.status === 'running' && <Progress mt={3} size={3} value={(task.progress ?? 0) * 100} animated={task.progress == null} striped={task.progress == null} />}
      {task.status !== 'running' && task.error && <Text size="xs" c="red" truncate>{task.error}</Text>}
    </UnstyledButton>
  );
}

export function LogView({ id, grow }: { id: string | null; grow?: boolean }) {
  const t = useT();
  const lines = useStore(live, (s) => (id ? s.logs[id] : undefined));
  const vp = useRef<HTMLDivElement>(null);
  useEffect(() => { if (id && !live.get().logs[id]) loadLog(id).catch(() => {}); }, [id]);
  useEffect(() => { vp.current?.scrollTo({ top: vp.current.scrollHeight }); }, [lines]);
  return (
    <ScrollArea viewportRef={vp} className="log" style={grow ? { flex: 1 } : undefined}>
      <pre>{id ? (lines || []).join('\n') || t('web.log_empty') : t('web.log_pick')}</pre>
    </ScrollArea>
  );
}

export default function Dock({ open, toggle }: { open: boolean; toggle: () => void }) {
  const t = useT();
  const tasks = useStore(live, (s) => s.tasks);
  const selected = useStore(live, (s) => s.selected);
  const list = Object.values(tasks).sort((a, b) => Number(b.id) - Number(a.id));
  const run = list.find((x) => x.status === 'running');
  const waiting = list.filter((x) => x.status === 'queued').length;
  const pick = (id: string) => live.set((s) => ({ ...s, selected: id }));
  const shown = selected ?? list[0]?.id ?? null;
  return (
    <div className="dock">
      <Group className="dock-head" gap="sm" wrap="nowrap" onClick={toggle}>
        {open ? <IconChevronDown size={14} /> : <IconChevronUp size={14} />}
        <Text size="xs" fw={600}>{t('web.dock')}</Text>
        {run ? (
          <Group gap={6} wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
            <Text size="xs" truncate>▶ {run.title} · {run.last}</Text>
            {run.progress != null && <Progress w={90} size="sm" value={run.progress * 100} />}
          </Group>
        ) : <Text size="xs" c="dimmed" style={{ flex: 1 }}>{t('web.gpu_idle')}</Text>}
        {waiting > 0 && <Badge size="xs" variant="light">{t('web.waiting', waiting)}</Badge>}
        <Text size="xs" c="dimmed">` </Text>
      </Group>
      {open && (
        <div className="dock-body">
          <ScrollArea className="dock-tasks">
            {list.length ? list.map((x) => <TaskRow key={x.id} task={x} selected={x.id === shown} onPick={() => pick(x.id)} />)
              : <Text size="xs" c="dimmed" p="xs">{t('web.no_tasks')}</Text>}
          </ScrollArea>
          <LogView id={shown} />
        </div>
      )}
    </div>
  );
}
