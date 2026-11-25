// The app's three.js editors inside the new web UI: the shell's look on (forge.css) and its theme (?theme=light|dark).
(() => {
  const root = document.documentElement;
  root.dataset.sf3d = '1';
  root.dataset.theme = new URLSearchParams(location.search).get('theme') === 'light' ? 'light' : 'dark';
})();
