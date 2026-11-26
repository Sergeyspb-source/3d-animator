// One of the app's three.js editors in a frame, with the hidden fields it writes into on its parent page (by id,
// each a <textarea> inside an element of that id, as Gradio had them). The editor sets a field's value and sends an
// «input» event: a native listener passes it on (React's own onChange does not see a value set from outside).
import { useEffect, useRef } from 'react';
import { useT } from '../i18n';
import LoadingVeil, { useFrameLoading } from './LoadingVeil';

export function fieldValue(id: string): string {
  return document.querySelector<HTMLTextAreaElement>(`#${id} textarea`)?.value || '';
}

// go: the hidden buttons a page «clicks» after writing its request into a field (its id, that field's id, what to do)
export interface Go { id: string; field: string; onGo: (value: string) => void }

export default function EditorFrame({ src, fields = [], onField, title, allow, go = [] }:
  { src: string; fields?: string[]; onField?: (id: string, value: string) => void; title: string; allow?: string; go?: Go[] }) {
  const t = useT();
  const host = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLIFrameElement>(null);
  const loading = useFrameLoading(frame, src);
  const cb = useRef(onField);
  cb.current = onField;
  useEffect(() => {
    const off: (() => void)[] = [];
    for (const id of fields) {
      const ta = host.current?.querySelector<HTMLTextAreaElement>(`#${id} textarea`);
      if (!ta) continue;
      const h = () => cb.current?.(id, ta.value);
      ta.addEventListener('input', h);
      off.push(() => ta.removeEventListener('input', h));
    }
    return () => off.forEach((f) => f());
  }, [fields.join('|')]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      <div className="frame-box">
        <iframe ref={frame} key={src} src={src} className="equip-frame" title={title} allow={allow} />
        {loading && <LoadingVeil text={t('web.loading_model')} />}
      </div>
      <div ref={host} hidden>
        {fields.map((id) => <div key={id} id={id}><textarea defaultValue="" /></div>)}
        {go.map((g) => <button key={g.id} id={g.id} type="button" onClick={() => g.onGo(fieldValue(g.field))} />)}
      </div>
    </>
  );
}
