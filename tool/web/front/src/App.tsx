// The shell: the current object and the GPU on top, the chains on the left, the step's work area in the middle,
// the log and the tasks at the bottom.
import { useEffect, useState } from 'react';
import { AppShell } from '@mantine/core';
import { useHotkeys, useLocalStorage, useMediaQuery } from '@mantine/hooks';
import { Spotlight, type SpotlightActionData } from '@mantine/spotlight';
import { IconSearch } from '@tabler/icons-react';
import { live, useStore, type AppState } from './api';
import { useT } from './i18n';
import { SECTIONS, TOOLS, hashOf, parseHash, stepOf, type Route } from './nav';
import TopBar from './components/TopBar';
import NavMenu from './components/NavMenu';
import Dock from './components/Dock';
import { ObjectsProvider, useObjects } from './objects';
import { Guard } from './components/ErrorBoundary';
import ModelCreate from './screens/ModelCreate';
import ModelCheck from './screens/ModelCheck';
import ModelRelease from './screens/ModelRelease';
import EquipWorkspace from './screens/EquipWorkspace';
import CharOverview from './screens/CharOverview';
import CharSkeleton from './screens/CharSkeleton';
import { CharWeights, CharGame } from './screens/CharMore';
import CharFace from './screens/CharFace';
import CharAnims from './screens/CharAnims';
import { CrOverviewScreen, CrSkeleton, CrAnims, CrPaint, CrGame } from './screens/Creatures';
import { Surfaces, Effects, Dungeons, Destructibles, Reference, ModelMaterials } from './screens/EnvScreens';
import { TasksScreen, GpuScreen, SettingsScreen, BatchScreen } from './screens/Tools';

// the step's screen in its own error boundary: another step or another current object draws it again
function Screen({ route, children }: { route: string; children: React.ReactNode }) {
  const { current } = useObjects();
  return <Guard key={`${route}|${current}`}>{children}</Guard>;
}

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
  const hot = useStore(live, (s) => Object.values(s.tasks).find((x) => x.status === 'running'));
  let screen;
  if (route.section === 'tasks') screen = <TasksScreen />;
  else if (route.section === 'gpu') screen = <GpuScreen />;
  else if (route.section === 'settings') screen = <SettingsScreen state={initial} />;
  else if (route.section === 'models' && route.step === 'create') screen = <ModelCreate go={go} />;
  else if (route.section === 'environment' && route.step === 'vegetation') screen = <ModelCreate go={go} vegetation />;
  else if (route.section === 'models' && route.step === 'check') screen = <ModelCheck go={go} />;
  else if (route.section === 'models' && route.step === 'ref') screen = <Reference go={go} />;
  else if (route.section === 'models' && route.step === 'batch') screen = <BatchScreen go={go} />;
  else if (route.section === 'models' && route.step === 'materials') screen = <ModelMaterials />;
  else if (route.section === 'environment' && route.step === 'surfaces') screen = <Surfaces />;
  else if (route.section === 'environment' && route.step === 'fx') screen = <Effects />;
  else if (route.section === 'environment' && route.step === 'dungeons') screen = <Dungeons />;
  else if (route.section === 'environment' && route.step === 'destructibles') screen = <Destructibles />;
  else if (route.section === 'models' && route.step === 'release') screen = <ModelRelease />;
  else if (route.section === 'character' && route.step === 'overview') screen = <CharOverview go={go} />;
  else if (route.section === 'character' && route.step === 'skeleton') screen = <CharSkeleton bridges={initial.bridges} />;
  else if (route.section === 'character' && route.step === 'face') screen = <CharFace go={go} bridges={initial.bridges} />;
  else if (route.section === 'character' && route.step === 'anim') screen = <CharAnims />;
  else if (route.section === 'creatures' && route.step === 'overview') screen = <CrOverviewScreen go={go} />;
  else if (route.section === 'creatures' && (route.step === 'skeleton' || route.step === 'eyes')) screen = <CrSkeleton bridge={initial.bridges.creature} eyes={route.step === 'eyes'} />;
  else if (route.section === 'creatures' && route.step === 'anim') screen = <CrAnims />;
  else if (route.section === 'creatures' && route.step === 'paint') screen = <CrPaint bridge={initial.bridges.paint} />;
  else if (route.section === 'creatures' && route.step === 'weights') screen = <CharWeights creature />;
  else if (route.section === 'creatures' && route.step === 'game') screen = <CrGame />;
  else if (route.section === 'character' && route.step === 'weights') screen = <CharWeights />;
  else if (route.section === 'character' && route.step === 'game') screen = <CharGame go={go} />;
  else if (route.section === 'equipment' || (route.section === 'character' && route.step === 'look'))   // (one editor: kept between the steps)
    screen = <EquipWorkspace step={route.section === 'character' ? 'look' : route.step} info={step} bridge={initial.bridges.equip} wear={initial.bridges.wear} go={go} />;
  else screen = <ModelCreate go={go} />;   // (parseHash leaves no other route)

  return (
    <ObjectsProvider>
      <AppShell header={{ height: 44 }} navbar={{ width: small ? 60 : 248, breakpoint: 0 }}
        footer={{ height: dockOpen ? 'clamp(160px, 22vh, 300px)' : 32 }} padding={0}>
        <AppShell.Header><Guard compact><TopBar route={route} go={go} testBench={initial.test_bench} /></Guard></AppShell.Header>
        <AppShell.Navbar className="navrail"><Guard compact><NavMenu route={route} go={go} small={small} toggle={() => setNavSmall(!navSmall)} canToggle={!narrow} /></Guard></AppShell.Navbar>
        <AppShell.Main className="main">
          {hot && <div className={'heat' + (hot.progress == null || hot.progress < 0.05 ? ' unknown' : '')} style={{ ['--p' as string]: hot.progress ?? 1 }} title={hot.title}><i /></div>}
          {/* (the equipment's steps and Looks share one editor, kept loaded between them: one boundary for all of them) */}
          <Screen route={route.section === 'equipment' || (route.section === 'character' && route.step === 'look') ? 'equip' : hashOf(route)}>{screen}</Screen>
        </AppShell.Main>
        <AppShell.Footer><Guard compact><Dock open={dockOpen} toggle={() => setDockOpen(!dockOpen)} /></Guard></AppShell.Footer>
      </AppShell>
      <Spotlight actions={actions} shortcut={['mod + K']} nothingFound={t('web.nothing_found')} highlightQuery
        searchProps={{ leftSection: <IconSearch size={18} />, placeholder: t('web.search_ph') }} />
    </ObjectsProvider>
  );
}
