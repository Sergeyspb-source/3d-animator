import { createRoot } from 'react-dom/client';
import { MantineProvider, createTheme, type MantineColorsTuple } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import '@fontsource/golos-text/400.css';
import '@fontsource/golos-text/500.css';
import '@fontsource/golos-text/600.css';
import '@fontsource/golos-text/700.css';
import '@fontsource/jetbrains-mono/400.css';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/dropzone/styles.css';
import '@mantine/spotlight/styles.css';
import './styles.css';
import App from './App';
import { Guard } from './components/ErrorBoundary';
import { I18nProvider } from './i18n';
import { connect, get, type AppState } from './api';

// The asset forge: blue-steel iron for the panels, a darker quench for the rails, ember only where the GPU works
// (and the one main action of a step), patina for what is done, rust for what failed.
const iron: MantineColorsTuple = ['#dde1e5', '#b9c0c7', '#8e98a3', '#6b7580', '#454d56', '#333a42', '#2a3037', '#1d2126', '#171a1e', '#121417'];
const ember: MantineColorsTuple = ['#fff3ea', '#ffe2cc', '#fbc39a', '#f5a266', '#ef8740', '#e0782e', '#c9651f', '#a85216', '#86410f', '#653008'];
const patina: MantineColorsTuple = ['#e9f6f1', '#cdeae0', '#a3d7c4', '#78c2a7', '#5fae94', '#4d9a80', '#3f8069', '#326653', '#264d3f', '#1a352b'];
const rust: MantineColorsTuple = ['#fdecea', '#f8d0ca', '#efa79b', '#e47c6b', '#d65e4a', '#c4553f', '#a94533', '#883728', '#672a1e', '#481d15'];

const theme = createTheme({
  primaryColor: 'ember',
  primaryShade: { light: 6, dark: 5 },
  colors: { dark: iron, ember, patina, rust },
  fontFamily: '"Golos Text", "Segoe UI", system-ui, sans-serif',
  fontFamilyMonospace: '"JetBrains Mono", Consolas, monospace',
  headings: { fontFamily: '"Golos Text", "Segoe UI", system-ui, sans-serif', fontWeight: '600',
    sizes: { h3: { fontSize: '20px', lineHeight: '1.3' }, h4: { fontSize: '17px', lineHeight: '1.3' } } },
  fontSizes: { xs: '12px', sm: '13px', md: '14px', lg: '16px', xl: '18px' },
  radius: { xs: '2px', sm: '4px', md: '6px', lg: '8px', xl: '12px' },
  defaultRadius: 'sm',
  components: {
    Tooltip: { defaultProps: { openDelay: 400, withArrow: true } },
    Badge: { defaultProps: { radius: 'sm' }, styles: { root: { textTransform: 'none', fontWeight: 500, letterSpacing: 0 } } },
    Button: { styles: { root: { fontWeight: 600 } } },
    Accordion: { styles: { label: { paddingBlock: 8 } } },
  },
});

get<AppState>('/api/state').then((st) => {
  document.documentElement.lang = st.lang;
  connect();
  createRoot(document.getElementById('root')!).render(
    <MantineProvider theme={theme} defaultColorScheme="dark">
      <Notifications position="bottom-right" limit={4} />
      <I18nProvider initial={st.lang} langs={st.langs}>
        <Guard><App initial={st} /></Guard>
      </I18nProvider>
    </MantineProvider>,
  );
});
