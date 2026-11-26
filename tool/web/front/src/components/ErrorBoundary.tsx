// A part of the page that fails to draw shows what went wrong and a way back instead of taking the whole page down
// with it (an error no boundary catches unmounts everything: the app window went black). The step's screen gets a
// full message, the top bar, the menu and the dock a one-line one; a new step or a new current object tries again.
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Alert, Button, Code, Group, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useT } from '../i18n';

interface Props { children: ReactNode; title: string; retry: string; note?: string; compact?: boolean }
interface State { error: Error | null }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[sf3d] a part of the page failed:', error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    const p = this.props;
    const again = () => this.setState({ error: null });
    if (p.compact) {
      return (
        <Group gap={6} p={6} wrap="nowrap" title={String(error.message || error)}>
          <IconAlertTriangle size={16} color="var(--mantine-color-rust-4)" style={{ flex: 'none' }} />
          <Text size="xs" c="rust.3" truncate>{p.title}</Text>
          <Button size="compact-xs" variant="subtle" onClick={again}>{p.retry}</Button>
        </Group>
      );
    }
    return (
      <div className="placeholder">
        <Alert color="rust" variant="light" icon={<IconAlertTriangle />} title={p.title} maw={680}>
          <Stack gap="sm">
            {p.note && <Text size="sm">{p.note}</Text>}
            <Code block style={{ whiteSpace: 'pre-wrap' }}>{String(error.message || error)}</Code>
            <Group><Button size="xs" variant="default" onClick={again}>{p.retry}</Button></Group>
          </Stack>
        </Alert>
      </div>
    );
  }
}

// the boundary with its texts, for a part of the window (compact) or a step's screen
export function Guard({ children, compact }: { children: ReactNode; compact?: boolean }) {
  const t = useT();
  return (
    <ErrorBoundary compact={compact} title={t(compact ? 'web.crash_part' : 'web.crash_title')} retry={t('web.crash_retry')}
      note={compact ? undefined : t('web.crash_note')}>
      {children}
    </ErrorBoundary>
  );
}
