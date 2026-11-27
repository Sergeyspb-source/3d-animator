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
// Wheel: zoom at the cursor; drag with the right or middle button or with Space held: pan.
import { useEffect, useMemo, useRef, useState } from 'react';
import { Snapshots, useUndoKeys } from '../undo';
import UndoButtons from './UndoButtons';
import * as THREE from 'three';
import { Button, Checkbox, SegmentedControl, Slider, Text, Tooltip } from '@mantine/core';
import { fileUrl } from '../api';
import { useT } from '../i18n';

export type Pin = [number, number, number, number];   // the picture's point (sx, sy) -> lands on the model at (dx, dy)
interface P { id: number; s: [number, number]; d: [number, number]; mate?: number }
export interface Mark { name: string; kind: string; model: [number, number] | null; pic: [number, number]; set: boolean }
export interface AlignData { picture: string; model: string; size: [number, number]; mid_x: number | null; pins: Pin[]; marks?: Mark[] }
interface State { pins: P[]; marks: Mark[] }

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
const markPins = (ms: Mark[]): Pin[] => ms.filter((m) => m.set && m.model).map((m) => [m.pic[0], m.pic[1], m.model![0], m.model![1]]);
const MARK_KEY: Record<string, string> = { ear_tip: 'web.imp_mk_ear_tip', ear_hole: 'web.imp_mk_ear_hole', elbow: 'web.imp_mk_elbow',
  hand: 'web.imp_mk_hand', knee: 'web.imp_mk_knee' };

export default function PinEditor({ data, onSave, onClose, onMark3d }: {
  data: AlignData; onSave: (pins: Pin[], marks: Record<string, [number, number]>) => Promise<void> | void; onClose: () => void;
  onMark3d?: (name: string, x: number, y: number, mirror: boolean) => Promise<AlignData | null>;
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
  const [mode, setMode] = useState<'pins' | 'marks'>('pins');
  const [sel, setSel] = useState<string | null>(null);
  const [sym, setSym] = useState(data.mid_x != null);
  const [op, setOp] = useState(0.55);
  const [show, setShow] = useState<'mix' | 'pic' | 'model'>('mix');
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busy3d, setBusy3d] = useState(false);
  const view = useRef({ s: 1, x: 0, y: 0 });   // screen = (picture - (x, y)) * s
  const [, redraw] = useState(0);
  const gl = useRef<any>(null);
  const freeField = useMemo(() => pinField(toPins(pins)), [pins]);
  const field = useMemo(() => pinField([...toPins(pins), ...markPins(marks)]), [pins, marks]);
  const shown = mode === 'marks' ? freeField : field;   // (landmarks are placed on the picture bent by the pins only)
  // undo / redo (Ctrl+Z, Ctrl+Shift+Z or Ctrl+Y, the ↶ ↷ buttons): a pin or a landmark put, dragged (one step for the
  // drag), removed, «Clear»; the editor is drawn anew for another model or view, its history with it
  const hist = useRef(new Snapshots<State>()).current;
  const now = (): State => ({ pins, marks });
  const mark = (before: State) => { hist.mark(before); redraw((x) => x + 1); };
  const histStep = (back: boolean) => {
    if (drag.current) return;
    const x = hist.step(back, now()); if (!x) return;
    setPins(x.pins); setMarks(x.marks); setDirty(true);
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
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(W, H), new THREE.MeshBasicMaterial({ map: tex(fileUrl(data.model)), transparent: true }));
    ground.position.set(W / 2, -H / 2, 0);
    scene.add(ground);
    const nx = 96, ny = Math.max(8, Math.round(96 * H / W));
    const geo = new THREE.PlaneGeometry(W, H, nx, ny);
    const mat = new THREE.MeshBasicMaterial({ map: tex(fileUrl(data.picture)), transparent: true, opacity: op, depthTest: false });
    const sheet = new THREE.Mesh(geo, mat);
    sheet.position.set(W / 2, -H / 2, 1);
    scene.add(sheet);
    const draw = () => {
      const r = el.getBoundingClientRect();
      renderer.setSize(r.width, r.height, false);
      renderer.domElement.style.width = r.width + 'px'; renderer.domElement.style.height = r.height + 'px';
      const v = view.current;
      cam.left = v.x; cam.right = v.x + r.width / v.s; cam.top = -v.y; cam.bottom = -(v.y + r.height / v.s);
      cam.updateProjectionMatrix();
      renderer.render(scene, cam);
    };
    gl.current = { geo, mat, ground, draw, renderer };
    const ro = new ResizeObserver(() => { fit(); draw(); redraw((x) => x + 1); });
    ro.observe(el);
    return () => { ro.disconnect(); renderer.dispose(); el.removeChild(renderer.domElement); };
  }, [data.picture, data.model]); // eslint-disable-line react-hooks/exhaustive-deps

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
    g.draw();
  }, [op, show]);

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
  type Drag = { kind: 'pin' | 'pan' | 'mpic' | 'mmodel'; id?: number; name?: string; at?: [number, number]; v0?: { s: number; x: number; y: number };
    before?: State; moved?: boolean; q?: [number, number] };
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
      await onSave(toPins(pins), ms); setDirty(false);
    } finally { setSaving(false); }
  };
  const markLabel = (n: string) => `${t(MARK_KEY[n.slice(0, -2)] || n)} ${n.endsWith('_L') ? t('web.imp_mk_l') : t('web.imp_mk_r')}`;

  const v = view.current;
  const sx = (x: number) => (x - v.x) * v.s, sy = (y: number) => (y - v.y) * v.s;
  const nSet = marks.filter((m) => m.set).length;
  return (
    <div className="pin-editor">
      <div className="pin-bar">
        {hasMarks && <SegmentedControl size="xs" value={mode} onChange={(x) => setMode(x as any)} data={[
          { value: 'pins', label: t('web.imp_pe_pins') }, { value: 'marks', label: t('web.imp_pe_marks', nSet) }]} />}
        <SegmentedControl size="xs" value={show} onChange={(x) => setShow(x as any)} data={[
          { value: 'mix', label: t('web.imp_pe_mix') }, { value: 'pic', label: t('web.imp_pe_pic') }, { value: 'model', label: t('web.imp_pe_model') }]} />
        <div style={{ width: 110 }}><Slider size="xs" min={0.1} max={0.9} step={0.05} value={op} onChange={setOp} label={null} disabled={show !== 'mix'} /></div>
        {mid != null && <Checkbox size="xs" label={t('web.imp_pe_sym')} checked={sym} onChange={(e) => setSym(e.currentTarget.checked)} />}
        <Button size="compact-xs" variant="default" onClick={() => { fit(); gl.current?.draw(); redraw((x) => x + 1); }}>{t('web.imp_pe_fit')}</Button>
        {mode === 'pins'
          ? <Button size="compact-xs" variant="default" color="red" disabled={!pins.length} onClick={() => { mark(now()); setPins([]); setDirty(true); }}>{t('web.imp_pe_clear')}</Button>
          : <Tooltip label={t('web.imp_pe_take_guess_tip')}><Button size="compact-xs" variant="default" disabled={marks.every((m) => m.set)}
              onClick={() => { mark(now()); setMarks((ms) => ms.map((m) => ({ ...m, set: true }))); setDirty(true); }}>{t('web.imp_pe_take_guess')}</Button></Tooltip>}
        <UndoButtons can={[hist.undo.length > 0, hist.redo.length > 0]} onStep={histStep} />
        <div style={{ flex: 1 }} />
        <Text size="xs" c="dimmed">{busy3d ? t('web.imp_pe_on_model') : t('web.imp_pe_count', pins.length)}</Text>
        <Button size="compact-sm" onClick={save} loading={saving} disabled={!dirty}>{t('web.imp_pe_save')}</Button>
        <Button size="compact-sm" variant="default" onClick={onClose}>{t('web.imp_pe_close')}</Button>
      </div>
      {mode === 'marks' && (
        <div className="mark-bar">
          {marks.map((m) => (
            <button key={m.name} className={'mark-chip' + (sel === m.name ? ' on' : '') + (m.set ? ' set' : '')} onClick={() => setSel(m.name)}>
              {markLabel(m.name)}
            </button>
          ))}
        </div>
      )}
      <div className="pin-canvas" ref={host} onPointerDown={down} onPointerMove={move} onPointerUp={up} onWheel={wheel}
        onContextMenu={(e) => e.preventDefault()}>
        <svg className="pin-svg">
          {mid != null && sym && <line x1={sx(mid)} x2={sx(mid)} y1={0} y2="100%" className="pin-mid" />}
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
      <div className="pin-help">{mode === 'marks' ? t('web.imp_pe_help_marks') : t('web.imp_pe_help')}</div>
    </div>
  );
}
