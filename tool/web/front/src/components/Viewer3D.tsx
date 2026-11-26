// A GLB in three.js (the same library as the app's editors): orbit, views, grid, wireframe, the collision proxy
// (Godot's <name>-colonly / -convcolonly nodes: hidden unless asked), a 1.75 m person beside it for scale (a capsule
// labelled so; the camera looks level from the model's middle, so it stands upright), «Loading… %» while it comes.
import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { Text, Tooltip } from '@mantine/core';
import { IconFocusCentered, IconGridDots, IconBox, IconUser, IconShape } from '@tabler/icons-react';
import { useT } from '../i18n';
import LoadingVeil from './LoadingVeil';

const COLLISION = /-(conv)?colonly$/;

// the gauge's label: a sprite over the capsule, its text drawn on a canvas
function drawTag(sprite: THREE.Sprite, text: string) {
  const cv = document.createElement('canvas');
  cv.width = 512; cv.height = 112;
  const g = cv.getContext('2d')!;
  g.fillStyle = 'rgba(20, 24, 28, 0.72)';
  g.beginPath(); g.roundRect(4, 8, 504, 96, 22); g.fill();
  g.fillStyle = '#e8edf2'; g.font = '600 46px "Golos Text", "Segoe UI", sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text, 256, 58);
  const old = sprite.material.map;
  sprite.material.map = new THREE.CanvasTexture(cv);
  sprite.material.map.colorSpace = THREE.SRGBColorSpace;
  sprite.material.needsUpdate = true;
  old?.dispose();
}
type View = 'front' | 'side' | 'back' | 'top';
export interface Measured { faces: number; size: [number, number, number] }

interface Props { url: string | null; empty?: string; onMeasured?: (m: Measured | null) => void; person?: boolean }

export default function Viewer3D({ url, empty, onMeasured, person: personDefault = false }: Props) {
  const t = useT();
  const host = useRef<HTMLDivElement>(null);
  const ctx = useRef<any>(null);
  const [busy, setBusy] = useState(false);
  const [pct, setPct] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [view, setView] = useState<View>('front');
  const [grid, setGrid] = useState(true);
  const [wire, setWire] = useState(false);
  const [col, setCol] = useState(false);
  const [person, setPerson] = useState(personDefault);
  const [info, setInfo] = useState<Measured | null>(null);

  // the scene, once
  useEffect(() => {
    const el = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    const cam = new THREE.PerspectiveCamera(35, 1, 0.01, 500);
    const controls = new OrbitControls(cam, renderer.domElement);
    controls.enableDamping = true;
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(2, 4, 3);
    scene.add(sun, new THREE.AmbientLight(0xffffff, 0.25));
    const gridH = new THREE.GridHelper(10, 20, 0x9a8462, 0x55606c);   // (0.5 m cells; brass centre lines)
    (gridH.material as THREE.Material).transparent = true;
    (gridH.material as THREE.Material).opacity = 0.45;
    scene.add(gridH);
    const man = new THREE.Mesh(new THREE.CapsuleGeometry(0.2, 1.75 - 0.4, 6, 16),
      new THREE.MeshStandardMaterial({ color: 0x6f8fb0, transparent: true, opacity: 0.35, roughness: 0.9 }));
    man.visible = false;
    scene.add(man);
    const tag = new THREE.Sprite(new THREE.SpriteMaterial({ transparent: true, depthWrite: false }));
    tag.scale.set(0.82, 0.18, 1);
    tag.position.set(0, 1.75 / 2 + 0.16, 0);   // (over the capsule's top: it moves and hides with it)
    man.add(tag);
    const root = new THREE.Group();
    scene.add(root);
    const resize = () => {
      const w = el.clientWidth, h = el.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      renderer.domElement.style.width = '100%';
      renderer.domElement.style.height = '100%';
      cam.aspect = w / h;
      cam.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();
    let raf = 0;
    const tick = () => { controls.update(); renderer.render(scene, cam); raf = requestAnimationFrame(tick); };
    tick();
    ctx.current = { renderer, scene, cam, controls, gridH, man, tag, root, box: new THREE.Box3(), loader: new GLTFLoader() };
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      pmrem.dispose();
      el.removeChild(renderer.domElement);
    };
  }, []);

  const frame = (v: View = view) => {
    const c = ctx.current;
    if (!c) return;
    const box: THREE.Box3 = c.box.isEmpty() ? new THREE.Box3(new THREE.Vector3(-0.5, 0, -0.5), new THREE.Vector3(0.5, 1, 0.5)) : c.box.clone();
    if (c.man.visible) box.union(new THREE.Box3().setFromObject(c.man));
    const centre = box.getCenter(new THREE.Vector3());
    const r = box.getSize(new THREE.Vector3()).length() / 2 || 1;
    const d = r / Math.sin(THREE.MathUtils.degToRad(c.cam.fov / 2)) * 1.05;
    // (level from the middle: what stands upright on the screen stands upright, the capsule too)
    const dir = { front: [0, 0, 1], side: [1, 0, 0], back: [0, 0, -1], top: [0, 1, 0.001] }[v];
    c.cam.position.copy(centre).add(new THREE.Vector3(...dir).normalize().multiplyScalar(d));
    c.cam.near = d / 100;
    c.cam.far = d * 20;
    c.cam.updateProjectionMatrix();
    c.controls.target.copy(centre);
    c.controls.update();
  };

  // the model
  useEffect(() => {
    const c = ctx.current;
    if (!c) return;
    c.root.clear();
    c.box.makeEmpty();
    setInfo(null);
    onMeasured?.(null);
    setErr(null);
    if (!url) { frame(); return; }
    let alive = true;
    setBusy(true);
    setPct(null);
    c.loader.load(url, (g: any) => {
      if (!alive) return;
      const scene: THREE.Object3D = g.scene;
      let faces = 0;
      scene.traverse((o: any) => {
        if (COLLISION.test(o.name || '')) { o.userData.collision = true; o.visible = col; return; }
        if (o.isMesh) {
          let inCol = false;
          o.traverseAncestors((a: any) => { if (a.userData.collision) inCol = true; });
          if (inCol) return;
          const gi = o.geometry;
          faces += gi.index ? gi.index.count / 3 : gi.attributes.position.count / 3;
        }
      });
      c.root.add(scene);
      scene.updateMatrixWorld(true);
      const box = new THREE.Box3();
      scene.traverse((o: any) => {
        if (!o.isMesh) return;
        let inCol = false;
        o.traverseAncestors((a: any) => { if (a.userData.collision) inCol = true; });
        if (!inCol) box.expandByObject(o);
      });
      c.box.copy(box);
      const size = box.getSize(new THREE.Vector3());
      c.gridH.position.y = box.min.y;
      c.man.position.set(box.min.x - 0.45, box.min.y + 1.75 / 2, box.getCenter(new THREE.Vector3()).z);
      const m: Measured = { faces: Math.round(faces), size: [size.x, size.y, size.z] };
      setInfo(m);
      onMeasured?.(m);
      applyLook();
      frame();
      setBusy(false);
    }, (e: ProgressEvent) => { if (alive && e.total) setPct(Math.round((100 * e.loaded) / e.total)); },
    (e: any) => { if (alive) { setErr(String(e?.message || e)); setBusy(false); } });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  const applyLook = () => {
    const c = ctx.current;
    if (!c) return;
    c.gridH.visible = grid;
    c.man.visible = person;
    c.root.traverse((o: any) => {
      if (o.userData.collision) {
        o.visible = col;
        o.traverse((m: any) => { if (m.isMesh) m.material = new THREE.MeshBasicMaterial({ color: 0xff8a3d, wireframe: true, transparent: true, opacity: 0.7 }); });
      } else if (o.isMesh && o.material) {
        for (const mat of Array.isArray(o.material) ? o.material : [o.material]) mat.wireframe = wire;
      }
    });
  };
  useEffect(() => { if (ctx.current) drawTag(ctx.current.tag, t('web.v_person_tag')); }, [t]);
  useEffect(applyLook, [grid, wire, col, person]);
  useEffect(() => { frame(view); }, [view, person]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {   // F: the model in the frame again
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.key.toLowerCase() === 'f' && !e.ctrlKey && !e.metaKey && !['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) frame();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const fmt = (x: number) => x.toFixed(x < 1 ? 2 : 1);
  const views: [View, string][] = [['front', t('ag.view_front')], ['side', t('ag.view_side')], ['back', t('ag.view_back')], ['top', t('web.view_top')]];
  const toggles: [boolean, () => void, string, typeof IconGridDots][] = [
    [grid, () => setGrid(!grid), t('web.v_grid'), IconGridDots], [wire, () => setWire(!wire), t('web.v_wire'), IconShape],
    [col, () => setCol(!col), t('web.v_collision'), IconBox], [person, () => setPerson(!person), t('web.v_person'), IconUser]];
  return (
    <div className="viewer">
      <div className="viewer-canvas" ref={host} />
      <div className="viewer-tools" role="toolbar">
        {views.map(([v, label]) => <button key={v} type="button" className={'vt' + (view === v ? ' on' : '')} onClick={() => setView(v)}>{label}</button>)}
        <span className="sep" />
        <Tooltip label={t('web.v_frame')}><button type="button" className="vt icon" onClick={() => frame()} aria-label={t('web.v_frame')}><IconFocusCentered size={16} /></button></Tooltip>
        {toggles.map(([on, act, label, I]) => (
          <Tooltip key={label} label={label}><button type="button" className={'vt icon' + (on ? ' on' : '')} onClick={act} aria-label={label} aria-pressed={on}><I size={16} /></button></Tooltip>))}
      </div>
      {info && (
        <div className="viewer-badge">
          <span>{info.faces.toLocaleString()}<em>{t('web.v_faces_unit')}</em></span>
          <span>{fmt(info.size[0])} × {fmt(info.size[1])} × {fmt(info.size[2])}<em>{t('web.m')}</em></span>
        </div>
      )}
      {!url && empty && <Text className="viewer-empty">{empty}</Text>}
      {busy && <LoadingVeil text={t('web.loading_model')} pct={pct} />}
      {err && <Text className="viewer-empty" c="rust.4">{t('web.v_failed', err)}</Text>}
    </div>
  );
}
