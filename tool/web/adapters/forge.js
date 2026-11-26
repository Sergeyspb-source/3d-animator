// The app's three.js editors inside the new web UI: the shell's look on (forge.css) and its theme (?theme=light|dark).
(() => {
  const root = document.documentElement;
  root.dataset.sf3d = '1';
  root.dataset.theme = new URLSearchParams(location.search).get('theme') === 'light' ? 'light' : 'dark';
})();

// The page's loads (models, textures) reported to the shell: its «Loading…» veil over this frame stays while any of
// them is in flight (sf3d-loading {n}). A load ends when its body has been read to the end (three's FileLoader reads
// it as a stream), or after a minute at the latest; «none» is said a moment after the last one, once it is drawn.
(() => {
  if (window.parent === window || !window.fetch) return;
  const HEAVY = /\.(glb|gltf|bin|png|jpe?g|webp|ktx2|hdr|exr|fbx)(\?|#|$)|\/file=|\/api\/file\?|^blob:/i;
  let n = 0, timer = 0;
  const inflight = new Map();   // (url → when: what still counts, for a look from the console)
  window.__sf3dLoads = inflight;
  const say = () => { try { parent.postMessage({ type: 'sf3d-loading', n }, location.origin); } catch (e) { /* (no parent page) */ } };
  const add = (d) => {
    n = Math.max(0, n + d);
    clearTimeout(timer);
    if (n > 0) say(); else timer = setTimeout(() => requestAnimationFrame(() => requestAnimationFrame(() => { say(); timer = setTimeout(say, 1000); })), 250);
  };   // («none» said twice: a shell that started listening late still hears it)
  window.addEventListener('load', () => { if (!n) add(0); });
  const f0 = window.fetch;
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || String(input || '');
    if (!HEAVY.test(url)) return f0.apply(this, arguments);
    add(1);
    const id = url + ' #' + Math.random().toString(36).slice(2, 6);
    inflight.set(id, Date.now());
    let done = false;
    const end = () => { if (!done) { done = true; clearTimeout(guard); inflight.delete(id); add(-1); } };
    const guard = setTimeout(end, 60000);
    return f0.apply(this, arguments).then((r) => {
      if (!r.body || !window.TransformStream || r.status < 200 || r.status > 599) { setTimeout(end, 0); return r; }   // (an opaque one cannot be rebuilt)
      const body = r.body.pipeThrough(new TransformStream({ flush() { end(); } }));
      const r2 = new Response(body, { status: r.status, statusText: r.statusText, headers: r.headers });
      Object.defineProperty(r2, 'url', { value: r.url });
      return r2;
    }, (e) => { end(); throw e; });
  };
})();
