// Pictures of the write-up «Как не дать умной модели отдать неверный приказ?»: cards, a chart and a scheme as HTML, headless Edge.
//   node "docs/Solve problems/2026-11-26_voice-orders-gemma-locks/pictures.mjs"
// Writes src/<name>.html and src/<name>.png (2560x1440, clean), then img/<name>.png (1920 wide) through the sf3d conda Python.
// Every number here is from the game's research note Docs/Research/voice_commands.md §13 and Docs/PendingDecisions/voice_commands.md
// (branch claude/voice-commands-62e907, commit cbf160d0). No model was run for these pictures.
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

// 1. What Gemma made of misheard text (the recogniser's own words, in noise): its order and the one meant.
const cards = (rows) => rows.map(([heard, said, got, meant]) => `<div class="card"><div class="heard">Распознано: «${heard}»</div>
  <div class="said">Сказано было: «${said}»</div><div class="got">Gemma: <b>${got}</b> <span>а нужно: ${meant}</span></div></div>`).join("");
render("01_false_orders", page("Умная модель угадывает слишком охотно",
  "Распознаватель в шуме исказил фразу. Маленькая модель на этих фразах неверных приказов не дала, Gemma — дала.",
  `<div class="grid">${cards([
    ["и дневеровать врагов", "Игнорировать врагов", "в атаку", "не ввязываться"],
    ["Китай, гадушки вниз!", "Кидай горшки вниз!", "в атаку", "горшки"],
    ["Отставить с нему.", "Отставить стрельбу!", "не ввязываться", "не стрелять"],
    ["встоп не страдать свои.", "Стоп, не стрелять, свои!", "не ввязываться", "не стрелять"],
  ])}</div><div class="foot">8 неверных приказов на 321 распознанной фразе. У маленькой модели Qwen3.5-2B — 1.</div>`,
  `.grid{display:grid;grid-template-columns:1fr 1fr;gap:44px 56px}
   .card{background:#36363b;border-radius:18px;padding:36px 46px;border-left:10px solid #d0695a}
   .heard{font-size:50px;line-height:1.2}.said{font-size:32px;color:#a7abb3;margin:14px 0 18px}
   .got{font-size:40px;color:#d0695a}.got b{font-weight:600}.got span{color:#8fbf98;font-size:34px;margin-left:18px}`));

// 2. Three variants side by side: free phrases right, wrong orders on recognised text, right guesses on recognised text.
const v = [
  ["Qwen3.5-2B", "маленькая, было", 27, 1, 9, "#7d8590"],
  ["Gemma 4 E4B", "без защиты", 30, 8, 17, "#d0695a"],
  ["Gemma 4 E4B", "с замком по словам", 30, 1, 17, "#e0a43a"],
];
const col = (title, key, max, fmt) => `<div class="c"><div class="ct">${title}</div>` + v.map((r) =>
  `<div class="vr"><span class="vl"><b>${r[0]}</b><i>${r[1]}</i></span><span class="vb"><i style="width:${r[key] / max * 420}px;background:${r[5]}"></i><em>${fmt(r[key])}</em></span></div>`).join("") + `</div>`;
render("02_compare", page("Замок вернул ложные приказы к уровню маленькой модели",
  "Тот же стенд и те же тексты. Ноутбук с RTX 4060 Laptop, 8 ГБ.",
  `<div class="cols">${col("Свободные фразы: верно из 31", 2, 31, (x) => x)}${col("Неверных приказов на 321 распознанной фразе", 3, 8, (x) => x)}${col("Верных догадок по искажённому тексту", 4, 17, (x) => x)}</div>`,
  `.cols{display:grid;grid-template-columns:1fr 1fr 1fr;gap:70px}.ct{font-size:38px;color:#a7abb3;height:110px}
   .vr{margin-bottom:46px}.vl b{display:block;font-size:40px}.vl i{display:block;font-style:normal;font-size:30px;color:#8a8f98;margin-bottom:12px}
   .vb{display:flex;align-items:center}.vb i{display:block;height:56px;border-radius:6px;flex:none}.vb em{font-style:normal;font-size:46px;margin-left:20px}`));

// 3. The locks: the model proposes, the words of the heard text decide whether the order goes.
const rule = (w, r) => `<div class="rule"><b>${w}</b><span>${r}</span></div>`;
render("03_locks", page("Замок по словам: модель предлагает, игра решает",
  "Приказ модели проходит, только если слова в услышанном ему не противоречат. Иначе воин переспрашивает.",
  rule("«стоп», «отставить», «хватит», «прекратить»", "пропускают только «не стрелять»") +
  rule("«в атаку» рядом с «игнорировать», «не ввязываться», «мимо»", "не проходит") +
  rule("«в атаку» без слова рукопашной: руби, бей, режь, меч, вперёд, навались", "не проходит") +
  rule("«не стрелять» без слова остановки: не, стоп, опустить, ждите", "не проходит") +
  `<div class="ex">«и дневеровать врагов» → Gemma: в атаку → слова рукопашной нет → <b>Рагнар: «Что? Повторите приказ, десятник!»</b></div>`,
  `.rule{display:flex;justify-content:space-between;align-items:center;background:#36363b;border-radius:16px;padding:30px 44px;margin-bottom:26px}
   .rule b{font-size:42px;font-weight:600}.rule span{font-size:38px;color:#f0b44c}
   .ex{margin-top:46px;font-size:40px;color:#c9c6bf;border-left:10px solid #6fae7c;padding:24px 40px;background:#323a33;border-radius:12px}
   .ex b{color:#8fbf98;font-weight:600}`));

// 4. The siege with Gemma: what happened, and the video memory per process against the small model.
const mem = [["Игра в осаде", 2217, 2221, "#7d8590"], ["Распознавание GigaAM", 356, 356, "#5f8fa8"], ["Модель приказов", 3226, 1426, "#e0a43a"]];
render("04_siege_vram", page("Gemma в настоящей осаде",
  "Ноутбук с RTX 4060 Laptop, 8 ГБ. Видеопамять — счётчики Windows по каждому процессу.",
  `<div class="cols"><div class="col">
     <div class="ev ok"><b>«Стреляйте все разом»</b><i>залп за 0,79 с, все 10 на залпах</i></div>
     <div class="ev ok"><b>«Мой брат тоже был лучником»</b><i>не приказ, воин переспрашивает</i></div>
     <div class="ev stop"><b>«и дневеровать врагов»</b><i>Gemma: в атаку → замок остановил, десяток не ввязался в рукопашную</i></div>
     <div class="ev ok"><b>Прогрев после запуска</b><i>первый ответ 0,8 с вместо 1,7 с</i></div></div>
   <div class="col"><div class="mh">Видеопамять, ГБ: <span class="g">Gemma</span> против <span class="q">Qwen3.5-2B</span></div>` +
  mem.map(([n, g, q, c]) => `<div class="mr"><span>${n}</span>
     <span class="mb"><i style="width:${g / 3400 * 640}px;background:${c}"></i><em>${(g / 1000).toFixed(2).replace(".", ",")}</em></span>
     <span class="mb small"><i style="width:${q / 3400 * 640}px;background:#55575e"></i><em>${(q / 1000).toFixed(2).replace(".", ",")}</em></span></div>`).join("") +
  `<div class="tot">вместе ≈ 5,8 ГБ (было ≈ 4,0) из 8</div></div></div>`,
  `.cols{display:grid;grid-template-columns:1180px 1020px;gap:80px}.ev{background:#36363b;border-radius:18px;padding:28px 40px;margin-bottom:28px;border-left:10px solid #6fae7c}
   .ev.stop{border-left-color:#e0a43a}.ev b{display:block;font-size:46px;margin-bottom:10px}.ev i{display:block;font-style:normal;font-size:31px;color:#c9c6bf}
   .mh{font-size:38px;color:#a7abb3;margin-bottom:36px}.g{color:#f0b44c}.q{color:#9a9ca3}.mr{margin-bottom:34px}.mr>span:first-child{display:block;font-size:36px;margin-bottom:10px}
   .mb{display:flex;align-items:center;margin-bottom:8px}.mb i{display:block;height:48px;border-radius:6px;flex:none}.mb.small i{height:28px}
   .mb em{font-style:normal;font-size:38px;margin-left:20px}.mb.small em{font-size:30px;color:#9a9ca3}.tot{font-size:44px;color:#f0b44c;margin-top:24px}`));
