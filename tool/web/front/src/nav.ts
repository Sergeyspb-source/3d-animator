// The left menu: sections are the chains of work, steps stand in the order of work. A step either has its screen
// here already (ready) or still lives in the Gradio app (gradio: the tab's path there, by text keys).
import { IconBox, IconUser, IconShield, IconPaw, IconTrees, type Icon } from '@tabler/icons-react';

export interface Step { id: string; key: string; ready?: boolean; gradio?: string[]; about: string }
export interface Section { id: string; key: string; icon: Icon; object?: 'character' | 'creature'; steps: Step[] }

export const SECTIONS: Section[] = [
  { id: 'models', key: 'web.sec_models', icon: IconBox, steps: [
    { id: 'ref', key: 'ui.reference', gradio: ['ui.create', 'ui.reference'], about: 'web.about_ref' },
    { id: 'create', key: 'ui.make_a_model', ready: true, about: 'web.about_create' },
    { id: 'check', key: 'web.step_check', ready: true, about: 'web.about_check' },
    { id: 'materials', key: 'web.step_model_materials', gradio: ['ui.create', 'ui.materials'], about: 'web.about_model_materials' },
    { id: 'release', key: 'web.step_release', ready: true, about: 'web.about_release' },
    { id: 'batch', key: 'ui.batch_processing_2', gradio: ['ui.create', 'ui.batch_processing_2'], about: 'web.about_batch' },
  ] },
  { id: 'character', key: 'web.sec_character', icon: IconUser, object: 'character', steps: [
    { id: 'overview', ready: true, key: 'web.step_overview', gradio: ['ui.character'], about: 'web.about_char_overview' },
    { id: 'skeleton', ready: true, key: 'ui.skeleton', gradio: ['ui.character', 'ui.skeleton'], about: 'web.about_char_skeleton' },
    { id: 'face', key: 'web.step_face', gradio: ['ui.character', 'ui.face_parts'], about: 'web.about_char_face' },
    { id: 'look', ready: true, key: 'web.step_look', gradio: ['ui.character', 'ui.equipment_procedural'], about: 'web.about_char_look' },
    { id: 'anim', key: 'cr.anim_tab', gradio: ['ui.character', 'ui.animations_procedural'], about: 'web.about_char_anim' },
    { id: 'weights', ready: true, key: 'web.step_weights', gradio: ['ui.character', 'ui.weight_fixing'], about: 'web.about_weights' },
    { id: 'game', ready: true, key: 'web.step_game', gradio: ['ui.character', 'ui.equipment_procedural'], about: 'web.about_char_game' },
  ] },
  { id: 'equipment', key: 'web.sec_equipment', icon: IconShield, object: 'character', steps: [
    { id: 'workshop', ready: true, key: 'web.step_workshop', gradio: ['ui.character', 'ui.equipment_procedural'], about: 'web.about_eq_workshop' },
    { id: 'materials', ready: true, key: 'web.step_eq_materials', gradio: ['ui.character', 'ui.equipment_procedural'], about: 'web.about_eq_materials' },
    { id: 'fit', ready: true, key: 'web.step_fit', gradio: ['ui.character', 'ui.equipment_procedural'], about: 'web.about_eq_fit' },
    { id: 'check', ready: true, key: 'web.step_check', gradio: ['ui.character', 'ui.equipment_procedural'], about: 'web.about_eq_check' },
    { id: 'release', ready: true, key: 'web.step_release', gradio: ['ui.character', 'ui.equipment_procedural'], about: 'web.about_eq_release' },
  ] },
  { id: 'creatures', key: 'cr.section', icon: IconPaw, object: 'creature', steps: [
    { id: 'overview', key: 'web.step_overview', gradio: ['cr.section'], about: 'web.about_cr_overview' },
    { id: 'skeleton', key: 'ui.skeleton', gradio: ['cr.section', 'ui.skeleton'], about: 'web.about_cr_skeleton' },
    { id: 'eyes', key: 'web.step_eyes', gradio: ['cr.section', 'ui.skeleton'], about: 'web.about_cr_eyes' },
    { id: 'anim', key: 'cr.anim_tab', gradio: ['cr.section', 'cr.anim_tab'], about: 'web.about_cr_anim' },
    { id: 'paint', key: 'web.step_paint', gradio: ['cr.section', 'cr.paint_tab'], about: 'web.about_cr_paint' },
    { id: 'weights', key: 'web.step_weights', gradio: ['cr.section', 'ui.weight_fixing'], about: 'web.about_weights' },
    { id: 'game', key: 'web.step_game', gradio: ['cr.section', 'cr.anim_tab'], about: 'web.about_cr_game' },
  ] },
  { id: 'environment', key: 'ui.environment', icon: IconTrees, steps: [
    { id: 'surfaces', key: 'web.step_surfaces', gradio: ['ui.environment', 'ui.surfaces_ground_floor_walls'], about: 'web.about_surfaces' },
    { id: 'fx', key: 'web.step_fx', gradio: ['ui.environment', 'ui.effects_particles'], about: 'web.about_fx' },
    { id: 'dungeons', key: 'web.step_dungeons', gradio: ['ui.environment', 'ui.modular_kits_dungeon'], about: 'web.about_dungeons' },
    { id: 'destructibles', key: 'web.step_destructibles', gradio: ['ui.environment', 'ui.destructible_objects'], about: 'web.about_destructibles' },
    { id: 'vegetation', key: 'web.step_vegetation', ready: true, about: 'web.about_vegetation' },
  ] },
];

export const TOOLS = [
  { id: 'tasks', key: 'web.tool_tasks' },
  { id: 'gpu', key: 'web.tool_gpu' },
  { id: 'settings', key: 'ui.settings_2' },
] as const;

export interface Route { section: string; step: string }
export function parseHash(h: string): Route {
  const [section, step] = h.replace(/^#/, '').split('-');
  const sec = SECTIONS.find((s) => s.id === section);
  if (sec) return { section, step: sec.steps.some((x) => x.id === step) ? step : sec.steps.find((x) => x.ready)?.id ?? sec.steps[0].id };
  if (TOOLS.some((x) => x.id === section)) return { section, step: '' };
  return { section: 'models', step: 'create' };
}
export const hashOf = (r: Route) => '#' + r.section + (r.step ? '-' + r.step : '');
export const stepOf = (r: Route) => SECTIONS.find((s) => s.id === r.section)?.steps.find((x) => x.id === r.step);
