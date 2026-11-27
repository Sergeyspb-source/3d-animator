// Pictures of the write-up «Могут ли жители игры разговаривать через ИИ?»: charts and line cards as HTML, rendered by headless Edge.
//   node "docs/Solve problems/2026-11-25_npc-dialogue-models/pictures.mjs"
// Writes src/<name>.html and src/<name>.png (2560x1440, clean), then img/<name>.png (1920 wide) through the sf3d conda Python.
// Every number here is from the game's research note Docs/Research/ai_dialogues_ru_review.md (§3, §7, §13–15.3).
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

// 1. The ladder: how the score of the residents' speech grew, total and facts.
const ladder = [
  ["Qwen3.5-2B", "на своей видеокарте, первые правила", 1.82, 1.3],
  ["Qwen3.5-4B", "на своей видеокарте, первые правила", 3.38, 2.8],
  ["Gemma 4 E4B", "на своей видеокарте, без подсказок игры", 4.14, 4.0],
  ["Gemma 4 E4B", "на своей видеокарте, ходы и память от игры", 4.30, 4.6],
  ["DeepSeek V4.1 Flash", "через интернет, ходы и память от игры", 4.79, 4.8],
];
const bar = (v, cls) => `<div class="bar ${cls}" style="width:${(v / 5) * 1180}px"><span>${v.toFixed(cls === "tot" ? 2 : 1).replace(".", ",")}</span></div>`;
render("01_score_ladder", page("Как росла оценка речи жителей",
  "Средняя оценка из 5: 11 сцен, 90 реплик на каждый вариант. Оценки мои, по чтению всех реплик.",
  ladder.map(([m, how, tot, fact]) => `<div class="row"><div class="lab"><b>${m}</b><i>${how}</i></div>
    <div class="bars">${bar(tot, "tot")}${bar(fact, "fact")}</div></div>`).join("") +
  `<div class="legend"><span class="sw tot"></span>общая оценка <span class="sw fact"></span>факты: нет выдуманных смертей, ран и чисел</div>`,
  `.row{display:flex;align-items:center;margin:0 0 34px}.lab{width:880px}.lab b{display:block;font-size:46px;font-weight:600}
   .lab i{display:block;font-style:normal;font-size:32px;color:#a7abb3}.bars{flex:1}
   .bar{height:50px;border-radius:6px;margin:6px 0;position:relative}.bar span{position:absolute;left:calc(100% + 22px);top:2px;font-size:38px}
   .tot{background:#e0a43a}.fact{background:#5f8fa8;height:34px}.fact span{font-size:32px;top:-4px;color:#bcd3df}
   .legend{margin-top:40px;font-size:34px;color:#c9c6bf}.sw{display:inline-block;width:46px;height:28px;border-radius:4px;margin:0 14px 0 40px;vertical-align:-4px}
   .legend .sw:first-child{margin-left:0}`));

// 2 and 3. Line cards: the worst lines of the small models and the best ones with the game's help.
const cards = (rows) => rows.map(([who, line, note]) => `<div class="card"><div class="who">${who}</div>
  <div class="line">«${line}»</div><div class="note">${note}</div></div>`).join("");
const cardCss = `.grid{display:grid;grid-template-columns:1fr 1fr;gap:40px 56px}
  .card{background:#36363b;border-radius:18px;padding:34px 44px;border-left:10px solid var(--c)}
  .who{font-size:34px;color:var(--c);font-weight:600;margin-bottom:10px}.line{font-size:46px;line-height:1.25}
  .note{font-size:30px;color:#a7abb3;margin-top:14px}`;
render("02_bad_lines", page("Что говорили жители без помощи игры",
  "Каждую реплику пишет модель за своего персонажа. Маленькие модели путают факты и слова.",
  `<div class="grid">${cards([
    ["Ульф, лучник", "Сигвард же погиб на стене!", "Qwen3.5-4B. Сигвард жив и стоит в десятке."],
    ["Сигвард, ветеран", "Ульфу снесло плечо. Это факт. Не спорь со мной.", "Qwen3.5-4B. У Ульфа лёгкий порез, и «факт» — слово не из этого мира."],
    ["Сотник", "Я иду к сотнику сдавать опыт за убийство.", "Qwen3.5-4B. Сотник забыл, что он и есть сотник."],
    ["Сотник", "Смерть коня есть. Не трогайте мой дом.", "Qwen3.5-2B. Бессмыслица посреди приказа."],
    ["Эдгар, балагур", "Давай с Любавой поиграем в шашлыки", "Qwen3.5-2B. Шашлыки и бессмыслица."],
  ])}</div>`, cardCss.replace(/var\(--c\)/g, "#d0695a")));
render("03_good_lines", page("Что они говорят, когда ход и факты даёт игра",
  "Игра решает, что сказать и какие факты знает говорящий. Модель только подбирает слова.",
  `<div class="grid">${cards([
    ["Любава, торговка", "Молочница шептала, что ночью у южной мельницы будто бы нурглы видели!", "Gemma 4 E4B. Слух остался слухом, источник назван."],
    ["Сыч, нищий у ворот", "Не знаю я, что там у мельницы видели, баба. Надо слушать лес, а не слухи.", "Gemma 4 E4B. Не выдумывает того, чего не знает."],
    ["Ждан, трактирщик", "Молва да мельница — обе мелят, да не в муку.", "DeepSeek V4.1 Flash. Своя поговорка к слуху про мельницу."],
    ["Сотник", "И не зови меня сынком, лекарь.", "DeepSeek V4.1 Flash. Ответ на присказку Маркуса «сынок»."],
    ["Сигвард, ветеран", "Помню. Скажу сотнику — но за него не решаю.", "DeepSeek V4.1 Flash. Коротко, как в его карточке."],
  ])}</div>`, cardCss.replace(/var\(--c\)/g, "#6fae7c")));

// 4. Cheap models at DeepSeek's price, same scheme, 90 lines each.
const cheap = [
  ["DeepSeek V4.1 Flash", 4.79, "$0,00012", "1,32 с", true],
  ["Gemma 4 26B", 4.34, "$0,00009", "0,77 с"],
  ["Claude Haiku 5.5", 4.31, "$0,00020", "1,03 с"],
  ["Gemma 4 E4B, своя видеокарта", 4.30, "бесплатно", "0,8 с"],
  ["Tencent HY4 Flash", 4.16, "$0,00007", "1,06 с"],
  ["Gemini 2.5 Flash Lite", 4.12, "$0,00012", "0,52 с"],
  ["Qwen3.7 Flash", 3.97, "$0,00003", "1,16 с"],
];
render("04_cheap_models", page("Дешёвые модели через интернет против DeepSeek",
  "Те же 11 сцен, ходы и память от игры. Цена — за одну реплику, время — медиана ответа.",
  `<div class="head"><span></span><span>оценка из 5</span><span>цена реплики</span><span>время</span></div>` +
  cheap.map(([m, s, p, t, best]) => `<div class="r${best ? " best" : ""}"><span class="m">${m}</span>
    <span class="b"><i style="width:${(s / 5) * 900}px"></i><em>${s.toFixed(2).replace(".", ",")}</em></span>
    <span class="p">${p}</span><span class="t">${t}</span></div>`).join(""),
  `.head,.r{display:grid;grid-template-columns:760px 1000px 300px 220px;align-items:center}
   .head{font-size:30px;color:#8a8f98;margin-bottom:14px}.r{font-size:42px;height:104px;border-top:1px solid #3c3c42}
   .b{position:relative;height:50px}.b i{display:block;height:50px;background:#7d8590;border-radius:6px}
   .b em{position:absolute;left:0;top:0;line-height:50px;font-style:normal;padding-left:20px;color:#1d1d20;font-weight:600}
   .best .m{color:#f0b44c;font-weight:600}.best .b i{background:#e0a43a}.p,.t{color:#c9c6bf}`));
