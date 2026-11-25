// A step whose screen is still in the Gradio app: what it will hold here and where it is there now.
import { Anchor, Badge, Button, Card, Group, Stack, Text, Title } from '@mantine/core';
import { IconExternalLink } from '@tabler/icons-react';
import { useT } from '../i18n';
import { useCurrent } from '../objects';
import type { Section, Step } from '../nav';

export default function Placeholder({ section, step, gradio }: { section: Section; step: Step; gradio: string }) {
  const t = useT();
  const cur = useCurrent();
  const wrongKind = section.object && cur && cur.creature !== (section.object === 'creature');
  return (
    <div className="placeholder">
      <Card withBorder radius="md" p="xl" maw={720}>
        <Stack gap="md">
          <Group gap="xs"><Badge variant="outline" color="gray">{t('web.in_gradio')}</Badge><Text size="sm" c="dimmed">{t(section.key)}</Text></Group>
          <Title order={3}>{t(step.key)}</Title>
          <Text>{t(step.about)}</Text>
          {section.object && (
            <Text size="sm" c={wrongKind || !cur ? 'yellow' : 'dimmed'}>
              {cur ? t('web.works_on', cur.name) : t(section.object === 'creature' ? 'web.need_creature' : 'web.need_character')}
            </Text>)}
          {step.gradio && (
            <Text size="sm" c="dimmed">{t('web.gradio_path')} <b>{step.gradio.map((k) => t(k)).join(' → ')}</b></Text>)}
          <Group>
            <Button component="a" href={gradio} target="_blank" rel="noreferrer" rightSection={<IconExternalLink size={16} />} variant="default">
              {t('web.open_gradio')}
            </Button>
            <Anchor size="sm" href="https://claude.ai/artifact/54ovpraP22KbZoWQPq3Cpy" target="_blank" rel="noreferrer">{t('web.plan_link')}</Anchor>
          </Group>
        </Stack>
      </Card>
    </div>
  );
}
