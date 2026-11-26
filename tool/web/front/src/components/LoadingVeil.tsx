// «Loading…» in the middle of a 3D view or an editor while its model comes: the stage dimmed under a spinner and a
// line (with the per cent when it is known). Editors' pages report their loads themselves (adapters/forge.js:
// sf3d-loading messages, the files in flight); useFrameLoading turns them into this veil for their frame.
import { useEffect, useState, type RefObject } from 'react';
import { Loader, Text } from '@mantine/core';

export default function LoadingVeil({ text, pct }: { text: string; pct?: number | null }) {
  return (
    <div className="loading-veil" role="status" aria-live="polite">
      <div className="loading-veil-box">
        <Loader size="md" />
        <Text size="sm" fw={500}>{text}{pct != null ? ` ${pct} %` : ''}</Text>
      </div>
    </div>
  );
}

// an editor frame is loading from the moment its page is asked for until it has its model: until its own page says
// nothing is in flight any more (or, a page that never reports, a moment after it loaded)
export function useFrameLoading(frame: RefObject<HTMLIFrameElement>, src: string | null) {
  const [loading, setLoading] = useState(!!src);
  useEffect(() => {
    setLoading(!!src);
    if (!src) return;
    let reported = false, quiet = 0;
    const el = frame.current;
    const onMsg = (e: MessageEvent) => {
      if (e.origin !== location.origin || e.data?.type !== 'sf3d-loading' || e.source !== frame.current?.contentWindow) return;
      reported = true;
      window.clearTimeout(quiet);
      setLoading(e.data.n > 0);
    };
    const onLoad = () => { quiet = window.setTimeout(() => { if (!reported) setLoading(false); }, 1200); };
    window.addEventListener('message', onMsg);
    el?.addEventListener('load', onLoad);
    try { if (el?.contentDocument?.readyState === 'complete' && el.contentWindow?.location.href !== 'about:blank') onLoad(); } catch { /* (another origin) */ }
    const cap = window.setTimeout(() => setLoading(false), 120000);   // (never forever: a page that stopped reporting)
    return () => { window.removeEventListener('message', onMsg); el?.removeEventListener('load', onLoad); window.clearTimeout(quiet); window.clearTimeout(cap); };
  }, [frame, src]);
  return loading;
}
