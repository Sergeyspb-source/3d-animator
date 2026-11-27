// Pictures of the write-up «Где думает ИИ: на своей видеокарте или в интернете?».
//   node "docs/Solve problems/2026-11-26_ai-source-setting/pictures.mjs"
// src/ai_tab_*.png are the game's own frames (ai_tab_shot.gd, see case.json -> regenerate); this script makes img/ from them
// (1920 wide, a sheet through _tools/sheet.py) and draws the OpenCode / OpenRouter chart as HTML through headless Edge (2560x1440).
// The numbers are from the game's research note Docs/Research/ai_dialogues_ru_review.md §15–15.2.
import { writeFileSync, mkdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const PY = "D:/conda/envs/sf3d/python.exe";
const SHEET = join(here, "..", "_tools", "sheet.py");
mkdirSync(join(here, "img"), { recursive: true });
const shrink = (src, out) => execFileSync(PY, ["-c", `from PIL import Image\nim=Image.open(r'''${src}''').convert('RGB')\n` +
  `im.resize((1920,1080), Image.LANCZOS).save(r'''${out}''', optimize=True)`]);

// 1. The tab with OpenRouter chosen; 2. the other two sources side by side.
shrink(join(here, "src", "ai_tab_openrouter.png"), join(here, "img", "01_ai_tab_openrouter.png"));
execFileSync(PY, [SHEET, join(here, "img", "02_local_and_opencode.png"),
  "Своя видеокарта: ключ не нужен", join(here, "src", "ai_tab_local.png"),
  "OpenCode Go: ключа нет, предупреждение", join(here, "src", "ai_tab_opencode_go.png"), "--cols", "2", "--width", "1920", "--crop"]);

// 3. The same model through the OpenCode agent and straight through OpenRouter.
const rows = [
  ["Оценка речи из 5", 4.74, 4.79, (v) => v.toFixed(2).replace(".", ","), 5],
  ["Токенов на входе одной реплики", 6400, 1300, (v) => `${(v / 1000).toFixed(1).replace(".", ",")} тыс.`, 6400],
  ["Время ответа, медиана", 2.39, 1.32, (v) => `${v.toFixed(2).replace(".", ",")} с`, 2.39],
  ["Цена одной реплики", 0.00037, 0.00012, (v) => `$${v.toFixed(5).replace(".", ",")}`, 0.00037],
];
const html = `<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;width:2560px;height:1440px;background:#2b2b2f;color:#ece8df;font-family:"Segoe UI",Arial,sans-serif;overflow:hidden}
.wrap{padding:96px 140px}h1{font-size:76px;font-weight:600;margin:0 0 18px;color:#f0b44c}.sub{font-size:38px;color:#a7abb3;margin:0 0 56px}
.g{display:grid;grid-template-columns:720px 1fr;align-items:center;margin-bottom:44px}.l{font-size:44px}
.b{height:50px;border-radius:6px;margin:6px 0;position:relative}.b span{position:absolute;left:calc(100% + 22px);top:0;font-size:38px;white-space:nowrap}
.oc{background:#7d8590}.or{background:#e0a43a}
.legend{margin-top:30px;font-size:34px;color:#c9c6bf}.sw{display:inline-block;width:46px;height:28px;border-radius:4px;margin:0 14px 0 40px;vertical-align:-4px}
.legend .sw:first-child{margin-left:0}.note{margin-top:26px;font-size:32px;color:#8a8f98}
</style></head><body><div class="wrap"><h1>Одна и та же DeepSeek V4.1 Flash, два пути</h1>
<div class="sub">90 реплик тех же 11 сцен. Через агента OpenCode к каждой реплике прибавляются его собственные инструкции.</div>
${rows.map(([label, oc, or, fmt, max]) => `<div class="g"><div class="l">${label}</div><div>
<div class="b oc" style="width:${(oc / max) * 1150}px"><span>${fmt(oc)}</span></div>
<div class="b or" style="width:${(or / max) * 1150}px"><span>${fmt(or)}</span></div></div></div>`).join("")}
<div class="legend"><span class="sw oc"></span>через OpenCode Go (подписка) <span class="sw or"></span>напрямую через OpenRouter</div>
<div class="note">Цена у OpenCode Go — доля оплаченного месячного лимита, у OpenRouter — деньги с баланса.</div>
</div></body></html>`;
const htmlPath = join(here, "src", "03_opencode_vs_openrouter.html");
const pngPath = join(here, "src", "03_opencode_vs_openrouter.png");
writeFileSync(htmlPath, html);
execFileSync(EDGE, ["--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1", "--window-size=2560,1440",
  `--screenshot=${pngPath}`, pathToFileURL(htmlPath).href], { stdio: "ignore" });
shrink(pngPath, join(here, "img", "03_opencode_vs_openrouter.png"));
console.log("made img/01..03");
