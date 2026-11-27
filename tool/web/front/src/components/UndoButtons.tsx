// ↶ ↷ for a React editor (undo.ts): greyed when there is nothing to undo or redo, the keys in the tooltip
import { ActionIcon, Group, Tooltip } from '@mantine/core';
import { IconArrowBackUp, IconArrowForwardUp } from '@tabler/icons-react';
import { useT } from '../i18n';

export default function UndoButtons({ can, onStep }: { can: [boolean, boolean]; onStep: (back: boolean) => void }) {
  const t = useT();
  return (
    <Group gap={2} wrap="nowrap">
      <Tooltip label={t('ui.undo_tip')}>
        <ActionIcon size="sm" variant="default" disabled={!can[0]} onClick={() => onStep(true)} aria-label={t('ui.undo_tip')}><IconArrowBackUp size={15} /></ActionIcon>
      </Tooltip>
      <Tooltip label={t('ui.redo_tip')}>
        <ActionIcon size="sm" variant="default" disabled={!can[1]} onClick={() => onStep(false)} aria-label={t('ui.redo_tip')}><IconArrowForwardUp size={15} /></ActionIcon>
      </Tooltip>
    </Group>
  );
}
