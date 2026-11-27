// Character → Overview: what the current character has (skeleton, face, looks, clips, pieces, the fitting room),
// each with the step that makes it; the character in 3D; add another from a GLB, open its folder, delete it.
import { useEffect, useState } from 'react';
import { Button, FileButton, Group, ScrollArea, Stack, Text, UnstyledButton } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconFolder, IconPlus, IconTrash } from '@tabler/icons-react';
import { fileUrl, get, live, post, upload, useStore } from '../api';
import { useT } from '../i18n';
import { asCharacter, PickList, useCurrent, useObjects } from '../objects';
import type { Route } from '../nav';
import Viewer3D from '../components/Viewer3D';
import { askRemove, ObjectsChecklist } from '../components/RemoveModels';

export interface Overview {
  id: string; name: string; dir: string; source: string | null; rigged: string | null; parts: string | null;
  rig: { kind: 'landmark' | 'auto'; file: string; when: string; bones: number; mouth: string | null; retopo: boolean; eyes: boolean; face_edits: boolean } | null;
  speech: number; worn: number; clips: Record<string, { file: string; when: string; count: number | null }>; hair: string[];
  files: { name: string; when: string; kb: number }[];
}

export function useOverview(id: string | null | undefined) {
  const finished = useStore(live, (s) => s.finished);
  const [o, setO] = useState<Overview | null>(null);
  useEffect(() => { if (!id) { setO(null); return; } get<Overview>(`/api/char/overview?id=${encodeURIComponent(id)}`).then(setO).catch(() => setO(null)); }, [id, finished]);
  return o;
}

function Row({ title, state, note, ok, onOpen }: { title: string; state: string; note?: string; ok?: boolean; onOpen: () => void }) {
  const t = useT();
  return (
    <UnstyledButton className="ov-row" onClick={onOpen}>
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <div style={{ minWidth: 0 }}>
          <Text size="sm" fw={600}>{title}</Text>
          <Text size="sm" c={ok ? 'patina.4' : 'dimmed'}>{state}</Text>
          {note && <Text size="xs" c="dimmed">{note}</Text>}
        </div>
        <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>{t('web.open')}</Text>
      </Group>
    </UnstyledButton>
  );
}

export default function CharOverview({ go }: { go: (r: Route) => void }) {
  const t = useT();
  const cur = useCurrent();
  const objs = useObjects();
  const o = useOverview(asCharacter(cur) ? cur.id : null);
  const model = o ? o.rigged || o.source : null;

  const add = async (f: File | null) => {
    if (!f) return;
    try {
      const [up] = await upload([f]);
      const r = await post<{ ok: boolean; id?: string; log: string }>('/api/char/add', { path: up.path });
      if (!r.ok || !r.id) { notifications.show({ color: 'rust', message: r.log }); return; }
      objs.refresh();
      objs.choose(r.id);
      notifications.show({ color: 'patina', message: t('web.char_added', r.id.split('/')[1]) });
    } catch (e) { notifications.show({ color: 'rust', message: String(e) }); }
  };

  const rig = o?.rig;
  const mouth = rig?.mouth === 'cut' ? t('web.ov_mouth_cut') : rig?.mouth === 'plate' ? t('web.ov_mouth_plate') : '';
  const clipText = o ? [o.clips.procedural && t('web.ov_clips_proc', o.clips.procedural.count ?? '✓'), o.clips.mixamo && t('web.ov_clips_mixamo', o.clips.mixamo.count ?? '✓')].filter(Boolean).join(', ') : '';
  const step = (section: string, s: string) => () => go({ section, step: s });

  return (
    <div className="work two">
      <div className="stage">
        <Viewer3D url={model ? fileUrl(model, o?.files.find((x) => model.endsWith(x.name))?.when) : null} empty={t(asCharacter(cur) ? 'web.ov_no_model' : 'web.need_character')} person />
      </div>
      <ScrollArea className="panel">
        <Stack gap="sm" p="sm">
          <div>
            <div className="panel-title">{o?.name || t('web.sec_character')}</div>
            {o && <div className="field-note">{o.dir}</div>}
          </div>
          {!(asCharacter(cur)) && <PickList />}
          {o && <>
            <Row title={t('ui.skeleton')} ok={!!rig} onOpen={step('character', 'skeleton')}
              state={rig ? `${t(rig.kind === 'landmark' ? 'web.ov_landmark' : 'web.ov_auto')}, ${t('web.ov_bones', rig.bones)}` : t('web.ov_none')}
              note={rig ? `${rig.file}, ${rig.when}` : t('web.ov_skeleton_hint')} />
            <Row title={t('web.step_face')} ok={!!(rig && (rig.mouth || rig.eyes))} onOpen={step('character', 'face')}
              state={rig && (rig.mouth || rig.eyes) ? [mouth, rig.eyes && t('web.ov_eyes'), rig.retopo && t('web.ov_retopo')].filter(Boolean).join(', ') : t('web.ov_none')}
              note={o.speech ? t('web.ov_speech', o.speech) : undefined} />
            <Row title={t('web.step_look')} ok={o.hair.length > 0} onOpen={step('character', 'look')}
              state={o.hair.length ? o.hair.map((x) => x.replace(/\.glb$/, '')).join(', ') : t('web.ov_none')} />
            <Row title={t('cr.anim_tab')} ok={!!clipText} onOpen={step('character', 'anim')} state={clipText || t('web.ov_none')} />
            <Row title={t('web.sec_equipment')} ok={o.worn > 0} onOpen={step('equipment', o.worn ? 'release' : 'catalog')} state={o.worn ? t('web.ov_worn', o.worn) : t('web.ov_none')} />
            <Row title={t('web.step_game')} onOpen={step('character', 'game')} state={t('ed.fitting_room_in_godot')} />
          </>}
          <Group grow>
            <FileButton onChange={add} accept=".glb">{(p) => <Button {...p} variant="default" leftSection={<IconPlus size={16} />}>{t('ui.char_add')}</Button>}</FileButton>
            {o && <Button variant="default" leftSection={<IconFolder size={16} />} onClick={() => post('/api/open', { path: o.dir })}>{t('ui.char_open_folder')}</Button>}
          </Group>
          {o && (
            <details className="files">
              <summary>{t('web.files', o.files.length)}</summary>
              {o.files.map((f) => <div key={f.name} className="file-row"><span>{f.name}</span><span>{f.when}</span></div>)}
            </details>)}
          {o && <Button variant="subtle" color="rust" leftSection={<IconTrash size={16} />} onClick={() => askRemove([{ id: o.id, draft: false }])}>{t('ui.char_delete')}</Button>}
          {objs.characters.length > 0 && (
            <details className="files">
              <summary>{t('web.rm_manage', objs.characters.length)}</summary>
              <ObjectsChecklist list={objs.characters} />
            </details>)}
        </Stack>
      </ScrollArea>
    </div>
  );
}
