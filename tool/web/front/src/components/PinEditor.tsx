// Hand fitting for «Improve»: the model drawn grey from the camera fitted to one picture, the picture over it (half
// seen), and two ways to say what belongs where (Gaussian radial basis, the same formulas as model_improve.pin_field,
// so what is seen here is what gets projected):
//  - Pins: drag from a feature of the picture (an eye corner, a nostril) to where it belongs on the model; the picture
//    bends smoothly so every pin lands exactly. Symmetric: a mirrored mate across the model's middle (front and back
//    views). Shift+click: a pin that holds its place. Right click on a pin: removes it (and its mate).
//  - Landmarks (characters): named points - ear tips, ear holes, elbows, hands, knees. The model's point is a 3D point
//    the app guessed (blue ring); drag it to move it on the model (it moves in every view: an ear fitted in the front and
//    the side picture alike). The picture's point (orange square, a first guess shown dashed) goes where that feature
//    is on the picture: pick a name, then click or drag. Shown over the picture bent by the pins only.
//  - Brush (a skin laid flat): «only the front» (the side, the back) - there that one picture paints the texture (a
//    side's doubled brow or nostril painted over); the stamp - Alt+click where to take from, then paint where it goes
//    (a spot no picture sees): there the texture takes the surface that far away. Shown after «Save».
// Wheel: zoom at the cursor; drag with the right or middle button or with Space held: pan.
import { useEffect, useMemo, useRef, useState } from 'react';
import { Snapshots, useUndoKeys } from '../undo';
import UndoButtons from './UndoButtons';
import * as THREE from 'three';
import { Button, Checkbox, SegmentedControl, Slider, Text, Tooltip } from '@mantine/core';
import { IconArrowLeft } from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import { fileUrl } from '../api';
import { useT } from '../i18n';

export type Pin = [number, number, number, number];   // the picture's point (sx, sy) -> lands on the model at (dx, dy)
interface P { id: number; s: [number, number]; d: [number, number]; mate?: number }
export interface Mark { name: string; kind: string; model: [number, number] | null; pic: [number, number]; set: boolean }
export interface Stroke { kind: 'only' | 'clone'; view?: string; off?: [number, number]; c: [number, number, number][] }
// the front picture's face fitted by its points (model_improve.face_field, every k-th cell): read before the pins
export interface FaceGrid { x0: number; y0: number; step: number; k: number; nx: number; ny: number; d: number[] }
export interface AlignData { picture: string; model: string; lines?: string; size: [number, number]; mid_x: number | null; pins: Pin[]; marks?: Mark[];
  kind?: string; brush?: Stroke[]; left_x?: number; views?: string[]; ver?: number; face?: FaceGrid | null }
interface State { pins: P[]; marks: Mark[]; strokes: Stroke[] }
type Tool = 'front' | 'side' | 'back' | 'clone' | 'erase';
const TOOL_COLOR: Record<string, string> = { front: '#4aa8ff', left: '#5fd38a', right: '#5fd38a', back: '#b48cff', clone: '#ffa94d' };

// ------------------------------------------------------------------ the warp (model_improve.pin_field)
export function pinField(pins: Pin[]) {
  const n = pins.length;
  if (!n) return (_x: number, _y: number): [number, number] => [0, 0];
  const dst = pins.map((p) => [p[2], p[3]]), disp = pins.map((p) => [p[0] - p[2], p[1] - p[3]]);
  const dist = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const sig = dst.map((a, i) => {
    let s = n > 1 ? Math.min(...dst.map((b, j) => (i === j ? 1e9 : dist(a, b)))) * 0.7 : 96;
    s = Math.min(Math.max(s, 12), 160);
    return Math.max(s, Math.hypot(disp[i][0], disp[i][1]) * 1.2, 12);
  });
  // (Phi + 1e-6 I) alpha = disp, Phi[i][k] = exp(-|d_i - d_k|^2 / 2 sig_k^2): Gaussian elimination, two right sides
  const A = dst.map((a, i) => dst.map((b, k) => Math.exp(-(dist(a, b) ** 2) / (2 * sig[k] ** 2)) + (i === k ? 1e-6 : 0)));
  const B = disp.map((x) => [...x]);
  for (let c = 0; c < n; c++) {
    let piv = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(A[r][c]) > Math.abs(A[piv][c])) piv = r;
    [A[c], A[piv]] = [A[piv], A[c]]; [B[c], B[piv]] = [B[piv], B[c]];
    for (let r = 0; r < n; r++) {
      if (r === c) continue;
      const f = A[r][c] / A[c][c];
      for (let k = c; k < n; k++) A[r][k] -= f * A[c][k];
      B[r][0] -= f * B[c][0]; B[r][1] -= f * B[c][1];
    }
  }
  const alpha = B.map((b, i) => [b[0] / A[i][i], b[1] / A[i][i]]);
  return (x: number, y: number): [number, number] => {
    let ox = 0, oy = 0;
    for (let k = 0; k < n; k++) {
      const w = Math.exp(-((x - dst[k][0]) ** 2 + (y - dst[k][1]) ** 2) / (2 * sig[k] ** 2));
      ox += alpha[k][0] * w; oy += alpha[k][1] * w;
    }
    return [ox, oy];
  };
}

const toPins = (ps: P[]): Pin[] => ps.map((p) => [p.s[0], p.s[1], p.d[0], p.d[1]]);
// the face field at a point (bilinear between its cells, nothing off them), as model_improve.field_at
function faceAt(f: FaceGrid) {
  return (x: number, y: number): [number, number] => {
    const gx = ((x - f.x0) / f.step - 0.5) / f.k, gy = ((y - f.y0) / f.step - 0.5) / f.k;
    if (gx < 0 || gy < 0 || gx > f.nx - 1 || gy > f.ny - 1) return [0, 0];
    const i = Math.min(Math.floor(gx), f.nx - 2), j = Math.min(Math.floor(gy), f.ny - 2), u = gx - i, v = gy - j;
    const at = (a: number, b: number, c: number) => f.d[(b * f.nx + a) * 2 + c];
    const lerp = (c: number) => (at(i, j, c) * (1 - u) + at(i + 1, j, c) * u) * (1 - v) + (at(i, j + 1, c) * (1 - u) + at(i + 1, j + 1, c) * u) * v;
    return [lerp(0), lerp(1)];
  };
}
const markPins = (ms: Mark[]): Pin[] => ms.filter((m) => m.set && m.model).map((m) => [m.pic[0], m.pic[1], m.model![0], m.model![1]]);
const MARK_KEY: Record<string, string> = { ear_tip: 'web.imp_mk_ear_tip', ear_hole: 'web.imp_mk_ear_hole', elbow: 'web.imp_mk_elbow',
  hand: 'web.imp_mk_hand', knee: 'web.imp_mk_knee' };

// pending: the page's handle on unsaved work - set to «save it» while something is unsaved, null when all is saved
// (the page saves it before another model is picked or «Improve» runs; leaving the page saves it too)
export default function PinEditor({ data, onSave, onClose, onMark3d, pending }: {
  data: AlignData; onSave: (pins: Pin[], marks: Record<string, [number, number]>, brush?: Stroke[]) => Promise<void> | void; onClose: () => void;
  onMark3d?: (name: string, x: number, y: number, mirror: boolean) => Promise<AlignData | null>;
  pending?: React.MutableRefObject<(() => Promise<void>) | null>;
}) {
  const t = useT();
  const host = useRef<HTMLDivElement>(null);
  const [W, H] = data.size;
  const [pins, setPins] = useState<P[]>(() => {
    let id = 1;
    const ps: P[] = data.pins.map((p) => ({ id: id++, s: [p[0], p[1]], d: [p[2], p[3]] }));
    if (data.mid_x != null) {   // (saved pins come without their mates: paired again by mirror image)
      const m = data.mid_x;
      for (const a of ps) {
        if (a.mate) continue;
        const b = ps.find((x) => x !== a && !x.mate && Math.hypot(2 * m - a.d[0] - x.d[0], a.d[1] - x.d[1]) < 2);
        if (b) { a.mate = b.id; b.mate = a.id; }
      }
    }
    return ps;
  });
  const [marks, setMarks] = useState<Mark[]>(() => data.marks || []);
  const hasMarks = marks.length > 0;
  const isSkin = data.kind === 'skin';
  const [strokes, setStrokes] = useState<Stroke[]>(() => data.brush || []);
  const [tool, setTool] = useState<Tool>('front');
  const [radius, setRadius] = useState(18);
  const [src, setSrc] = useState<[number, number] | null>(null);   // (the stamp: where it takes from)
  const cloneOff = useRef<[number, number] | null>(null);   // (fixed by the first stamp after a source is set)
  const hover = useRef<[number, number] | null>(null);
  const [mode, setMode] = useState<'pins' | 'marks' | 'brush'>('pins');
  const [sel, setSel] = useState<string | null>(null);
  const [sym, setSym] = useState(data.mid_x != null);
  const [op, setOp] = useState(0.55);
  const [show, setShow] = useState<'mix' | 'pic' | 'model'>('mix');
  const [relief, setRelief] = useState(true);   // the model's relief as height lines over everything (not bent by the pins)
  const [dirty, setDirty] = useState(false);
  const dirtyNow = useRef(false);   // (as dirty, read on the way out; cleared by a save at once, before any render)
  dirtyNow.current = dirty;
  const [saving, setSaving] = useState(false);
  const [busy3d, setBusy3d] = useState(false);
  const view = useRef({ s: 1, x: 0, y: 0 });   // screen = (picture - (x, y)) * s
  const [, redraw] = useState(0);
  const gl = useRef<any>(null);
  // (with the face field: the picture is read at q + F(q) + D(q), the pins solved with F taken out of their picture
  // points, as model_improve.reads)
  const F = useMemo(() => (data.face ? faceAt(data.face) : null), [data.face]);
  const withFace = (ps: Pin[]) => {
    if (!F) return pinField(ps);
    const D = pinField(ps.map(([sx, sy, dx, dy]) => { const [fx, fy] = F(dx, dy); return [sx - fx, sy - fy, dx, dy] as Pin; }));
    return (x: number, y: number): [number, number] => { const [a, b] = F(x, y), [c, e] = D(x, y); return [a + c, b + e]; };
  };
  const freeField = useMemo(() => withFace(toPins(pins)), [pins, F]); // eslint-disable-line react-hooks/exhaustive-deps
  const field = useMemo(() => withFace([...toPins(pins), ...markPins(marks)]), [pins, marks, F]); // eslint-disable-line react-hooks/exhaustive-deps
  const shown = mode === 'marks' ? freeField : field;   // (landmarks are placed on the picture bent by the pins only)
  // undo / redo (Ctrl+Z, Ctrl+Shift+Z or Ctrl+Y, the ↶ ↷ buttons): a pin or a landmark put, dragged (one step for the
  // drag), removed, «Clear»; the editor is drawn anew for another model or view, its history with it
  const hist = useRef(new Snapshots<State>()).current;
  const now = (): State => ({ pins, marks, strokes });
  const mark = (before: State) => { hist.mark(before); redraw((x) => x + 1); };
  const histStep = (back: boolean) => {
    if (drag.current) return;
    const x = hist.step(back, now()); if (!x) return;
    setPins(x.pins); setMarks(x.marks); setStrokes(x.strokes); setDirty(true);
  };
  useUndoKeys((redo) => histStep(!redo));

  // ---- three.js: the model picture as the ground, the picture on a bent grid over it
  useEffect(() => {
    const el = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const cam = new THREE.OrthographicCamera(0, W, 0, -H, -10, 10);
    const loader = new THREE.TextureLoader();
    const tex = (u: string) => { const x = loader.load(u, () => draw()); x.colorSpace = THREE.SRGBColorSpace; return x; };
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(W, H), new THREE.MeshBasicMaterial({ map: tex(fileUrl(data.model, data.ver)), transparent: true }));
    ground.position.set(W / 2, -H / 2, 0);
    scene.add(ground);
    const nx = 96, ny = Math.max(8, Math.round(96 * H / W));
    const geo = new THREE.PlaneGeometry(W, H, nx, ny);
    const mat = new THREE.MeshBasicMaterial({ map: tex(fileUrl(data.picture, data.ver)), transparent: true, opacity: op, depthTest: false });
    const sheet = new THREE.Mesh(geo, mat);
    sheet.position.set(W / 2, -H / 2, 1);
    scene.add(sheet);
    const lines = data.lines ? new THREE.Mesh(new THREE.PlaneGeometry(W, H),
      new THREE.MeshBasicMaterial({ map: tex(fileUrl(data.lines)), transparent: true, depthTest: false })) : null;
    if (lines) { lines.position.set(W / 2, -H / 2, 2); lines.renderOrder = 2; lines.visible = relief; scene.add(lines); }
    sheet.renderOrder = 1;
    const draw = () => {
      const r = el.getBoundingClientRect();
      renderer.setSize(r.width, r.height, false);
      renderer.domElement.style.width = r.width + 'px'; renderer.domElement.style.height = r.height + 'px';
      const v = view.current;
      cam.left = v.x; cam.right = v.x + r.width / v.s; cam.top = -v.y; cam.bottom = -(v.y + r.height / v.s);
      cam.updateProjectionMatrix();
      renderer.render(scene, cam);
    };
    gl.current = { geo, mat, ground, lines, draw, renderer };
    const ro = new ResizeObserver(() => { fit(); draw(); redraw((x) => x + 1); });
    ro.observe(el);
    return () => { ro.disconnect(); renderer.dispose(); el.removeChild(renderer.domElement); };
  }, [data.picture, data.model, data.lines, data.ver]); // eslint-disable-line react-hooks/exhaustive-deps

  const fit = () => {   // the whole picture in view
    const r = host.current!.getBoundingClientRect();
    const s = Math.min(r.width / W, r.height / H) * 0.96;
    view.current = { s, x: -(r.width / s - W) / 2, y: -(r.height / s - H) / 2 };
  };

  // the grid's texture coordinates from the pins: each vertex at q shows the picture at q + D(q)
  useEffect(() => {
    const g = gl.current; if (!g) return;
    const pos = g.geo.attributes.position, uv = g.geo.attributes.uv;
    for (let i = 0; i < pos.count; i++) {
      const qx = pos.getX(i) + W / 2, qy = H / 2 - pos.getY(i);
      const [dx, dy] = shown(qx, qy);
      uv.setXY(i, (qx + dx) / W, 1 - (qy + dy) / H);
    }
    uv.needsUpdate = true;
    g.draw();
  }, [shown]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const g = gl.current; if (!g) return;
    g.mat.opacity = show === 'model' ? 0 : show === 'pic' ? 1 : op;
    g.ground.visible = show !== 'pic';
    if (g.lines) g.lines.visible = relief;
    g.draw();
  }, [op, show, relief]);

  // ---- mouse
  const toPic = (e: { clientX: number; clientY: number }): [number, number] => {
    const r = host.current!.getBoundingClientRect(), v = view.current;
    return [(e.clientX - r.left) / v.s + v.x, (e.clientY - r.top) / v.s + v.y];
  };
  // the screen place where the bent picture shows its point p: q with q + D(q) = p (a few fixed-point steps)
  const whereShown = (p: [number, number]): [number, number] => {
    let q: [number, number] = [p[0], p[1]];
    for (let i = 0; i < 8; i++) { const [dx, dy] = shown(q[0], q[1]); q = [p[0] - dx, p[1] - dy]; }
    return q;
  };
  type Drag = { kind: 'pin' | 'pan' | 'mpic' | 'mmodel' | 'paint' | 'erase'; id?: number; name?: string; at?: [number, number];
    v0?: { s: number; x: number; y: number }; before?: State; moved?: boolean; q?: [number, number]; idx?: number[]; last?: [number, number] };
  const drag = useRef<Drag | null>(null);
  const panMoved = useRef(0);   // (a right-button drag ends with a context menu event: not a «remove» then)
  const space = useRef(false);
  useEffect(() => {
    const kd = (e: KeyboardEvent) => { if (e.code === 'Space') space.current = true; };
    const ku = (e: KeyboardEvent) => { if (e.code === 'Space') space.current = false; };
    window.addEventListener('keydown', kd); window.addEventListener('keyup', ku);
    return () => { window.removeEventListener('keydown', kd); window.removeEventListener('keyup', ku); };
  }, []);
  const mid = data.mid_x;
  const mirrorPt = (p: [number, number]): [number, number] => [2 * (mid ?? 0) - p[0], p[1]];
  const mirrorName = (n: string) => n.slice(0, -1) + (n.endsWith('L') ? 'R' : 'L');
  const nextId = () => Math.max(0, ...pins.map((p) => p.id)) + 1;
  const setMarkPic = (ms: Mark[], name: string, p: [number, number]) => ms.map((m) => (m.name === name ? { ...m, pic: p, set: true }
    : sym && mid != null && m.name === mirrorName(name) ? { ...m, pic: mirrorPt(p), set: true } : m));

  const startPan = (e: React.PointerEvent) => { panMoved.current = 0; drag.current = { kind: 'pan', at: [e.clientX, e.clientY], v0: { ...view.current } }; };
  const down = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture?.(e.pointerId);
    if (e.button === 1 || e.button === 2 || space.current) { startPan(e); return; }
    if (e.button !== 0) return;
    const q = toPic(e);
    if (mode === 'brush') { brushDown(e, q); return; }
    if (mode === 'marks') {   // the picked landmark's picture point: here (what the picture bent by the pins shows here)
      if (!sel) return;
      const [dx, dy] = freeField(q[0], q[1]);
      mark(now());
      setMarks((ms) => setMarkPic(ms, sel, [q[0] + dx, q[1] + dy]));
      setDirty(true);
      drag.current = { kind: 'mpic', name: sel };
      return;
    }
    const [dx, dy] = field(q[0], q[1]);
    const id = nextId();
    const s: [number, number] = e.shiftKey ? q : [q[0] + dx, q[1] + dy];   // (what is under the cursor now)
    const add: P[] = [{ id, s, d: q }];
    if (sym && mid != null && Math.abs(q[0] - mid) > 6) {
      const [mx, my] = mirrorPt(q), [ex, ey] = field(mx, my);
      add[0].mate = id + 1;
      add.push({ id: id + 1, s: e.shiftKey ? [mx, my] : [mx + ex, my + ey], d: [mx, my], mate: id });
    }
    mark(now());   // (the pin put and its drag: one step)
    setPins((ps) => [...ps, ...add]);
    setDirty(true);
    drag.current = e.shiftKey ? null : { kind: 'pin', id };
  };
  const move = (e: React.PointerEvent) => {
    const d = drag.current; if (!d) return;
    if (d.kind === 'pan') {
      const v0 = d.v0!;
      panMoved.current = Math.max(panMoved.current, Math.hypot(e.clientX - d.at![0], e.clientY - d.at![1]));
      view.current = { ...v0, x: v0.x - (e.clientX - d.at![0]) / v0.s, y: v0.y - (e.clientY - d.at![1]) / v0.s };
      gl.current?.draw(); redraw((x) => x + 1); return;
    }
    const q = toPic(e);
    if (d.kind === 'paint' || d.kind === 'erase') { brushMove(d, q); return; }
    if (d.before && !d.moved) { d.moved = true; mark(d.before); }   // (an existing handle dragged: a step once it moves)
    if (d.kind === 'mpic') {
      const [dx, dy] = freeField(q[0], q[1]);
      setMarks((ms) => setMarkPic(ms, d.name!, [q[0] + dx, q[1] + dy]));
      setDirty(true); return;
    }
    if (d.kind === 'mmodel') { d.q = q; redraw((x) => x + 1); return; }
    setPins((ps) => {
      const me = ps.find((p) => p.id === d.id); if (!me) return ps;
      return ps.map((p) => (p.id === d.id ? { ...p, d: q } : sym && mid != null && p.id === me.mate ? { ...p, d: mirrorPt(q) } : p));
    });
    setDirty(true);
  };
  const up = async () => {
    const d = drag.current; drag.current = null;
    if (d?.kind === 'mmodel' && d.q && d.moved && onMark3d) {   // the model point put back onto the model (3D) by the server
      setBusy3d(true);
      try {
        const a = await onMark3d(d.name!, d.q[0], d.q[1], sym);
        if (a?.marks) setMarks((ms) => ms.map((m) => { const n = a.marks!.find((x) => x.name === m.name); return n ? { ...m, model: n.model } : m; }));
      } finally { setBusy3d(false); redraw((x) => x + 1); }
    }
  };

  // ---- the brush (skins)
  const sideOf = (x: number) => ((x - (mid ?? 0)) * (data.left_x ?? 1) > 0 ? 'left' : 'right');
  const viewOf = (x: number): string => (tool === 'front' ? 'front' : tool === 'back' ? 'back' : sideOf(x));
  const swapLR = (v?: string) => (v === 'left' ? 'right' : v === 'right' ? 'left' : v);
  const eraseAt = (ss: Stroke[], q: [number, number]) => {
    const pts = [q, ...(sym && mid != null ? [mirrorPt(q)] : [])];
    return ss.map((s) => ({ ...s, c: s.c.filter(([x, y]) => pts.every((p) => Math.hypot(x - p[0], y - p[1]) > radius)) })).filter((s) => s.c.length);
  };
  const brushDown = (e: React.PointerEvent, q: [number, number]) => {
    if (tool === 'clone' && e.altKey) { setSrc(q); cloneOff.current = null; redraw((x) => x + 1); return; }
    if (tool === 'erase') { mark(now()); setStrokes((ss) => eraseAt(ss, q)); setDirty(true); drag.current = { kind: 'erase' }; return; }
    let add: Stroke[];
    const c: [number, number, number] = [q[0], q[1], radius];
    const mc = (): [number, number, number] => { const m = mirrorPt(q); return [m[0], m[1], radius]; };
    const twin = sym && mid != null && Math.abs(q[0] - mid) > radius;
    if (tool === 'clone') {
      if (!src) return;
      if (!cloneOff.current) cloneOff.current = [src[0] - q[0], src[1] - q[1]];
      const off = cloneOff.current;
      add = [{ kind: 'clone', off: [off[0], off[1]], c: [c] }];
      if (twin) add.push({ kind: 'clone', off: [-off[0], off[1]], c: [mc()] });
    } else {
      const v = viewOf(q[0]);
      add = [{ kind: 'only', view: v, c: [c] }];
      if (twin) add.push({ kind: 'only', view: swapLR(v), c: [mc()] });
    }
    mark(now());
    const n0 = strokes.length;
    setStrokes((ss) => [...ss, ...add]);
    setDirty(true);
    drag.current = { kind: 'paint', idx: add.map((_, i) => n0 + i), last: q };
  };
  const brushMove = (d: NonNullable<typeof drag.current>, q: [number, number]) => {
    if (d.kind === 'erase') { setStrokes((ss) => eraseAt(ss, q)); return; }
    if (Math.hypot(q[0] - d.last![0], q[1] - d.last![1]) < radius / 3) return;
    d.last = q;
    const m = mirrorPt(q);
    setStrokes((ss) => ss.map((s, i) => (i === d.idx![0] ? { ...s, c: [...s.c, [q[0], q[1], radius]] }
      : i === d.idx![1] ? { ...s, c: [...s.c, [m[0], m[1], radius]] } : s)));
  };
  const hoverMove = (e: React.PointerEvent) => {   // (the brush's ring under the pointer)
    if (mode !== 'brush') return;
    hover.current = toPic(e);
    if (!drag.current) redraw((x) => x + 1);
  };
  const grabPin = (e: React.PointerEvent, id: number) => {
    if (e.button !== 0) return;   // (right / middle: the pan, from the canvas under it)
    e.stopPropagation();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    drag.current = { kind: 'pin', id, before: now() };
  };
  const grabMark = (e: React.PointerEvent, name: string, which: 'mpic' | 'mmodel') => {
    if (e.button !== 0) return;
    e.stopPropagation();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    setSel(name);
    drag.current = { kind: which, name, before: now() };
  };
  const removePin = (e: React.MouseEvent, id: number) => {
    e.preventDefault(); e.stopPropagation();
    if (panMoved.current > 4) return;
    mark(now());
    setPins((ps) => { const me = ps.find((p) => p.id === id); return ps.filter((p) => p.id !== id && p.id !== me?.mate); });
    setDirty(true);
  };
  const unsetMark = (e: React.MouseEvent, name: string) => {   // right click: back to the first guess (not used)
    e.preventDefault(); e.stopPropagation();
    if (panMoved.current > 4) return;
    mark(now());
    const orig = (data.marks || []).find((m) => m.name === name);
    setMarks((ms) => ms.map((m) => (m.name === name ? { ...m, set: false, pic: orig && !orig.set ? orig.pic : m.model || m.pic } : m)));
    setDirty(true);
  };
  const wheel = (e: React.WheelEvent) => {
    const r = host.current!.getBoundingClientRect(), v = view.current;
    const q = toPic(e), k = Math.exp(-e.deltaY * 0.0015), s = Math.min(Math.max(v.s * k, 0.1), 40);
    view.current = { s, x: q[0] - (e.clientX - r.left) / s, y: q[1] - (e.clientY - r.top) / s };
    gl.current?.draw(); redraw((x) => x + 1);
  };
  const save = async () => {
    setSaving(true);
    try {
      const ms: Record<string, [number, number]> = {};
      for (const m of marks) if (m.set) ms[m.name] = m.pic;
      await onSave(toPins(pins), ms, isSkin ? strokes : undefined); setDirty(false); dirtyNow.current = false;
    } finally { setSaving(false); }
  };
  // back to the model: what is unsaved is saved first (never lost by leaving)
  const back = async () => {
    if (dirty) {
      try { await save(); } catch (x: any) { notifications.show({ color: 'red', message: String(x.message || x) }); return; }
    }
    onClose();
  };
  const saveNow = useRef(save);
  saveNow.current = save;
  useEffect(() => {
    if (pending) pending.current = dirty ? () => saveNow.current() : null;
  }, [dirty, pending]);
  useEffect(() => () => {   // (the page left with work unsaved: saved on the way out)
    if (pending) pending.current = null;
    if (dirtyNow.current) Promise.resolve(saveNow.current()).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const markLabel = (n: string) => `${t(MARK_KEY[n.slice(0, -2)] || n)} ${n.endsWith('_L') ? t('web.imp_mk_l') : t('web.imp_mk_r')}`;

  const v = view.current;
  const sx = (x: number) => (x - v.x) * v.s, sy = (y: number) => (y - v.y) * v.s;
  const nSet = marks.filter((m) => m.set).length;
  return (
    <div className="pin-editor">
      <div className="pin-bar">
        <Tooltip label={t(dirty ? 'web.imp_pe_back_save_tip' : 'web.imp_pe_back_tip')}>
          <Button size="compact-sm" variant="light" leftSection={<IconArrowLeft size={14} />} onClick={back} loading={saving}>
            {t(dirty ? 'web.imp_pe_back_save' : 'web.imp_pe_back')}</Button></Tooltip>
        {(hasMarks || isSkin) && <SegmentedControl size="xs" value={mode} onChange={(x) => setMode(x as any)} data={[
          { value: 'pins', label: t('web.imp_pe_pins') },
          ...(hasMarks ? [{ value: 'marks', label: t('web.imp_pe_marks', nSet) }] : []),
          ...(isSkin ? [{ value: 'brush', label: t('web.imp_pe_brush') }] : [])]} />}
        <SegmentedControl size="xs" value={show} onChange={(x) => setShow(x as any)} data={[
          { value: 'mix', label: t('web.imp_pe_mix') }, { value: 'pic', label: t('web.imp_pe_pic') }, { value: 'model', label: t('web.imp_pe_model') }]} />
        <div style={{ width: 110 }}><Slider size="xs" min={0.1} max={0.9} step={0.05} value={op} onChange={setOp} label={null} disabled={show !== 'mix'} /></div>
        {data.lines && <Tooltip label={t('web.imp_pe_relief_tip')} multiline w={320}>
          <Checkbox size="xs" label={t('web.imp_pe_relief')} checked={relief} onChange={(e) => setRelief(e.currentTarget.checked)} /></Tooltip>}
        {mid != null && <Checkbox size="xs" label={t('web.imp_pe_sym')} checked={sym} onChange={(e) => setSym(e.currentTarget.checked)} />}
        <Button size="compact-xs" variant="default" onClick={() => { fit(); gl.current?.draw(); redraw((x) => x + 1); }}>{t('web.imp_pe_fit')}</Button>
        {mode === 'brush'
          ? <Button size="compact-xs" variant="default" color="red" disabled={!strokes.length} onClick={() => { mark(now()); setStrokes([]); setDirty(true); }}>{t('web.imp_pe_clear')}</Button>
          : mode === 'pins'
          ? <Button size="compact-xs" variant="default" color="red" disabled={!pins.length} onClick={() => { mark(now()); setPins([]); setDirty(true); }}>{t('web.imp_pe_clear')}</Button>
          : <Tooltip label={t('web.imp_pe_take_guess_tip')}><Button size="compact-xs" variant="default" disabled={marks.every((m) => m.set)}
              onClick={() => { mark(now()); setMarks((ms) => ms.map((m) => ({ ...m, set: true }))); setDirty(true); }}>{t('web.imp_pe_take_guess')}</Button></Tooltip>}
        <UndoButtons can={[hist.undo.length > 0, hist.redo.length > 0]} onStep={histStep} />
        <div style={{ flex: 1 }} />
        <Text size="xs" c="dimmed">{busy3d ? t('web.imp_pe_on_model') : mode === 'brush' ? t('web.imp_br_count', strokes.length) : t('web.imp_pe_count', pins.length)}</Text>
        <Button size="compact-sm" onClick={save} loading={saving} disabled={!dirty}>{t('web.imp_pe_save')}</Button>
      </div>
      {mode === 'brush' && (
        <div className="mark-bar">
          <SegmentedControl size="xs" value={tool} onChange={(x) => setTool(x as Tool)} data={[
            { value: 'front', label: t('web.imp_br_front') }, { value: 'side', label: t('web.imp_br_side') },
            { value: 'back', label: t('web.imp_br_back') }, { value: 'clone', label: t('web.imp_br_clone') },
            { value: 'erase', label: t('web.imp_br_erase') }]} />
          <Text size="xs" c="dimmed">{t('web.imp_br_size')}</Text>
          <div style={{ width: 120 }}><Slider size="xs" min={4} max={120} step={1} value={radius} onChange={setRadius} label={(x) => x} /></div>
          {tool === 'clone' && <Text size="xs" c={src ? 'dimmed' : 'yellow'}>{src ? t('web.imp_br_src_set') : t('web.imp_br_need_src')}</Text>}
        </div>
      )}
      {mode === 'marks' && (
        <div className="mark-bar">
          {marks.map((m) => (
            <button key={m.name} className={'mark-chip' + (sel === m.name ? ' on' : '') + (m.set ? ' set' : '')} onClick={() => setSel(m.name)}>
              {markLabel(m.name)}
            </button>
          ))}
        </div>
      )}
      <div className={'pin-canvas' + (mode === 'brush' ? ' brushing' : '')} ref={host} onPointerDown={down}
        onPointerMove={(e) => { hoverMove(e); move(e); }} onPointerUp={up} onWheel={wheel}
        onPointerLeave={() => { hover.current = null; if (mode === 'brush') redraw((x) => x + 1); }}
        onContextMenu={(e) => e.preventDefault()}>
        <svg className="pin-svg">
          {mid != null && sym && <line x1={sx(mid)} x2={sx(mid)} y1={0} y2="100%" className="pin-mid" />}
          {isSkin && strokes.map((st, i) => (   // (the strokes: each one evenly see-through, its circles opaque inside it)
            <g key={i} opacity={mode === 'brush' ? 0.34 : 0.16} fill={TOOL_COLOR[st.kind === 'clone' ? 'clone' : st.view || 'front']}>
              {st.c.map(([x, y, r], k) => <circle key={k} cx={sx(x)} cy={sy(y)} r={r * v.s} />)}
            </g>
          ))}
          {mode === 'brush' && tool === 'clone' && src && (
            <g className="brush-src">
              <circle cx={sx(src[0])} cy={sy(src[1])} r={radius * v.s} />
              <line x1={sx(src[0]) - 8} x2={sx(src[0]) + 8} y1={sy(src[1])} y2={sy(src[1])} />
              <line x1={sx(src[0])} x2={sx(src[0])} y1={sy(src[1]) - 8} y2={sy(src[1]) + 8} />
            </g>)}
          {mode === 'brush' && hover.current && (() => {
            const h = hover.current!, off = cloneOff.current;
            return (
              <g className="brush-ring">
                <circle cx={sx(h[0])} cy={sy(h[1])} r={radius * v.s} />
                {tool === 'clone' && off && <circle cx={sx(h[0] + off[0])} cy={sy(h[1] + off[1])} r={radius * v.s} className="src" />}
              </g>);
          })()}
          {mode === 'pins' && pins.map((p) => (
            <g key={p.id}>
              <line x1={sx(p.s[0])} y1={sy(p.s[1])} x2={sx(p.d[0])} y2={sy(p.d[1])} className="pin-line" />
              <circle cx={sx(p.s[0])} cy={sy(p.s[1])} r={3} className="pin-src" />
              <circle cx={sx(p.d[0])} cy={sy(p.d[1])} r={6} className={'pin-dst' + (p.s[0] === p.d[0] && p.s[1] === p.d[1] ? ' hold' : '')}
                onPointerDown={(e) => grabPin(e, p.id)} onContextMenu={(e) => removePin(e, p.id)} />
            </g>
          ))}
          {mode === 'pins' && marks.filter((m) => m.set && m.model).map((m) => (   // (landmarks in the pins mode: where they land)
            <rect key={m.name} x={sx(m.model![0]) - 4} y={sy(m.model![1]) - 4} width={8} height={8} className="mark-landed" />
          ))}
          {mode === 'marks' && marks.map((m) => {
            const d = drag.current;
            const mp = d?.kind === 'mmodel' && d.name === m.name && d.q ? d.q : m.model;
            const pp = whereShown(m.pic);
            const on = sel === m.name;
            return (
              <g key={m.name} className={on ? 'mark on' : 'mark'}>
                {mp && <line x1={sx(pp[0])} y1={sy(pp[1])} x2={sx(mp[0])} y2={sy(mp[1])} className="mark-line" />}
                {mp && <circle cx={sx(mp[0])} cy={sy(mp[1])} r={on ? 8 : 6} className="mark-model"
                  onPointerDown={(e) => grabMark(e, m.name, 'mmodel')} />}
                <rect x={sx(pp[0]) - 5} y={sy(pp[1]) - 5} width={10} height={10} className={'mark-pic' + (m.set ? '' : ' guess')}
                  onPointerDown={(e) => grabMark(e, m.name, 'mpic')} onContextMenu={(e) => unsetMark(e, m.name)} />
                {on && <text x={sx(pp[0]) + 9} y={sy(pp[1]) - 8} className="mark-label">{markLabel(m.name)}</text>}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="pin-help">{mode === 'marks' ? t('web.imp_pe_help_marks') : mode === 'brush' ? t('web.imp_br_help') : t('web.imp_pe_help')}</div>
    </div>
  );
}
