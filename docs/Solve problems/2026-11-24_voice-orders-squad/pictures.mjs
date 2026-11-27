// Pictures of the write-up «Можно ли командовать десятком голосом?»: a scheme, charts and cards as HTML, rendered by headless Edge.
//   node "docs/Solve problems/2026-11-24_voice-orders-squad/pictures.mjs"
// Writes src/<name>.html and src/<name>.png (2560x1440, clean), then img/<name>.png (1920 wide) through the sf3d conda Python.
// Every number here is from the game's research note Docs/Research/voice_commands.md (§4, §5, §6, §11, §12), branch
// claude/voice-commands-62e907. No model was run for these pictures.
import { writeFileSync, mkdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const PY = "D:/conda/envs/sf3d/python.exe";
mkdirSync(join(here, "src"), { recursive: true });
mkdirSync(join(here, "img"), { recursive: true });

const page = (title, sub, body, extra = "") => `<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;width:2560px;height:1440px;background:#2b2b2f;color:#ece8df;font-family:"Segoe UI",Arial,sans-serif;overflow:hidden}
.wrap{padding:96px 140px}
h1{font-size:76px;font-weight:600;margin:0 0 18px;color:#f0b44c}
.sub{font-size:38px;color:#a7abb3;margin:0 0 64px}
.foot{position:absolute;left:140px;bottom:64px;font-size:30px;color:#8a8f98}
${extra}</style></head><body><div class="wrap"><h1>${title}</h1><div class="sub">${sub}</div>${body}</div></body></html>`;

function render(name, html) {
  const htmlPath = join(here, "src", `${name}.html`);
  const pngPath = join(here, "src", `${name}.png`);
  writeFileSync(htmlPath, html);
  execFileSync(EDGE, ["--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
    "--window-size=2560,1440", `--screenshot=${pngPath}`, pathToFileURL(htmlPath).href], { stdio: "ignore" });
  execFileSync(PY, ["-c", `from PIL import Image\nim=Image.open(r'''${pngPath}''').convert('RGB')\n` +
    `im.resize((1920,1080), Image.LANCZOS).save(r'''${join(here, "img", name + ".png")}''', optimize=True)`]);
  console.log("made", name);
}

// 1. The chain: the key, the microphone, the recogniser, the phrase list, the order; the LLM only when the list found nothing.
const box = (t, s, c = "#3a3a40") => `<div class="box" style="background:${c}"><b>${t}</b><i>${s}</i></div>`;
render("01_chain", page("Как голос становится приказом",
  "Тот же приказ, что и колесо T или клавиши Ctrl+1…8. Всё работает на этом компьютере, без интернета.",
  `<div class="row">${box("Держишь B", "микрофон открыт, пока клавиша зажата")}<span class="ar">→</span>
   ${box("GigaAM", "речь → текст, ~0,11 с на видеокарте")}<span class="ar">→</span>
   ${box("Список фраз", "«за мной», «залп», «по местам»… ~1 мс")}<span class="ar">→</span>
   ${box("Десяток", "тот же приказ, что из колеса", "#4a5a3c")}</div>
   <div class="down"><span class="ar2">↓ ничего не нашёл, 2+ слова</span></div>
   <div class="row r2">${box("LLM", "«Стреляйте все разом» → залп, «по смыслу»", "#5a4a32")}<span class="ar">→</span>
   ${box("Ничего не понятно", "приказа нет, «Десяток не понял»", "#5a3a36")}</div>
   <div class="foot">Говорит стражник в колонках во время записи — фраза выбрасывается: его ответы повторяют слова приказов.</div>`,
  `.row{display:flex;align-items:center;gap:26px}.r2{margin-left:1120px}
   .box{border-radius:20px;padding:34px 38px;width:470px;min-height:190px}.box b{display:block;font-size:52px;margin-bottom:14px}
   .box i{display:block;font-style:normal;font-size:32px;color:#c9c6bf;line-height:1.3}.ar{font-size:70px;color:#f0b44c}
   .down{margin:30px 0 30px 1260px}.ar2{font-size:38px;color:#f0b44c}`));

// 2. The recognisers: Russian phrases right and the wait after the key is let go (median), RTX 4060 Laptop.
const engines = [
  ["GigaAM v3, видеокарта", "только русский · 99 из 105", 99, 105, 113, true],
  ["Whisper small, видеокарта, с подсказкой", "русский и английский · 98 из 105", 98, 105, 265],
  ["Whisper small, видеокарта, без подсказки", "90 из 105", 90, 105, 246],
  ["GigaAM v3, процессор, 2 потока", "один голос · 32 из 35", 32, 35, 314],
  ["Whisper small, процессор, 4 потока", "один голос · 31 из 35", 31, 35, 2914],
];
render("02_engines", page("Какой распознаватель речи взять",
  "Русские фразы-приказы, синтезированные голоса. Слева — доля понятых верно, справа — сколько ждать после отпускания клавиши.",
  `<div class="head"><span></span><span>понято верно</span><span>ожидание, медиана</span></div>` +
  engines.map(([m, n, ok, of, ms, best]) => `<div class="r${best ? " best" : ""}"><span class="m">${m}<i>${n}</i></span>
    <span class="b"><i style="width:${(ok / of) * 560}px"></i><em>${Math.round(ok / of * 100)} %</em></span>
    <span class="b t"><i style="width:${Math.min(ms, 3000) / 3000 * 480}px"></i><em>${ms >= 1000 ? (ms / 1000).toFixed(1).replace(".", ",") + " с" : ms + " мс"}</em></span></div>`).join(""),
  `.head,.r{display:grid;grid-template-columns:900px 740px 640px;align-items:center}
   .head{font-size:30px;color:#8a8f98;margin-bottom:14px}.r{font-size:42px;min-height:150px;border-top:1px solid #3c3c42}
   .m i{display:block;font-style:normal;font-size:28px;color:#8a8f98}
   .b{display:flex;align-items:center;height:56px}.b i{display:block;height:56px;background:#7d8590;border-radius:6px;flex:none}
   .b em{font-style:normal;padding-left:20px}.t i{background:#5f8fa8}.best .m{color:#f0b44c;font-weight:600}.best .b i{background:#e0a43a}`));

// 3. Single words: what the recognisers wrote for one-word orders (raw answers of the bench).
const cards = (rows) => rows.map(([said, heard, note]) => `<div class="card"><div class="who">Сказано: «${said}»</div>
  <div class="line">${heard}</div><div class="note">${note}</div></div>`).join("");
render("03_single_words", page("Короткий приказ — лёгкая ошибка",
  "Что распознаватели услышали в односложных приказах. Фразы из двух и больше слов держатся даже в шуме.",
  `<div class="grid">${cards([
    ["Пли!", "«Блин» · «Привет» · «Филипп»", "0 из 6 — ни один движок. Слово убрано, вместо него «Огонь!» и «Стреляй!»"],
    ["Залп!", "«Зал» · «Зуб» · «Зап»", "Хвост слова потерялся — и это уже другое слово."],
    ["Бомбы!", "«Бомбой» · «Томбы» · «Бомби»", ""],
    ["Бей их!", "«Би их» · «Беги»", "«Беги» — уже совсем другой приказ."],
  ])}</div>`,
  `.grid{display:grid;grid-template-columns:1fr 1fr;gap:44px 56px}
   .card{background:#36363b;border-radius:18px;padding:38px 46px;border-left:10px solid #d0695a}
   .who{font-size:36px;color:#d0695a;font-weight:600;margin-bottom:12px}.line{font-size:56px;line-height:1.25}
   .note{font-size:30px;color:#a7abb3;margin-top:16px}`));

// 4. The siege: what happened and the video memory per process.
const mem = [["Игра в осаде", 2221, "#7d8590"], ["Распознавание GigaAM", 356, "#5f8fa8"], ["LLM Qwen3.5-2B", 1426, "#e0a43a"]];
render("04_siege", page("Проверка в настоящей осаде",
  "Записанные фразы подаются тем же путём, что и голос с микрофона. Ноутбук с RTX 4060 Laptop, 8 ГБ.",
  `<div class="cols"><div class="col">
     <div class="ev ok"><b>«Десяток, за мной!»</b><i>все 10 воинов идут за героем · 0,5 с первая фраза, 0,2 с следующие</i></div>
     <div class="ev ok"><b>«Огонь в очаге почти погас»</b><i>приказа нет: «Десяток не понял»</i></div>
     <div class="ev ok"><b>«Стреляйте все разом»</b><i>LLM: залп за 0,4 с, все 10 на залпах, «по смыслу»</i></div>
     <div class="ev ok"><b>«Мой брат тоже был лучником»</b><i>LLM: не приказ</i></div></div>
   <div class="col"><div class="mh">Видеопамять по процессам</div>` +
  mem.map(([n, mb, c]) => `<div class="mr"><span>${n}</span><span class="mb"><i style="width:${mb / 2300 * 700}px;background:${c}"></i><em>${(mb / 1000).toFixed(2).replace(".", ",")} ГБ</em></span></div>`).join("") +
  `<div class="tot">вместе ≈ 4,0 ГБ из 8</div></div></div>`,
  `.cols{display:grid;grid-template-columns:1200px 1000px;gap:80px}.ev{background:#36363b;border-radius:18px;padding:30px 40px;margin-bottom:30px;border-left:10px solid #6fae7c}
   .ev b{display:block;font-size:48px;margin-bottom:10px}.ev i{display:block;font-style:normal;font-size:32px;color:#c9c6bf}
   .mh{font-size:40px;color:#a7abb3;margin-bottom:40px}.mr{margin-bottom:40px}.mr span{display:block;font-size:38px;margin-bottom:12px}
   .mb{position:relative;height:56px}.mb i{display:inline-block;height:56px;border-radius:6px;vertical-align:middle}
   .mb em{font-style:normal;font-size:40px;margin-left:22px;vertical-align:middle}.tot{font-size:46px;color:#f0b44c;margin-top:30px}`));
