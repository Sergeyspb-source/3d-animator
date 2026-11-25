// The left menu: the chains, each step with what the current object already has (a tick, a count) and a mark
// on the steps whose screen is still in the Gradio app.
import { useEffect, useState } from 'react';
import { ActionIcon, Badge, Divider, NavLink, ScrollArea, Stack, Switch, Text, Tooltip } from '@mantine/core';
import { useLocalStorage } from '@mantine/hooks';
import { IconCheck, IconChevronsLeft, IconChevronsRight, IconExternalLink, IconListDetails, IconCpu, IconSettings } from '@tabler/icons-react';
import { get, live, useStore, type ModelInfo, type SceneObject } from '../api';
import { useT } from '../i18n';
import { useCurrent } from '../objects';
import { SECTIONS, TOOLS, type Route } from '../nav';

const TOOL_ICON = { tasks: IconListDetails, gpu: IconCpu, settings: IconSettings } as const;

function mark(section: string, step: string, o: SceneObject | undefined, drafts: number): string | true | null {
  if (section === 'models' && step === 'check') return drafts ? String(drafts) : null;
  if (!o) return null;
  if (section === 'character' || section === 'creatures') {
    if (step === 'skeleton') return o.rigged ? true : null;
    if (step === 'face') return o.landmark ? true : o.speech ? String(o.speech) : null;
  }
  if (section === 'equipment' && step === 'release') return o.worn ? String(o.worn) : null;
  return null;
}

export default function NavMenu({ route, go, small, toggle, canToggle }: { route: Route; go: (r: Route) => void; small: boolean; toggle: () => void; canToggle: boolean }) {
  const t = useT();
  const cur = useCurrent();
  const finished = useStore(live, (s) => s.finished);
  const [drafts, setDrafts] = useState(0);
  const [onlyReady, setOnlyReady] = useLocalStorage({ key: 'sf3d.only_ready', defaultValue: false });
  const [open, setOpen] = useLocalStorage<Record<string, boolean>>({ key: 'sf3d.nav_open', defaultValue: { models: true, equipment: true } });
  useEffect(() => { get<ModelInfo[]>('/api/models/drafts').then((d) => setDrafts(d.length)).catch(() => {}); }, [finished, route]);

  if (small) {
    return (
      <Stack gap={4} p={8} align="center" h="100%">
        {SECTIONS.map((s) => (
          <Tooltip key={s.id} label={t(s.key)} position="right">
            <ActionIcon size="lg" variant={route.section === s.id ? 'filled' : 'subtle'} onClick={() => go({ section: s.id, step: '' })}><s.icon size={20} /></ActionIcon>
          </Tooltip>))}
        <div style={{ flex: 1 }} />
        {TOOLS.map((x) => { const I = TOOL_ICON[x.id]; return (
          <Tooltip key={x.id} label={t(x.key)} position="right"><ActionIcon size="lg" variant={route.section === x.id ? 'filled' : 'subtle'} onClick={() => go({ section: x.id, step: '' })}><I size={18} /></ActionIcon></Tooltip>); })}
        {canToggle && <ActionIcon variant="subtle" onClick={toggle} aria-label="expand"><IconChevronsRight size={16} /></ActionIcon>}
      </Stack>
    );
  }
  return (
    <Stack gap={0} h="100%">
      <ScrollArea style={{ flex: 1 }} p={6}>
        {SECTIONS.map((s) => {
          const needs = s.object && (!cur || cur.creature !== (s.object === 'creature'));
          return (
            <NavLink key={s.id} label={<Text fw={600} size="md">{t(s.key)}</Text>} leftSection={<s.icon size={18} stroke={1.6} />}
              opened={!!open[s.id] || route.section === s.id} onChange={(o) => setOpen({ ...open, [s.id]: o })} childrenOffset={22}
              description={needs ? t(s.object === 'creature' ? 'web.need_creature' : 'web.need_character') : undefined}>
              {s.steps.filter((x) => !onlyReady || x.ready).map((x, i) => {
                const m = mark(s.id, x.id, cur, drafts);
                return (
                  <NavLink key={x.id} active={route.section === s.id && route.step === x.id} onClick={() => go({ section: s.id, step: x.id })}
                    label={<Text size="sm" c={x.ready ? undefined : 'dimmed'}>{t(x.key)}</Text>}
                    leftSection={<span className="step-n">{i + 1}</span>}
                    rightSection={m === true ? <IconCheck size={14} color="var(--mantine-color-patina-4)" aria-label={t('web.done_mark')} />
                      : m ? <Badge size="sm" variant="light" color="gray">{m}</Badge>
                      : !x.ready ? <Tooltip label={t('web.in_gradio_tip')}><IconExternalLink size={13} color="var(--ash)" aria-label={t('web.in_gradio')} /></Tooltip> : null} />
                );
              })}
            </NavLink>
          );
        })}
      </ScrollArea>
      <Divider />
      <Stack gap={0} p={6}>
        {TOOLS.map((x) => { const I = TOOL_ICON[x.id]; return (
          <NavLink key={x.id} label={t(x.key)} leftSection={<I size={16} />} active={route.section === x.id} onClick={() => go({ section: x.id, step: '' })} />); })}
        <Switch size="xs" mt={8} mx={10} checked={onlyReady} onChange={(e) => setOnlyReady(e.currentTarget.checked)} label={t('web.only_ready')} />
        {canToggle && <NavLink label={t('web.collapse')} leftSection={<IconChevronsLeft size={16} />} onClick={toggle} />}
      </Stack>
    </Stack>
  );
}
