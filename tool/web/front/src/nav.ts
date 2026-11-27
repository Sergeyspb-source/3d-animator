// The left menu: sections are the chains of work, steps stand in the order of work.
import { IconBox, IconUser, IconShield, IconPaw, IconTrees, type Icon } from '@tabler/icons-react';

export interface Step { id: string; key: string; about: string }
export interface Section { id: string; key: string; icon: Icon; object?: 'character' | 'creature'; steps: Step[] }

export const SECTIONS: Section[] = [
  { id: 'models', key: 'web.sec_models', icon: IconBox, steps: [
    { id: 'ref', key: 'ui.reference', about: 'web.about_ref' },
    { id: 'create', key: 'ui.make_a_model', about: 'web.about_create' },
    { id: 'check', key: 'web.step_check', about: 'web.about_check' },
    { id: 'improve', key: 'web.step_improve', about: 'web.about_improve' },
    { id: 'materials', key: 'web.step_model_materials', about: 'web.about_model_materials' },
    { id: 'release', key: 'web.step_release', about: 'web.about_release' },
    { id: 'batch', key: 'ui.batch_processing_2', about: 'web.about_batch' },
  ] },
  { id: 'character', key: 'web.sec_character', icon: IconUser, object: 'character', steps: [
    { id: 'overview', key: 'web.step_overview', about: 'web.about_char_overview' },
    { id: 'skeleton', key: 'ui.skeleton', about: 'web.about_char_skeleton' },
    { id: 'face', key: 'web.step_face', about: 'web.about_char_face' },
    { id: 'look', key: 'web.step_look', about: 'web.about_char_look' },
    { id: 'anim', key: 'cr.anim_tab', about: 'web.about_char_anim' },
    { id: 'weights', key: 'web.step_weights', about: 'web.about_weights' },
    { id: 'game', key: 'web.step_game', about: 'web.about_char_game' },
  ] },
  { id: 'equipment', key: 'web.sec_equipment', icon: IconShield, object: 'character', steps: [
    { id: 'catalog', key: 'web.step_catalog', about: 'web.about_eq_catalog' },
    { id: 'workshop', key: 'web.step_workshop', about: 'web.about_eq_workshop' },
    { id: 'check', key: 'web.step_check', about: 'web.about_eq_check' },
    { id: 'release', key: 'web.step_release', about: 'web.about_eq_release' },
  ] },
  { id: 'creatures', key: 'cr.section', icon: IconPaw, object: 'creature', steps: [
    { id: 'overview', key: 'web.step_overview', about: 'web.about_cr_overview' },
    { id: 'skeleton', key: 'ui.skeleton', about: 'web.about_cr_skeleton' },
    { id: 'eyes', key: 'web.step_eyes', about: 'web.about_cr_eyes' },
    { id: 'anim', key: 'cr.anim_tab', about: 'web.about_cr_anim' },
    { id: 'paint', key: 'web.step_paint', about: 'web.about_cr_paint' },
    { id: 'weights', key: 'web.step_weights', about: 'web.about_weights' },
    { id: 'game', key: 'web.step_game', about: 'web.about_cr_game' },
  ] },
  { id: 'environment', key: 'ui.environment', icon: IconTrees, steps: [
    { id: 'surfaces', key: 'web.step_surfaces', about: 'web.about_surfaces' },
    { id: 'fx', key: 'web.step_fx', about: 'web.about_fx' },
    { id: 'dungeons', key: 'web.step_dungeons', about: 'web.about_dungeons' },
    { id: 'destructibles', key: 'web.step_destructibles', about: 'web.about_destructibles' },
    { id: 'vegetation', key: 'web.step_vegetation', about: 'web.about_vegetation' },
  ] },
];

export const TOOLS = [
  { id: 'tasks', key: 'web.tool_tasks' },
  { id: 'gpu', key: 'web.tool_gpu' },
  { id: 'settings', key: 'ui.settings_2' },
] as const;

export interface Route { section: string; step: string }
// steps that were merged into another (a link kept from before still lands on its work)
const MOVED: Record<string, string> = { 'equipment-fit': 'workshop', 'equipment-materials': 'workshop' };
export function parseHash(h: string): Route {
  const [section, step0] = h.replace(/^#/, '').split('-');
  const step = MOVED[`${section}-${step0}`] ?? step0;
  const sec = SECTIONS.find((s) => s.id === section);
  if (sec) return { section, step: sec.steps.some((x) => x.id === step) ? step : sec.steps[0].id };
  if (TOOLS.some((x) => x.id === section)) return { section, step: '' };
  return { section: 'models', step: 'create' };
}
export const hashOf = (r: Route) => '#' + r.section + (r.step ? '-' + r.step : '');
export const stepOf = (r: Route) => SECTIONS.find((s) => s.id === r.section)?.steps.find((x) => x.id === r.step);
