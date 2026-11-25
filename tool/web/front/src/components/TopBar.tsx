import { ActionIcon, Badge, Group, Menu, Progress, Select, Text, Tooltip, useMantineColorScheme } from '@mantine/core';
import { spotlight } from '@mantine/spotlight';
import { IconLanguage, IconMoon, IconSearch, IconSun, IconSettings, IconRefresh } from '@tabler/icons-react';
import { live, useStore } from '../api';
import { useI18n } from '../i18n';
import { useObjects } from '../objects';
import { SECTIONS, stepOf, type Route } from '../nav';

export default function TopBar({ route, go, testBench }: { route: Route; go: (r: Route) => void; testBench: boolean }) {
  const { t, lang, langs, setLang } = useI18n();
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const gpu = useStore(live, (s) => s.gpu);
  const tasks = useStore(live, (s) => s.tasks);
  const connected = useStore(live, (s) => s.connected);
  const objs = useObjects();
  const sec = SECTIONS.find((s) => s.id === route.section);
  const step = stepOf(route);
  const running = Object.values(tasks).filter((x) => x.status === 'running');
  const queued = Object.values(tasks).filter((x) => x.status === 'queued');
  const pct = gpu.total ? (100 * (gpu.used || 0)) / gpu.total : 0;
  const objData = [
    { group: t('web.characters'), items: objs.characters.map((o) => ({ value: o.id, label: `${o.name}   ${o.tags}` })) },
    { group: t('web.creatures'), items: objs.creatures.map((o) => ({ value: o.id, label: `${o.name}   ${o.tags}` })) },
  ].filter((g) => g.items.length);

  return (
    <Group h="100%" px="sm" gap="sm" wrap="nowrap" className="topbar">
      <Text className="brand" fw={700}>SF3D</Text>
      <Text size="sm" c="dimmed" className="crumbs" truncate>
        {sec ? `${t(sec.key)} › ${step ? t(step.key) : ''}` : ''}
      </Text>
      {testBench && <Badge color="yellow" variant="light">{t('web.test_bench')}</Badge>}
      <div style={{ flex: 1 }} />
      <Select size="xs" w={300} data={objData} value={objs.current} onChange={(v) => objs.choose(v)} searchable
        placeholder={t('web.no_object')} aria-label={t('web.current_object')} nothingFoundMessage={t('web.nothing_found')}
        comboboxProps={{ width: 380 }} leftSection={<Text size="xs" c="dimmed" pl={4}>{t('web.object_short')}</Text>} leftSectionWidth={64} />
      <Tooltip label={t('ui.refresh')}><ActionIcon variant="subtle" onClick={objs.refresh}><IconRefresh size={16} /></ActionIcon></Tooltip>
      <Tooltip label={t('web.gpu_tip', gpu.used ?? '—', gpu.total ?? '—', gpu.util ?? '—') + (gpu.sf3d ? ' · ' + t('web.sf3d_loaded') : '')}>
        <Group gap={6} wrap="nowrap" className="gpu" onClick={() => go({ section: 'gpu', step: '' })}>
          <Text size="xs" c="dimmed">{t('web.gpu')}</Text>
          <Progress w={70} value={pct} color={pct > 85 ? 'red' : pct > 60 ? 'yellow' : 'teal'} size="sm" />
          <Text size="xs" ff="monospace">{gpu.used != null ? `${(gpu.used / 1024).toFixed(1)}/${((gpu.total || 0) / 1024).toFixed(0)}` : '—'}</Text>
        </Group>
      </Tooltip>
      <Badge variant={running.length ? 'filled' : 'default'} style={{ cursor: 'pointer' }} onClick={() => go({ section: 'tasks', step: '' })}>
        {running.length ? t('web.tasks_running', running.length + queued.length) : t('web.tasks_none')}
      </Badge>
      {!connected && <Badge color="red" variant="light">{t('web.offline')}</Badge>}
      <Tooltip label={t('web.search_tip')}><ActionIcon variant="subtle" onClick={() => spotlight.open()}><IconSearch size={18} /></ActionIcon></Tooltip>
      <Menu position="bottom-end">
        <Menu.Target><ActionIcon variant="subtle" aria-label="language"><IconLanguage size={18} /></ActionIcon></Menu.Target>
        <Menu.Dropdown>
          {Object.entries(langs).map(([code, name]) => (
            <Menu.Item key={code} onClick={() => setLang(code)} fw={code === lang ? 700 : 400}>{name}</Menu.Item>))}
        </Menu.Dropdown>
      </Menu>
      <Tooltip label={t('web.theme')}>
        <ActionIcon variant="subtle" onClick={() => setColorScheme(colorScheme === 'dark' ? 'light' : 'dark')}>
          {colorScheme === 'dark' ? <IconSun size={18} /> : <IconMoon size={18} />}
        </ActionIcon>
      </Tooltip>
      <Tooltip label={t('ui.settings_2')}><ActionIcon variant="subtle" onClick={() => go({ section: 'settings', step: '' })}><IconSettings size={18} /></ActionIcon></Tooltip>
    </Group>
  );
}
