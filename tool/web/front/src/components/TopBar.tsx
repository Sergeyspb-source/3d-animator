import { ActionIcon, Badge, Group, Menu, Select, Text, Tooltip, UnstyledButton, useMantineColorScheme } from '@mantine/core';
import { spotlight } from '@mantine/spotlight';
import { IconLanguage, IconMoon, IconSearch, IconSun, IconSettings, IconRefresh } from '@tabler/icons-react';
import { live, useStore } from '../api';
import { useI18n } from '../i18n';
import { useObjects } from '../objects';
import { SECTIONS, type Route } from '../nav';

// the card's memory as heat: cold iron while there is room, ember when it fills, yellow heat when nearly full
const heatOf = (pct: number) => (pct > 85 ? '#f2c14e' : pct > 55 ? '#e0782e' : '#6f7c88');

export default function TopBar({ route, go, testBench }: { route: Route; go: (r: Route) => void; testBench: boolean }) {
  const { t, lang, langs, setLang } = useI18n();
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const gpu = useStore(live, (s) => s.gpu);
  const tasks = useStore(live, (s) => s.tasks);
  const connected = useStore(live, (s) => s.connected);
  const objs = useObjects();
  const running = Object.values(tasks).filter((x) => x.status === 'running');
  const queued = Object.values(tasks).filter((x) => x.status === 'queued');
  const pct = gpu.total ? (100 * (gpu.used || 0)) / gpu.total : 0;
  // a model can be listed both as a character and as a creature (export\character\front, nurgls_medium); Mantine's
  // Select throws on a value given twice and the whole page went black - each id once, under the first group it is in
  const seen = new Set<string>();
  const once = (list: typeof objs.characters) => list.filter((o) => !seen.has(o.id) && !!seen.add(o.id));
  // the current object only where a section works on one (Character, Equipment, Creatures), and only its kind there;
  // Models and Environment make new things: no object to choose
  const kind = SECTIONS.find((s) => s.id === route.section)?.object;
  const fits = (o: (typeof objs.characters)[number]) => (kind === 'creature' ? o.as_creature : o.as_character);
  const objData = [
    { group: t('web.characters'), items: once(objs.characters.filter(fits)).map((o) => ({ value: o.id, label: `${o.name}   ${o.tags}` })) },
    { group: t('web.creatures'), items: once(objs.creatures.filter(fits)).map((o) => ({ value: o.id, label: `${o.name}   ${o.tags}` })) },
  ].filter((g) => g.items.length);

  return (
    <Group h="100%" px="sm" gap="sm" wrap="nowrap" className="topbar">
      <Text className="brand">SF3D</Text>
      {testBench && <Badge color="yellow" variant="light">{t('web.test_bench')}</Badge>}
      <div style={{ flex: 1 }} />
      {kind && <Select size="xs" w={300} data={objData} value={objData.some((g) => g.items.some((x) => x.value === objs.current)) ? objs.current : null}
        onChange={(v) => objs.choose(v)} searchable
        placeholder={t('web.no_object')} aria-label={t('web.current_object')} nothingFoundMessage={t('web.nothing_found')}
        comboboxProps={{ width: 380 }} leftSection={<Text size="xs" c="dimmed" pl={4}>{t('web.object_short')}</Text>} leftSectionWidth={64} />}
      {kind && <Tooltip label={t('ui.refresh')}><ActionIcon variant="subtle" color="gray" onClick={objs.refresh} aria-label={t('ui.refresh')}><IconRefresh size={16} /></ActionIcon></Tooltip>}
      <Tooltip label={t('web.gpu_tip', gpu.used ?? '—', gpu.total ?? '—', gpu.util ?? '—') + (gpu.sf3d ? '. ' + t('web.sf3d_loaded') : '')}>
        <UnstyledButton className="gpu" onClick={() => go({ section: 'gpu', step: '' })}>
          <Group gap={6} wrap="nowrap">
            <Text size="xs" c="dimmed">{t('web.gpu')}</Text>
            <div className="heatmeter"><i style={{ width: `${pct}%`, background: heatOf(pct) }} /></div>
            <Text size="xs">{gpu.used != null ? `${(gpu.used / 1024).toFixed(1)} / ${((gpu.total || 0) / 1024).toFixed(0)}` : '—'}</Text>
          </Group>
        </UnstyledButton>
      </Tooltip>
      <UnstyledButton onClick={() => go({ section: 'tasks', step: '' })}>
        <Group gap={6} wrap="nowrap">
          <span className={'mark ' + (running.length ? 'running' : 'cancelled')} />
          <Text size="xs">{running.length ? t('web.tasks_running', running.length + queued.length) : t('web.tasks_none')}</Text>
        </Group>
      </UnstyledButton>
      {!connected && <Badge color="rust" variant="light">{t('web.offline')}</Badge>}
      <Tooltip label={t('web.search_tip')}><ActionIcon variant="subtle" color="gray" onClick={() => spotlight.open()} aria-label={t('web.search_tip')}><IconSearch size={18} /></ActionIcon></Tooltip>
      <Menu position="bottom-end">
        <Menu.Target><ActionIcon variant="subtle" color="gray" aria-label="language"><IconLanguage size={18} /></ActionIcon></Menu.Target>
        <Menu.Dropdown>
          {Object.entries(langs).map(([code, name]) => (
            <Menu.Item key={code} onClick={() => setLang(code)} fw={code === lang ? 700 : 400}>{name}</Menu.Item>))}
        </Menu.Dropdown>
      </Menu>
      <Tooltip label={t('web.theme')}>
        <ActionIcon variant="subtle" color="gray" onClick={() => setColorScheme(colorScheme === 'dark' ? 'light' : 'dark')} aria-label={t('web.theme')}>
          {colorScheme === 'dark' ? <IconSun size={18} /> : <IconMoon size={18} />}
        </ActionIcon>
      </Tooltip>
      <Tooltip label={t('ui.settings_2')}><ActionIcon variant="subtle" color="gray" onClick={() => go({ section: 'settings', step: '' })} aria-label={t('ui.settings_2')}><IconSettings size={18} /></ActionIcon></Tooltip>
    </Group>
  );
}
