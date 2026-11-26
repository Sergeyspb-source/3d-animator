// A piece's pictogram: a small figure with the place the piece goes lit (a helmet the head, a bracer the forearms...),
// and what is held drawn by its style: a bow with its string, a long staff or spear, a two-handed weapon with both
// hands on it, a quiver on the back (sticking out by the left hip and over the right shoulder) or on the hip. Drawn at
// once, nothing rendered; the ids are the procedural editor's (armour_gen_ui.PIECES, its weapon_* / sheath_* styles).

type Part = 'cloak' | 'head' | 'neck' | 'chest' | 'belly' | 'waist' | 'hips' | 'shoulder' | 'upperarm' | 'elbow' | 'forearm' | 'hand'
  | 'thigh' | 'knee' | 'shin' | 'foot';

const ZONES: Record<string, Part[]> = {
  helmet: ['head'], coif: ['head', 'neck'], hood: ['head', 'neck'], gorget: ['neck'], pelerine: ['neck', 'shoulder'],
  hair: ['head'], beard: ['head'], brows: ['head'], lashes: ['head'],
  cuirass: ['chest', 'belly'], hauberk: ['chest', 'belly', 'hips', 'upperarm'], pauldron: ['shoulder'], rondel: ['shoulder'], ailette: ['shoulder'],
  rerebrace: ['upperarm'], elbow: ['elbow'], bracer: ['forearm'], glove: ['hand'],
  fauld: ['belly'], tassets: ['hips'], culet: ['hips'], codpiece: ['hips'], brayette: ['hips'], belt: ['waist'],
  cuisse: ['thigh'], poleyn: ['knee'], greave: ['shin'], footwear: ['foot'], wraps: ['shin', 'forearm'],
  trousers: ['hips', 'thigh', 'shin'], skirt: ['hips', 'thigh'], undercloth: ['chest', 'belly', 'upperarm', 'forearm'],
  tunic: ['chest', 'belly', 'hips'], vest: ['chest', 'belly'], apron: ['belly', 'hips', 'thigh'], tabard: ['chest', 'belly', 'hips'],
  cloak: ['cloak'],
};

const BODY = 'var(--piece-body, #6b7580)', HOT = 'var(--piece-hot, var(--mantine-color-ember-5))';
const line = (d: string, c: string, w = 3.6) => `<path d="${d}" fill="none" stroke="${c}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"/>`;
const fill = (el: string, c: string) => `<g fill="${c}">${el}</g>`;
const dots = (pts: number[][], r: number, c: string) => fill(pts.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="${r}"/>`).join(''), c);

// the arms at rest, or both hands together on a two-handed weapon's grip
const ARMS = {
  rest: { upper: 'M11.5 18.5 L8 29 M28.5 18.5 L32 29', fore: 'M8 30 L6 40 M32 30 L34 40', elbow: [[8, 29.5], [32, 29.5]], hand: [[5.7, 42.3], [34.3, 42.3]] },
  two: { upper: 'M11.5 18.5 L10 29 M28.5 18.5 L31 29', fore: 'M10 30 L22.6 38.4 M31 30 L26.6 38.6', elbow: [[10, 29.5], [31, 29.5]], hand: [[23.6, 39.2], [26.4, 39.4]] },
};

// what is held, by its style (drawn over the figure)
const BOW = (top: number, bottom: number, c: string) =>
  line(`M33.6 ${top} Q${42 + (bottom - top - 32) / 10} ${(top + bottom) / 2} 33.6 ${bottom}`, c, 1.8) + line(`M33.6 ${top} L33.6 ${bottom}`, c, 0.7);
const HELD: Record<string, (c: string) => string> = {
  weapon_sword: (c) => line('M34.3 41 L37.4 19', c, 2.2) + line('M32.4 39.4 L36.6 40.4', c, 1.6),
  weapon_dagger: (c) => line('M34.3 41 L35.6 32', c, 2) + line('M33 39.6 L36 40.2', c, 1.4),
  weapon_axe: (c) => line('M34.6 44 L37 21', c, 1.6) + fill('<path d="M36.6 21.5 L40.5 19.5 L40.5 27 L36.2 25.5 Z"/>', c),
  weapon_mace: (c) => line('M34.6 44 L36.8 23', c, 1.6) + dots([[37, 21.5]], 2.6, c),
  weapon_warhammer: (c) => line('M34.6 44 L36.6 22', c, 1.6) + fill('<rect x="33.6" y="18.6" width="6.6" height="3.4" rx=".6"/>', c),
  weapon_club: (c) => line('M34.5 43 L37.2 22', c, 3.4) + dots([[37.3, 21.5]], 2.2, c),
  weapon_spear: (c) => line('M35.2 67 L36.8 6', c, 1.5) + fill('<path d="M36.9 0.8 L38.5 6.4 L35.3 6.4 Z"/>', c),
  weapon_staff: (c) => line('M35.2 67 L36.9 6', c, 2) + dots([[37, 5.6]], 1.7, c),
  weapon_greatsword: (c) => line('M25 39.5 L33.5 4', c, 2.4) + line('M22.4 36.4 L28.4 38.6', c, 1.6),
  weapon_greataxe: (c) => line('M24.6 45 L33 6', c, 1.7) + fill('<path d="M32.6 6.6 L38.8 4 L38.8 13.6 L31.6 11.6 Z"/>', c),
  weapon_bow: (c) => BOW(26, 58, c), weapon_bow_flat: (c) => BOW(25, 59, c), weapon_bow_riser: (c) => BOW(26, 58, c),
  weapon_bow_recurve: (c) => BOW(25, 59, c), weapon_bow_scythian: (c) => BOW(27, 57, c), weapon_bow_mongol: (c) => BOW(26, 58, c),
  weapon_bow_turkish: (c) => BOW(27, 57, c), weapon_bow_long: (c) => BOW(14, 68, c), weapon_bow_yumi: (c) => BOW(10, 64, c),
  shield: (c) => fill('<ellipse cx="6" cy="35" rx="5" ry="7"/>', c),
  sheath_scabbard: (c) => line('M26.5 32.5 L33.5 48.5', c, 2.4) + line('M25.2 33.6 L28.4 32', c, 1.4),
  sheath_dagger: (c) => line('M26.5 32.5 L29.5 40.5', c, 2.2) + line('M25.4 33.4 L28 32.2', c, 1.2),
  sheath_quiver_hip: (c) => fill('<rect x="26.6" y="33" width="4.4" height="12" rx="1" transform="rotate(-12 28.8 39)"/>', c)
    + line('M27.4 33.2 L26.2 28.8 M29 33 L29.2 28.4 M30.5 33.4 L31.8 29.2', c, 1),
};
// behind the figure: a quiver on the back, across it (its foot by the left hip, its mouth over the right shoulder)
const BEHIND: Record<string, (c: string) => string> = {
  sheath_quiver: (c) => line('M6.2 41 L32.6 9.6', c, 5) + line('M32.6 9.6 L34.8 4.4 M30.8 9.4 L31.2 4.2 M34 10.8 L37.6 7', c, 1.1),
};
const TWO_HANDED = ['weapon_greatsword', 'weapon_greataxe'];   // (the editor's w_two: its second hand on the haft)

export default function PieceIcon({ piece, style, size = 40 }: { piece: string | null | undefined; style?: string | null; size?: number }) {
  const kind = piece === 'weapon' ? (style && HELD[style] ? style : 'weapon_sword')
    : piece === 'sheath' ? (style && (HELD[style] || BEHIND[style]) ? style : 'sheath_scabbard')
    : piece === 'shield' ? 'shield' : null;
  const lit = new Set<Part>(ZONES[piece || ''] ?? []);
  const col = (p: Part) => (lit.has(p) ? HOT : BODY);
  const arms = ARMS[kind && TWO_HANDED.includes(kind) ? 'two' : 'rest'];
  const html = [
    lit.has('cloak') ? fill('<path d="M11 16 L29 16 L33 60 L7 60 Z"/>', HOT) : '',
    kind && BEHIND[kind] ? BEHIND[kind](HOT) : '',
    line('M16.5 38 L16 52 M23.5 38 L24 52', col('thigh')),
    line('M16 53 L16 65 M24 53 L24 65', col('shin')),
    fill('<rect x="12.5" y="65" width="5" height="3.2" rx="1.4"/><rect x="22.5" y="65" width="5" height="3.2" rx="1.4"/>', col('foot')),
    dots([[16, 52.5], [24, 52.5]], 2, col('knee')),
    fill('<rect x="13" y="31" width="14" height="7" rx="3"/>', col('hips')),
    fill('<rect x="13.5" y="25" width="13" height="6.5" rx="2"/>', col('belly')),
    fill('<rect x="12.5" y="16" width="15" height="9.5" rx="3"/>', col('chest')),
    lit.has('waist') ? fill('<rect x="13" y="30" width="14" height="2.2" rx="1"/>', HOT) : '',
    line(arms.upper, col('upperarm')),
    line(arms.fore, col('forearm')),
    dots(arms.hand, 2.1, col('hand')),
    dots(arms.elbow, 2, col('elbow')),
    dots([[12.5, 17.5], [27.5, 17.5]], 2.6, col('shoulder')),
    line('M20 13 L20 16', col('neck')),
    fill('<circle cx="20" cy="7.5" r="5.5"/>', col('head')),
    kind && HELD[kind] ? HELD[kind](HOT) : '',
  ].join('');
  return <svg className="piece-icon" viewBox="0 0 40 72" width={(size * 40) / 72} height={size} aria-hidden="true" dangerouslySetInnerHTML={{ __html: html }} />;
}
