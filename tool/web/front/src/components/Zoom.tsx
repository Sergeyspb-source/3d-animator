// A picture opened large on a click: previews, sheets of views, source pictures, the check's frames, galleries.
// <ZoomImage src={path} group={paths} caption /> draws the small picture; a click shows it over the whole window
// (<ZoomHost /> once in the app): ← → to the group's other pictures, the wheel zooms at the cursor, a drag moves it,
// a double click or 0 fits it again, Esc or a click beside it closes. The file itself opens in a new tab from there.
import { useEffect, useRef, useState } from 'react';
import { ActionIcon, Image, Text, Tooltip, type ImageProps } from '@mantine/core';
import { IconChevronLeft, IconChevronRight, IconExternalLink, IconX, IconZoomIn } from '@tabler/icons-react';
import { fileUrl } from '../api';
import { useT } from '../i18n';

interface Shown { list: { src: string; caption?: string }[]; at: number }
const EV = 'sf3d-zoom';

// open a group of pictures (their paths, or urls already made) at one of them
export function zoom(list: (string | { src: string; caption?: string })[], at = 0) {
  const items = list.map((x) => (typeof x === 'string' ? { src: x } : x)).map((x) => ({ ...x, src: x.src.startsWith('/') || x.src.startsWith('http') || x.src.startsWith('blob:') ? x.src : fileUrl(x.src) }));
  window.dispatchEvent(new CustomEvent<Shown>(EV, { detail: { list: items, at: Math.max(0, at) } }));
}

// a picture that opens large: src a file's path (or a url); group: the pictures shown with it, in order
export function ZoomImage({ src, url, group, captions, caption, ...rest }:
  { src: string; url?: string; group?: string[]; captions?: (string | undefined)[]; caption?: string; title?: string } & ImageProps & { style?: React.CSSProperties }) {
  const open = (e: React.MouseEvent) => {
    e.stopPropagation(); e.preventDefault();
    const g = group && group.includes(src) ? group : [src];
    zoom(g.map((s, i) => ({ src: s, caption: captions?.[i] ?? (s === src ? caption : undefined) })), g.indexOf(src));
  };
  return <Image src={url || fileUrl(src)} {...rest} className={'zoomable ' + (rest.className || '')} onClick={open} />;
}

// the small loupe for a picture whose own click does something else (a gallery that picks)
export function ZoomButton({ list, at }: { list: string[]; at: number }) {
  const t = useT();
  return (
    <Tooltip label={t('web.zoom_open')}>
      <ActionIcon className="zoom-btn" size="sm" variant="default" aria-label={t('web.zoom_open')}
        onClick={(e) => { e.stopPropagation(); zoom(list, at); }}><IconZoomIn size={14} /></ActionIcon>
    </Tooltip>
  );
}

export function ZoomHost() {
  const t = useT();
  const [s, setS] = useState<Shown | null>(null);
  const [v, setV] = useState({ k: 1, x: 0, y: 0 });   // the picture's scale and shift (pixels)
  const drag = useRef<{ x: number; y: number; v: typeof v; moved: boolean } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const on = (e: Event) => { setS((e as CustomEvent<Shown>).detail); setV({ k: 1, x: 0, y: 0 }); };
    window.addEventListener(EV, on);
    return () => window.removeEventListener(EV, on);
  }, []);
  const n = s?.list.length || 0;
  const go = (d: number) => { if (!s || n < 2) return; setS({ ...s, at: (s.at + d + n) % n }); setV({ k: 1, x: 0, y: 0 }); };
  useEffect(() => {
    if (!s) return;
    const kd = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopPropagation(); setS(null); }
      else if (e.key === 'ArrowRight') go(1);
      else if (e.key === 'ArrowLeft') go(-1);
      else if (e.key === '0') setV({ k: 1, x: 0, y: 0 });
      else return;
      e.preventDefault();
    };
    window.addEventListener('keydown', kd, true);
    return () => window.removeEventListener('keydown', kd, true);
  }); // (each render: go sees the picture now)
  if (!s) return null;
  const it = s.list[s.at];
  const wheel = (e: React.WheelEvent) => {   // at the cursor: the point under it stays there
    const r = box.current!.getBoundingClientRect(), cx = e.clientX - r.left - r.width / 2, cy = e.clientY - r.top - r.height / 2;
    const k = Math.min(Math.max(v.k * Math.exp(-e.deltaY * 0.0015), 1), 12), f = k / v.k;
    setV(k === 1 ? { k: 1, x: 0, y: 0 } : { k, x: cx - (cx - v.x) * f, y: cy - (cy - v.y) * f });
  };
  return (
    <div className="zoom-host" role="dialog" aria-label={it.caption || t('web.zoom_open')} ref={box} onWheel={wheel}
      onPointerDown={(e) => { if (e.button === 0) { drag.current = { x: e.clientX, y: e.clientY, v, moved: false }; (e.target as Element).setPointerCapture?.(e.pointerId); } }}
      onPointerMove={(e) => { const d = drag.current; if (!d) return; const dx = e.clientX - d.x, dy = e.clientY - d.y;
        if (Math.hypot(dx, dy) > 3) d.moved = true; if (d.moved && d.v.k > 1) setV({ ...d.v, x: d.v.x + dx, y: d.v.y + dy }); }}
      onPointerUp={(e) => { const d = drag.current; drag.current = null; if (d && !d.moved && (e.target as Element).tagName !== 'IMG') setS(null); }}
      onDoubleClick={() => setV(v.k > 1 ? { k: 1, x: 0, y: 0 } : { k: 2.5, x: 0, y: 0 })}>
      <img src={it.src} alt={it.caption || ''} draggable={false} className={v.k > 1 ? 'grab' : ''}
        style={{ transform: `translate(${v.x}px, ${v.y}px) scale(${v.k})` }} />
      <div className="zoom-bar" onPointerDown={(e) => e.stopPropagation()} onPointerUp={(e) => e.stopPropagation()}>
        {n > 1 && <ActionIcon variant="default" onClick={() => go(-1)} aria-label="←"><IconChevronLeft size={18} /></ActionIcon>}
        <Text size="sm" className="zoom-cap">{[n > 1 ? `${s.at + 1} / ${n}` : '', it.caption, v.k > 1 ? `×${v.k.toFixed(1)}` : ''].filter(Boolean).join(' · ') || ' '}</Text>
        {n > 1 && <ActionIcon variant="default" onClick={() => go(1)} aria-label="→"><IconChevronRight size={18} /></ActionIcon>}
        <Tooltip label={t('web.zoom_tab')}><ActionIcon variant="default" component="a" href={it.src} target="_blank" rel="noreferrer" aria-label={t('web.zoom_tab')}><IconExternalLink size={16} /></ActionIcon></Tooltip>
        <Tooltip label={t('web.zoom_close')}><ActionIcon variant="default" onClick={() => setS(null)} aria-label={t('web.zoom_close')}><IconX size={18} /></ActionIcon></Tooltip>
      </div>
      <Text size="xs" className="zoom-help">{t('web.zoom_help')}</Text>
    </div>
  );
}
