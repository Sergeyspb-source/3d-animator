// The equipment's steps around the procedural editor (EquipWorkspace keeps the editor; these are the shell's own parts):
// Catalog (what to make, the pieces made), the Workshop's empty state, Check's panel (the bake, the check in motion
// over the clips, the Godot fitting room) and Release (the character's pieces in a table).
import { useEffect, useState } from 'react';
import { Alert, Badge, Button, Group, Progress, ScrollArea, Stack, Table, Text, Title, UnstyledButton } from '@mantine/core';
import { IconFolder, IconRefresh } from '@tabler/icons-react';
import { fileUrl, get, live, post, useStore, type TaskSummary } from '../api';
import { useI18n } from '../i18n';
import PieceIcon from '../components/PieceIcon';
import LoadingVeil from '../components/LoadingVeil';
import { ZoomImage } from '../components/Zoom';

export interface PieceOn { piece: string | null; style: string | null; label: string; item: string }
export interface CatBlock { title: string; hair: boolean; items: { piece: string; style: string | null; label: string }[] }
export interface MadeRow {
  item: string; piece: string | null; label: string; style: string | null; layer: number | null; glb: string; when: number;
  editable: boolean; qa: { bad: boolean; stale: boolean; when: number } | null;
}
export interface Made { rows: MadeRow[]; folder: string }
interface QaRow { clip: string; through: number; holes: number | null; edge: number | null; frame: number | null; facing?: string; held?: boolean; bad: boolean }
interface QaReport { item: string; made: boolean; baked?: number | null; checked: boolean; when?: number; rows?: QaRow[]; bad?: boolean; stale?: boolean; shots?: { path: string; caption: string }[] }

const pct = (x: number | null | undefined) => (x == null ? '—' : `${(x * 100).toFixed(1).replace('.', ',')} %`);

export function QaBadge({ qa }: { qa: MadeRow['qa'] }) {
  const { t } = useI18n();
  if (!qa) return <Badge variant="light" color="gray">{t('web.eq_qa_never')}</Badge>;
  if (qa.stale) return <Badge variant="light" color="yellow">{t('web.eq_qa_old')}</Badge>;
  return qa.bad ? <Badge variant="light" color="ember">{t('web.eq_qa_warn')}</Badge> : <Badge variant="light" color="patina">{t('web.eq_qa_ok')}</Badge>;
}

// ------------------------------------------------------------------ Catalog: what to make, the pieces made
export function CatalogPage({ catalog, made, current, pick, open }:
  { catalog: CatBlock[]; made: Made | null; current: PieceOn | null; pick: (piece: string, style: string | null) => void; open: (item: string) => void }) {
  const { t } = useI18n();
  const mine = (made?.rows ?? []).filter((r) => r.editable);
  return (
    <ScrollArea h="100%">
      <Stack p="md" gap="lg" maw={1400}>
        {mine.length > 0 && (
          <Stack gap={6}>
            <Text fw={600}>{t('web.eq_made')}</Text>
            <Group gap={6}>
              {mine.map((r) => (
                <Button key={r.item} size="compact-sm" variant="default" leftSection={<PieceIcon piece={r.piece} style={r.style} size={20} />} onClick={() => open(r.item)}
                  title={r.label}>{r.item}</Button>))}
            </Group>
          </Stack>)}
        {catalog.filter((b) => !b.hair && b.items.length).map((b) => (
          <Stack key={b.title} gap={6}>
            <Text fw={600}>{b.title}</Text>
            <div className="piece-tiles">
              {b.items.map((it) => {
                const on = current?.piece === it.piece && (current?.style || null) === (it.style || null);
                return (
                  <UnstyledButton key={it.piece + (it.style || '')} className={'piece-tile' + (on ? ' on' : '')} onClick={() => pick(it.piece, it.style)}>
                    <PieceIcon piece={it.piece} style={it.style} size={46} />
                    <span>{it.label}</span>
                  </UnstyledButton>);
              })}
            </div>
          </Stack>))}
      </Stack>
      {!catalog.length && <LoadingVeil text={t('web.eq_catalog_loading')} />}
    </ScrollArea>
  );
}

// ------------------------------------------------------------------ Workshop with no piece on
export function WorkshopEmpty({ toCatalog }: { toCatalog: () => void }) {
  const { t } = useI18n();
  return (
    <div className="placeholder">
      <Stack maw={620} gap="md">
        <Title order={3}>{t('web.eq_pick_title')}</Title>
        <Text>{t('web.eq_pick_text')}</Text>
        <Stack gap={4}>
          {(['shape', 'fit', 'materials'] as const).map((k) => (
            <Text key={k} size="sm"><b>{t(`web.eq_tab_${k}`)}</b>: {t(`web.eq_tab_${k}_about`)}</Text>))}
        </Stack>
        <Group><Button onClick={toCatalog}>{t('web.eq_open_catalog')}</Button></Group>
      </Stack>
    </div>
  );
}

// ------------------------------------------------------------------ Check: the bake, the check in motion, Godot
const latest = (tasks: Record<string, TaskSummary>, rigged: string, item: string, action: string) =>
  Object.values(tasks).filter((x) => x.kind === 'equip' && x.meta?.rigged === rigged && x.meta?.action === action && (!item || x.meta?.item === item))
    .sort((a, b) => Number(b.id) - Number(a.id))[0];

export function CheckPanel({ rigged, piece, press }: { rigged: string; piece: PieceOn | null; press: (id: string) => void }) {
  const { t, lang } = useI18n();
  const tasks = useStore(live, (s) => s.tasks);
  const finished = useStore(live, (s) => s.finished);
  const item = piece?.item || '';
  const [rep, setRep] = useState<QaReport | null>(null);
  useEffect(() => {
    if (!item) { setRep(null); return; }
    get<QaReport>(`/api/equip/qa?rigged=${encodeURIComponent(rigged)}&item=${encodeURIComponent(item)}`).then(setRep).catch(() => setRep(null));
  }, [rigged, item, finished]);
  const bake = latest(tasks, rigged, item, 'generate'), qa = latest(tasks, rigged, item, 'qa');
  const running = (x?: TaskSummary) => !!x && (x.status === 'running' || x.status === 'queued');
  const when = (s?: number) => (s ? new Date(s * 1000).toLocaleString(lang) : '');
  if (!piece?.piece) return <div className="panel"><Stack p="sm"><Text c="dimmed">{t('web.eq_pick_title')}</Text></Stack></div>;
  const made = !!rep?.made;
  return (
    <ScrollArea className="panel">
      <Stack p="sm" gap="md">
        <div><div className="panel-title">{piece.label}</div><div className="field-note">{item}</div></div>

        <Stack gap={6}>
          <Text fw={600}>{t('web.eq_bake')}</Text>
          {running(bake) ? <><Text size="sm">{t('web.eq_bake_running')}</Text><Progress value={(bake!.progress ?? 0) * 100} animated striped /></>
            : bake?.status === 'error' ? <Text size="sm" c="rust.4">{t('web.eq_bake_failed', bake.error || '')}</Text>
            : made ? <Text size="sm" c="patina.4">{t('web.eq_bake_done', when(rep?.baked ?? undefined))}</Text>
            : <Text size="sm" c="dimmed">{t('web.eq_bake_none')}</Text>}
          <Group><Button size="xs" variant={made ? 'default' : 'filled'} disabled={running(bake)} onClick={() => press('go')}>{t(made ? 'web.eq_bake_again' : 'web.eq_bake_go')}</Button></Group>
        </Stack>

        <Stack gap={6}>
          <Text fw={600}>{t('web.eq_qa')}</Text>
          {!made && <Text size="sm" c="dimmed">{t('web.eq_need_bake')}</Text>}
          {made && running(qa) && <><Text size="sm">{t('web.eq_qa_running')}</Text><Progress value={100} animated striped /></>}
          {made && !running(qa) && !rep?.checked && <Text size="sm" c="dimmed">{t('web.eq_qa_none')}</Text>}
          {rep?.checked && rep.stale && <Alert color="yellow" p="xs">{t('web.eq_qa_stale')}</Alert>}
          {rep?.checked && !rep.stale && <Text size="sm" c={rep.bad ? 'ember.4' : 'patina.4'}>{t(rep.bad ? 'web.eq_qa_bad' : 'web.eq_qa_good')} {when(rep.when)}</Text>}
          <Group><Button size="xs" variant={made && (!rep?.checked || rep.stale) ? 'filled' : 'default'} disabled={!made || running(qa) || running(bake)}
            onClick={() => press('qa')}>{t('web.eq_qa_go')}</Button></Group>
          {rep?.checked && rep.rows && rep.rows.length > 0 && (
            <Table fz="xs" verticalSpacing={4} horizontalSpacing={6} className="qa-table">
              <Table.Thead><Table.Tr><Table.Th>{t('web.eq_qa_clip')}</Table.Th><Table.Th>{t('web.eq_qa_through')}</Table.Th>
                <Table.Th>{t('web.eq_qa_holes')}</Table.Th><Table.Th>{t('web.eq_qa_edge')}</Table.Th><Table.Th>{t('web.eq_qa_frame')}</Table.Th></Table.Tr></Table.Thead>
              <Table.Tbody>{rep.rows.map((r) => (
                <Table.Tr key={r.clip} className={r.bad ? 'bad' : undefined}>
                  <Table.Td>{r.clip}</Table.Td>
                  <Table.Td c={r.bad ? 'ember.4' : undefined}>{r.held ? String(r.through) : pct(r.through)}</Table.Td>
                  <Table.Td>{pct(r.holes)}</Table.Td><Table.Td>{r.held ? (r.facing || '—') : pct(r.edge)}</Table.Td><Table.Td>{r.frame ?? '—'}</Table.Td>
                </Table.Tr>))}
              </Table.Tbody>
            </Table>)}
          {rep?.shots && rep.shots.length > 0 && (
            <Stack gap={4}>
              <Text size="xs" c="dimmed">{t('web.eq_qa_shots')}</Text>
              <div className="qa-shots">{rep.shots.map((s) => (
                <ZoomImage key={s.path} src={s.path} url={fileUrl(s.path, rep.when)} group={(rep.shots || []).map((x) => x.path)} captions={(rep.shots || []).map((x) => x.caption)} title={s.caption} radius="sm" />))}</div>
            </Stack>)}
        </Stack>

        <Stack gap={6}>
          <Text fw={600}>{t('ed.fitting_room_in_godot')}</Text>
          <Text size="sm" c="dimmed">{t('web.eq_godot_note')}</Text>
          <Group><Button size="xs" variant="default" onClick={() => press('room')}>{t('web.eq_godot')}</Button></Group>
        </Stack>
      </Stack>
    </ScrollArea>
  );
}

// ------------------------------------------------------------------ Release: the character's pieces
export function ReleasePage({ made, reload, open, check, press, toCatalog }:
  { made: Made | null; reload: () => void; open: (item: string) => void; check: (item: string) => void; press: (id: string) => void; toCatalog: () => void }) {
  const { t, lang } = useI18n();
  const rows = made?.rows ?? [];
  return (
    <ScrollArea h="100%">
      <Stack p="md" gap="md" maw={1200}>
        <Group justify="space-between" wrap="wrap">
          <Title order={4}>{t('web.eq_rel_title', rows.length)}</Title>
          <Group gap="xs">
            <Button size="xs" variant="default" onClick={() => press('layersGo')} title={t('web.eq_layers_note')}>{t('ag.layers_rebuild')}</Button>
            <Button size="xs" variant="default" onClick={() => press('room')}>{t('ed.fitting_room_in_godot')}</Button>
            {made?.folder && <Button size="xs" variant="default" leftSection={<IconFolder size={14} />} onClick={() => post('/api/open', { path: made.folder })}>{t('web.eq_rel_folder')}</Button>}
            <Button size="xs" variant="subtle" color="gray" onClick={reload} aria-label={t('ui.refresh')}><IconRefresh size={14} /></Button>
          </Group>
        </Group>
        {!made && <Text c="dimmed">{t('web.eq_catalog_loading')}</Text>}
        {made && !rows.length && (
          <Stack gap="sm" align="flex-start"><Text>{t('web.eq_rel_empty')}</Text><Button onClick={toCatalog}>{t('web.eq_open_catalog')}</Button></Stack>)}
        {rows.length > 0 && (
          <Table highlightOnHover verticalSpacing={6}>
            <Table.Thead><Table.Tr>
              <Table.Th>{t('web.eq_rel_piece')}</Table.Th><Table.Th>{t('web.eq_rel_kind')}</Table.Th><Table.Th>{t('web.eq_rel_layer')}</Table.Th>
              <Table.Th>{t('web.eq_rel_qa')}</Table.Th><Table.Th>{t('web.eq_rel_when')}</Table.Th><Table.Th />
            </Table.Tr></Table.Thead>
            <Table.Tbody>{rows.map((r) => (
              <Table.Tr key={r.item}>
                <Table.Td><Group gap={8} wrap="nowrap"><PieceIcon piece={r.piece} style={r.style} size={30} /><Text size="sm" fw={500}>{r.item}</Text></Group></Table.Td>
                <Table.Td><Text size="sm">{r.label || '—'}</Text>{!r.editable && <Text size="xs" c="dimmed">{t('web.eq_rel_fitted')}</Text>}</Table.Td>
                <Table.Td>{r.layer ?? '—'}</Table.Td>
                <Table.Td><QaBadge qa={r.qa} /></Table.Td>
                <Table.Td><Text size="xs" c="dimmed">{r.when ? new Date(r.when * 1000).toLocaleString(lang) : ''}</Text></Table.Td>
                <Table.Td><Group gap={4} justify="flex-end" wrap="nowrap">
                  {r.editable && <Button size="compact-xs" variant="default" onClick={() => open(r.item)}>{t('web.eq_rel_open')}</Button>}
                  {r.editable && <Button size="compact-xs" variant="subtle" onClick={() => check(r.item)}>{t('web.eq_rel_check')}</Button>}
                </Group></Table.Td>
              </Table.Tr>))}
            </Table.Tbody>
          </Table>)}
      </Stack>
    </ScrollArea>
  );
}
