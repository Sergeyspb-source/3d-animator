// The procedural equipment editor inside the new web UI (served by tool/web/equip.py, the editor file untouched):
// - the shell says which step of the chain is shown (postMessage {type: 'sf3d-step', step}: the Workshop's tabs shape,
//   fit, materials; check; catalog / release, where the shell covers the editor; look); the rail shows that part
//   (armour_editor.css). Looks = only hair, beard, brows, lashes; the equipment = everything else.
// - the editor tells the shell which piece is on (postMessage {type: 'sf3d-piece', piece, style, label, item}) and
//   what its catalogue holds ({type: 'sf3d-catalog', blocks: [{title, hair, items: [{piece, style, label}]}]}).
// - the shell asks it to take a piece (sf3d-pick {piece, style}), to open one made before (sf3d-open {item}) and to
//   press one of its action buttons (sf3d-click {id}: generate, the fitting room, the check, the rebuild by layers).
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
    const name = document.getElementById('name');
    const msg = { type: 'sf3d-piece', piece: b ? b.dataset.piece : null, style: b ? b.dataset.style || null : null, label: b ? b.textContent.trim() : '',
      item: b && name ? name.value : '' };
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
  let catSent = '';
  function catalog() {   // the editor's own grid of pieces, by its blocks, for the shell's Catalog
    if (!ready()) return;
    const blocks = [];
    for (const el of pieces().children) {
      if (el.classList.contains('pgrp')) blocks.push({ title: el.textContent.trim(), hair: el.dataset.block === 'hair', items: [] });
      else if (el.dataset && el.dataset.piece && blocks.length)
        blocks[blocks.length - 1].items.push({ piece: el.dataset.piece, style: el.dataset.style || null, label: el.textContent.trim() });
    }
    const key = JSON.stringify(blocks);
    if (key !== catSent && window.parent !== window) { catSent = key; window.parent.postMessage({ type: 'sf3d-catalog', blocks }, location.origin); }
  }
  const ACTIONS = ['go', 'room', 'qa', 'qaHide', 'layersGo', 'bakeStop'];   // (the buttons the shell may press)
  function pick(piece, style) {
    const b = button(`button[data-piece="${piece}"]` + (style ? `[data-style="${style}"]` : ':not([data-style])')) || button(`button[data-piece="${piece}"]`);
    if (b && !b.classList.contains('on')) { b.click(); if (window.agHistReset) window.agHistReset(); }   // (a piece from the catalog: another object, its undo history anew)
    return !!b;
  }
  function openSaved(item) {   // one made before, from the editor's own list of them (an option «<item> — <kind>»)
    const sel = document.getElementById('saved');
    const o = sel && [...sel.options].find((x) => x.value !== '' && x.textContent.split(' — ')[0] === item);
    if (!o) return false;
    sel.value = o.value; sel.dispatchEvent(new Event('change'));
    return true;
  }
  function setStep(step) {
    document.body.dataset.step = step || 'shape';
    tagBlocks();
    if (!fit()) { const t = setInterval(() => { if (fit()) clearInterval(t); }, 500); }
    report();
  }
  addEventListener('message', (e) => {
    if (e.origin !== location.origin || !e.data) return;
    const d = e.data, later = (f) => { if (!f()) { const t = setInterval(() => { if (f()) clearInterval(t); }, 400); setTimeout(() => clearInterval(t), 60000); } };
    if (d.type === 'sf3d-step') setStep(d.step);
    else if (d.type === 'sf3d-pick') later(() => ready() && pick(d.piece, d.style));
    else if (d.type === 'sf3d-open') later(() => ready() && openSaved(d.item));
    else if (d.type === 'sf3d-click' && ACTIONS.includes(d.id)) { const b = document.getElementById(d.id); if (b && !b.disabled) b.click(); }
    else if (d.type === 'sf3d-hello') { sent = ''; catSent = ''; report(); catalog(); }   // (a shell that came later)
  });
  const watch = () => {
    if (!pieces()) return setTimeout(watch, 200);
    new MutationObserver(() => { tagBlocks(); report(); catalog(); }).observe(pieces(), { subtree: true, childList: true, attributes: true, attributeFilter: ['class'] });
    const nm = document.getElementById('name');   // (the item's name follows the piece and its style)
    if (nm) new MutationObserver(report).observe(nm, { attributes: true });
    setInterval(() => { report(); catalog(); }, 1500);   // (the name is set as a value, which no observer sees)
  };
  watch();
  setStep(q.get('step'));
})();
