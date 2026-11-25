// The procedural equipment editor inside the new web UI (served by tool/web/equip.py, the editor file untouched):
// - the shell says which step of the chain is shown (postMessage {type: 'sf3d-step', step}); the rail shows that part
//   (armour_editor.css). Looks = only hair, beard, brows, lashes; Workshop = everything else.
// - the editor tells the shell which piece is on (postMessage {type: 'sf3d-piece', piece, style, label}).
// Its requests still go through «the parent page's hidden field and button» (sendNow): the shell keeps both.
(() => {
  const q = new URLSearchParams(location.search);
  const HAIRY = ['hair', 'beard', 'brows', 'lashes'];
  const pieces = () => document.getElementById('pieces');
  const ready = () => { const m = document.getElementById('msg'); return !!m && m.hidden && !!pieces() && !!pieces().querySelector('button'); };
  const current = () => { const b = pieces() && pieces().querySelector('button.on'); return b ? b.dataset.piece : null; };
  const button = (sel) => pieces() && pieces().querySelector(sel);

  function tagBlocks() {   // a block's title gets the kind of the pieces under it (data-block="hair" for the hair's)
    for (const g of (pieces() ? pieces().querySelectorAll('.pgrp') : [])) {
      let n = g.nextElementSibling;
      while (n && !n.dataset.piece && !n.classList.contains('pgrp')) n = n.nextElementSibling;
      if (n && n.dataset.piece) g.dataset.block = HAIRY.includes(n.dataset.piece) ? 'hair' : 'other';
    }
  }
  let sent = '', lastEquip = null;
  function report() {
    const b = pieces() && pieces().querySelector('button.on');
    if (b && !HAIRY.includes(b.dataset.piece))
      lastEquip = `button[data-piece="${b.dataset.piece}"]` + (b.dataset.style ? `[data-style="${b.dataset.style}"]` : ':not([data-style])');
    const msg = { type: 'sf3d-piece', piece: b ? b.dataset.piece : null, style: b ? b.dataset.style || null : null, label: b ? b.textContent.trim() : '' };
    const key = JSON.stringify(msg);
    if (key !== sent && window.parent !== window) { sent = key; window.parent.postMessage(msg, location.origin); }
  }
  function fit() {   // the piece on fits the step: hair for Looks, not hair for the equipment's steps
    if (!ready()) return false;
    const step = document.body.dataset.step, c = current();
    if (step === 'look' && !HAIRY.includes(c)) { const b = button('button[data-piece="hair"]'); if (b) b.click(); }
    else if (step && step !== 'look' && HAIRY.includes(c)) {   // back to the piece worked on before Looks, else the first one
      const b = (lastEquip && button(lastEquip)) || button(HAIRY.map((h) => `:not([data-piece="${h}"])`).reduce((s, x) => s + x, 'button[data-piece]'));
      if (b) b.click();
    }
    return true;
  }
  function setStep(step) {
    document.body.dataset.step = step || 'workshop';
    tagBlocks();
    if (!fit()) { const t = setInterval(() => { if (fit()) clearInterval(t); }, 500); }
    report();
  }
  addEventListener('message', (e) => {
    if (e.origin === location.origin && e.data && e.data.type === 'sf3d-step') setStep(e.data.step);
  });
  const watch = () => {
    if (!pieces()) return setTimeout(watch, 200);
    new MutationObserver(() => { tagBlocks(); report(); }).observe(pieces(), { subtree: true, childList: true, attributes: true, attributeFilter: ['class'] });
  };
  watch();
  setStep(q.get('step'));
})();
