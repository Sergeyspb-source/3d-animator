// A GLB in three.js (the same library as the app's editors): orbit, views, grid, wireframe, the collision proxy
// (Godot's <name>-colonly / -convcolonly nodes: hidden unless asked), a 1.75 m person beside it for scale.
import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { Loader, Text, Tooltip } from '@mantine/core';
import { IconFocusCentered, IconGridDots, IconBox, IconUser, IconShape } from '@tabler/icons-react';
import { useT } from '../i18n';

const COLLISION = /-(conv)?colonly$/;
type View = 'front' | 'side' | 'back' | 'top';
export interface Measured { faces: number; size: [number, number, number] }

interface Props { url: string | null; empty?: string; onMeasured?: (m: Measured | null) => void; person?: boolean }

export default function Viewer3D({ url, empty, onMeasured, person: personDefault = false }: Props) {
  const t = useT();
  const host = useRef<HTMLDivElement>(null);
  const ctx = useRef<any>(null);
  const [busy, setBusy] = useState(false);
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
    ctx.current = { renderer, scene, cam, controls, gridH, man, root, box: new THREE.Box3(), loader: new GLTFLoader() };
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
    const dir = { front: [0, 0.12, 1], side: [1, 0.12, 0], back: [0, 0.12, -1], top: [0, 1, 0.001] }[v];
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
    }, undefined, (e: any) => { if (alive) { setErr(String(e?.message || e)); setBusy(false); } });
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
      {busy && <Loader className="viewer-busy" size="sm" />}
      {err && <Text className="viewer-empty" c="rust.4">{t('web.v_failed', err)}</Text>}
    </div>
  );
}
