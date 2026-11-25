import { createRoot } from 'react-dom/client';
import { MantineProvider, createTheme, type MantineColorsTuple } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/dropzone/styles.css';
import '@mantine/spotlight/styles.css';
import './styles.css';
import App from './App';
import { I18nProvider } from './i18n';
import { connect, get, type AppState } from './api';

// a bronze accent (the forge the armour comes from), cool graphite neutrals
const bronze: MantineColorsTuple = ['#fbf3ea', '#f1e2cf', '#e4c39d', '#d7a268', '#cc8740', '#c67728', '#c36f1b', '#ac5e10', '#9a530b', '#864500'];
const theme = createTheme({
  primaryColor: 'bronze',
  colors: { bronze },
  fontFamily: '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif',
  fontFamilyMonospace: '"Cascadia Mono", Consolas, monospace',
  headings: { fontFamily: '"Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif', fontWeight: '600' },
  defaultRadius: 'sm',
  components: { Tooltip: { defaultProps: { openDelay: 400, withArrow: true } } },
});

get<AppState>('/api/state').then((st) => {
  document.documentElement.lang = st.lang;
  connect();
  createRoot(document.getElementById('root')!).render(
    <MantineProvider theme={theme} defaultColorScheme="dark">
      <Notifications position="bottom-right" limit={4} />
      <I18nProvider initial={st.lang} langs={st.langs}>
        <App initial={st} />
      </I18nProvider>
    </MantineProvider>,
  );
});
