// The shell: the current object and the GPU on top, the chains on the left, the step's work area in the middle,
// the log and the tasks at the bottom.
import { useEffect, useState } from 'react';
import { AppShell } from '@mantine/core';
import { useHotkeys, useLocalStorage, useMediaQuery } from '@mantine/hooks';
import { Spotlight, type SpotlightActionData } from '@mantine/spotlight';
import { IconSearch } from '@tabler/icons-react';
import type { AppState } from './api';
import { useT } from './i18n';
import { SECTIONS, TOOLS, hashOf, parseHash, stepOf, type Route } from './nav';
import TopBar from './components/TopBar';
import NavMenu from './components/NavMenu';
import Dock from './components/Dock';
import { ObjectsProvider } from './objects';
import ModelCreate from './screens/ModelCreate';
import ModelCheck from './screens/ModelCheck';
import ModelRelease from './screens/ModelRelease';
import Placeholder from './screens/Placeholder';
import { TasksScreen, GpuScreen, SettingsScreen } from './screens/Tools';

export default function App({ initial }: { initial: AppState }) {
  const t = useT();
  const [route, setRoute] = useState<Route>(() => parseHash(location.hash));
  const [dockOpen, setDockOpen] = useLocalStorage({ key: 'sf3d.dock', defaultValue: true });
  const [navSmall, setNavSmall] = useLocalStorage({ key: 'sf3d.nav_small', defaultValue: false });
  const narrow = useMediaQuery('(max-width: 1100px)');
  const small = navSmall || !!narrow;

  useEffect(() => {
    const on = () => setRoute(parseHash(location.hash));
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  const go = (r: Route) => { location.hash = hashOf(r); };

  // keys: Ctrl+K every command, ` the dock, Alt+1..7 the steps of this section
  const sec = SECTIONS.find((s) => s.id === route.section);
  useHotkeys([
    ['Backquote', () => setDockOpen((o) => !o)],
    ...((sec?.steps ?? []).slice(0, 9).map((s, i) => [`alt+${i + 1}`, () => go({ section: sec!.id, step: s.id })]) as [string, () => void][]),
  ]);

  const actions: SpotlightActionData[] = [
    ...SECTIONS.flatMap((s) => s.steps.map((x) => ({
      id: `${s.id}-${x.id}`, label: `${t(s.key)} → ${t(x.key)}`, description: t(x.about),
      onClick: () => go({ section: s.id, step: x.id }),
    }))),
    ...TOOLS.map((x) => ({ id: x.id, label: t(x.key), onClick: () => go({ section: x.id, step: '' }) })),
  ];

  const step = stepOf(route);
  let screen;
  if (route.section === 'tasks') screen = <TasksScreen />;
  else if (route.section === 'gpu') screen = <GpuScreen />;
  else if (route.section === 'settings') screen = <SettingsScreen state={initial} />;
  else if (route.section === 'models' && route.step === 'create') screen = <ModelCreate go={go} />;
  else if (route.section === 'environment' && route.step === 'vegetation') screen = <ModelCreate go={go} vegetation />;
  else if (route.section === 'models' && route.step === 'check') screen = <ModelCheck go={go} />;
  else if (route.section === 'models' && route.step === 'release') screen = <ModelRelease />;
  else screen = <Placeholder section={sec!} step={step!} gradio={initial.gradio} />;

  return (
    <ObjectsProvider>
      <AppShell header={{ height: 48 }} navbar={{ width: small ? 60 : 248, breakpoint: 0 }}
        footer={{ height: dockOpen ? 'clamp(170px, 24vh, 300px)' : 34 }} padding={0}>
        <AppShell.Header><TopBar route={route} go={go} testBench={initial.test_bench} /></AppShell.Header>
        <AppShell.Navbar><NavMenu route={route} go={go} small={small} toggle={() => setNavSmall(!navSmall)} canToggle={!narrow} /></AppShell.Navbar>
        <AppShell.Main className="main">{screen}</AppShell.Main>
        <AppShell.Footer><Dock open={dockOpen} toggle={() => setDockOpen(!dockOpen)} /></AppShell.Footer>
      </AppShell>
      <Spotlight actions={actions} shortcut={['mod + K']} nothingFound={t('web.nothing_found')} highlightQuery
        searchProps={{ leftSection: <IconSearch size={18} />, placeholder: t('web.search_ph') }} />
    </ObjectsProvider>
  );
}
