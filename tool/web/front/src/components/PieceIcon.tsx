// A piece's pictogram: a small figure with the place the piece goes lit (a helmet the head, a bracer the forearms...).
// Drawn at once, nothing rendered; the piece ids are the procedural editor's (armour_gen_ui.PIECES).

type Part = 'cloak' | 'head' | 'neck' | 'chest' | 'belly' | 'waist' | 'hips' | 'shoulder' | 'upperarm' | 'elbow' | 'forearm' | 'hand'
  | 'thigh' | 'knee' | 'shin' | 'foot' | 'weapon' | 'shield' | 'sheath';

const ZONES: Record<string, Part[]> = {
  helmet: ['head'], coif: ['head', 'neck'], hood: ['head', 'neck'], gorget: ['neck'], pelerine: ['neck', 'shoulder'],
  hair: ['head'], beard: ['head'], brows: ['head'], lashes: ['head'],
  cuirass: ['chest', 'belly'], hauberk: ['chest', 'belly', 'hips', 'upperarm'], pauldron: ['shoulder'], rondel: ['shoulder'], ailette: ['shoulder'],
  rerebrace: ['upperarm'], elbow: ['elbow'], bracer: ['forearm'], glove: ['hand'],
  fauld: ['belly'], tassets: ['hips'], culet: ['hips'], codpiece: ['hips'], brayette: ['hips'], belt: ['waist'],
  cuisse: ['thigh'], poleyn: ['knee'], greave: ['shin'], footwear: ['foot'], wraps: ['shin', 'forearm'],
  trousers: ['hips', 'thigh', 'shin'], skirt: ['hips', 'thigh'], undercloth: ['chest', 'belly', 'upperarm', 'forearm'],
  tunic: ['chest', 'belly', 'hips'], vest: ['chest', 'belly'], apron: ['belly', 'hips', 'thigh'], tabard: ['chest', 'belly', 'hips'],
  cloak: ['cloak'], weapon: ['weapon'], shield: ['shield'], sheath: ['sheath'],
};

// each part: a filled shape (f) or a stroke (s), in a 40 × 72 box
const SHAPES: [Part, 'f' | 's', string][] = [
  ['cloak', 'f', '<path d="M11 16 L29 16 L33 60 L7 60 Z"/>'],
  ['thigh', 's', '<path d="M16.5 38 L16 52 M23.5 38 L24 52"/>'],
  ['shin', 's', '<path d="M16 53 L16 65 M24 53 L24 65"/>'],
  ['foot', 'f', '<rect x="12.5" y="65" width="5" height="3.2" rx="1.4"/><rect x="22.5" y="65" width="5" height="3.2" rx="1.4"/>'],
  ['knee', 'f', '<circle cx="16" cy="52.5" r="2"/><circle cx="24" cy="52.5" r="2"/>'],
  ['hips', 'f', '<rect x="13" y="31" width="14" height="7" rx="3"/>'],
  ['belly', 'f', '<rect x="13.5" y="25" width="13" height="6.5" rx="2"/>'],
  ['chest', 'f', '<rect x="12.5" y="16" width="15" height="9.5" rx="3"/>'],
  ['waist', 'f', '<rect x="13" y="30" width="14" height="2.2" rx="1"/>'],
  ['upperarm', 's', '<path d="M11.5 18.5 L8 29 M28.5 18.5 L32 29"/>'],
  ['forearm', 's', '<path d="M8 30 L6 40 M32 30 L34 40"/>'],
  ['hand', 'f', '<circle cx="5.7" cy="42.3" r="2.1"/><circle cx="34.3" cy="42.3" r="2.1"/>'],
  ['elbow', 'f', '<circle cx="8" cy="29.5" r="2"/><circle cx="32" cy="29.5" r="2"/>'],
  ['shoulder', 'f', '<circle cx="12.5" cy="17.5" r="2.6"/><circle cx="27.5" cy="17.5" r="2.6"/>'],
  ['neck', 's', '<path d="M20 13 L20 16"/>'],
  ['head', 'f', '<circle cx="20" cy="7.5" r="5.5"/>'],
  ['sheath', 's', '<path d="M27 33 L33 47"/>'],
  ['weapon', 's', '<path d="M34.3 42 L37.5 20"/>'],
  ['shield', 'f', '<ellipse cx="6" cy="35" rx="5" ry="7"/>'],
];
const EXTRA: Part[] = ['cloak', 'sheath', 'weapon', 'shield', 'waist'];   // (drawn only when they are the piece)

export default function PieceIcon({ piece, size = 40 }: { piece: string | null | undefined; size?: number }) {
  const lit = new Set<Part>(ZONES[piece || ''] ?? []);
  const body = 'var(--piece-body, #6b7580)', hot = 'var(--piece-hot, var(--mantine-color-ember-5))';
  const html = SHAPES.filter(([p]) => !EXTRA.includes(p) || lit.has(p)).map(([p, kind, d]) => {
    const c = lit.has(p) ? hot : body;
    return kind === 'f' ? `<g fill="${c}">${d}</g>` : `<g fill="none" stroke="${c}" stroke-width="3.6" stroke-linecap="round">${d}</g>`;
  }).join('');
  return <svg className="piece-icon" viewBox="0 0 40 72" width={(size * 40) / 72} height={size} aria-hidden="true" dangerouslySetInnerHTML={{ __html: html }} />;
}
