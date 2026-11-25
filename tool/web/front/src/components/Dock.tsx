// The dock at the bottom: every task (one at a time on the GPU, the rest wait) and the log of the one picked.
import { useEffect, useRef } from 'react';
import { ActionIcon, Badge, Group, Progress, ScrollArea, Text, Tooltip, UnstyledButton } from '@mantine/core';
import { IconChevronDown, IconChevronUp, IconPlayerStop } from '@tabler/icons-react';
import { live, loadLog, post, useStore, type TaskSummary } from '../api';
import { useT } from '../i18n';

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
        <Tooltip label={t('web.st_' + task.status)}><span className={'mark ' + task.status} aria-label={t('web.st_' + task.status)} /></Tooltip>
        <Text size="sm" fw={600} truncate style={{ flex: 1 }}>{task.title}</Text>
        <Text size="xs" c="dimmed">{task.status === 'running' ? since(task.started, null) : t('web.st_' + task.status)}</Text>
        {(task.status === 'running' || task.status === 'queued') && (
          <Tooltip label={t('web.cancel')}><ActionIcon size="xs" variant="subtle" color="red" onClick={(e) => { e.stopPropagation(); post(`/api/tasks/${task.id}/cancel`); }}><IconPlayerStop size={12} /></ActionIcon></Tooltip>)}
      </Group>
      {task.status === 'running' && <Text size="xs" c="dimmed" truncate>{task.last}</Text>}
      {task.status === 'running' && task.progress != null && <Progress mt={3} size={3} value={task.progress * 100} />}
      {task.status !== 'running' && task.error && <Text size="xs" c="rust.4" truncate>{task.error}</Text>}
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
            <span className="mark running" />
            <Text size="xs" fw={600}>{run.title}</Text>
            <Text size="xs" c="dimmed" truncate>{run.last}</Text>
            {run.progress != null && <Progress w={90} size="sm" value={run.progress * 100} />}
          </Group>
        ) : <Text size="xs" c="dimmed" style={{ flex: 1 }}>{t('web.gpu_idle')}</Text>}
        {waiting > 0 && <Badge size="xs" variant="light">{t('web.waiting', waiting)}</Badge>}
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
