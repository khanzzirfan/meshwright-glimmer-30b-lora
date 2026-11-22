// Compose Meshwright v1 promo images from the studio renders (scripts/showcase_render.mjs).
// usage: node release/v1/promo/make.mjs   (run from the repo root; offline, system fonts only)
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const DIR = path.resolve("release/v1/promo");
const OUT = path.join(DIR, "out");
fs.mkdirSync(OUT, { recursive: true });
const meta = JSON.parse(fs.readFileSync(path.join(DIR, "meta.json"), "utf8"));
const img = (id) => "file://" + path.join(DIR, "renders", `${id}.png`);
const OLLAMA = "ollama run khanzz_irfan/meshwright-glimmer-30b-lora:v1";

// --slides switches the script to the 16:9 hero slides (docs/15, promo-1 US-004) and writes only those; a plain
// run keeps every existing out/ image byte-identical. --slides-file and --out default to release/v1/promo.
const argv = process.argv.slice(2);
const opt = (n, d) => { const i = argv.indexOf("--" + n); return i > -1 ? argv[i + 1] : d; };
const SLIDES_MODE = argv.includes("--slides");
const ENDCARD_MODE = argv.includes("--endcard");

const FONT = `font-family:'Avenir Next','SF Pro Display',-apple-system,Helvetica,sans-serif;`;
const MONO = `font-family:'SF Mono',Menlo,monospace;`;
const base = `*{box-sizing:border-box;margin:0}body{${FONT}-webkit-font-smoothing:antialiased}`;

// dark studio backdrop with a soft spotlight and a faint floor grid
const dark = `background:radial-gradient(ellipse 70% 60% at 62% 58%,#2b3a63 0%,#151c33 55%,#0b0f1e 100%);color:#eef2ff;`;
const gridFloor = (h) => `<div style="position:absolute;left:0;right:0;bottom:0;height:${h}px;
  background-image:linear-gradient(rgba(140,170,255,.10) 1px,transparent 1px),linear-gradient(90deg,rgba(140,170,255,.10) 1px,transparent 1px);
  background-size:48px 48px;transform:perspective(500px) rotateX(58deg);transform-origin:bottom;
  -webkit-mask-image:linear-gradient(to top,#000 10%,transparent 90%)"></div>`;
const chip = (t) => `<span style="display:inline-block;padding:7px 14px;border-radius:999px;border:1px solid rgba(170,190,255,.35);
  background:rgba(120,140,255,.10);font-size:15px;font-weight:600;letter-spacing:.2px;margin:0 8px 8px 0">${t}</span>`;
const place = (id, x, y, h, extra = "") => `<img src="${img(id)}" style="position:absolute;left:${x}px;top:${y}px;height:${h}px;
  filter:drop-shadow(0 18px 22px rgba(0,0,0,.45));${extra}">`;

const pages = {
  // 1280x640: GitHub social preview and HF / blog banner
  "cover_1280x640.png": [1280, 640, `
  <div style="position:relative;width:1280px;height:640px;overflow:hidden;${dark}">
    ${gridFloor(300)}
    <div style="position:absolute;left:64px;top:92px;width:520px">
      <div style="font-size:15px;font-weight:700;letter-spacing:3px;color:#9fb3ff">TEXT → 3D GAME ASSETS</div>
      <div style="font-size:84px;font-weight:800;letter-spacing:-2px;line-height:1;margin:14px 0 18px">Meshwright</div>
      <div style="font-size:26px;line-height:1.3;color:#cfd8ff;margin-bottom:26px">Describe a prop. Get a low-poly,<br>game-ready <b style="color:#fff">GLB</b> in about a minute.</div>
      ${chip("Godot · Unity · Blender")}${chip("Animated GLBs")}${chip("Runs locally · Ollama")}
      <div style="${MONO}font-size:14px;color:#9fb3ff;margin-top:22px;opacity:.9">$ ${OLLAMA}</div>
    </div>
    ${place("x0458", 1060, 150, 120)}${place("g023", 930, 92, 210)}${place("x0022", 630, 96, 205)}
    ${place("x0422", 1110, 300, 235)}${place("x0110", 650, 352, 175)}${place("x0455", 830, 372, 165)}
    ${place("x0092", 1010, 440, 120)}
    <div style="position:absolute;right:28px;bottom:18px;font-size:13px;color:#8d9bd0">v1 · Built on Muse Glimmer 30B · Apache 2.0</div>
  </div>`],

  // 1080x1080: X / LinkedIn / Instagram square
  "social_1080.png": [1080, 1080, `
  <div style="position:relative;width:1080px;height:1080px;overflow:hidden;${dark}">
    ${gridFloor(520)}
    <div style="position:absolute;top:70px;width:100%;text-align:center">
      <div style="font-size:18px;font-weight:700;letter-spacing:4px;color:#9fb3ff">TEXT → 3D GAME ASSETS</div>
      <div style="font-size:104px;font-weight:800;letter-spacing:-3px;margin-top:10px">Meshwright</div>
      <div style="font-size:30px;color:#cfd8ff;margin-top:6px">One sentence in. A game-ready GLB out.</div>
    </div>
    ${place("x0022", 70, 360, 240)}${place("x0458", 400, 420, 170)}${place("x0422", 770, 330, 290)}
    ${place("x0110", 90, 650, 220)}${place("g023", 350, 610, 260)}${place("x0455", 560, 690, 190)}${place("x0092", 840, 700, 160)}
    <div style="position:absolute;bottom:42px;width:100%;text-align:center">
      <div style="${MONO}display:inline-block;font-size:21px;padding:14px 26px;border-radius:14px;background:rgba(10,14,30,.75);border:1px solid rgba(170,190,255,.3)">$ ${OLLAMA}</div>
      <div style="font-size:16px;color:#8d9bd0;margin-top:14px">Free and open · Apache 2.0 · Built on Muse Glimmer 30B</div>
    </div>
  </div>`],
};

// showcase grid: every tile shows the exact prompt it came from
const gridIds = ["x0022","g023","x0186","x0422","x0110","x0455","g011","x0092","x0047","x0458","x0265","x0184",
                 "x0005","x0054","x0336","x0461","x0139","g029","x0195","x0091","x0419","x0024","x0316","x0170"];
const COLS = 6, TW = 380, TH = 420;
pages["showcase_grid.png"] = [COLS * TW + 120, Math.ceil(gridIds.length / COLS) * TH + 230, `
  <div style="background:#f4f2ee;padding:60px;color:#1b2033">
    <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:30px">
      <div><div style="font-size:56px;font-weight:800;letter-spacing:-1.5px">Meshwright v1</div>
        <div style="font-size:24px;color:#59607a;margin-top:4px">Every asset below came from the one-line prompt under it. No manual edits.</div></div>
      <div style="${MONO}font-size:17px;color:#3a4266;text-align:right">${OLLAMA}<br><span style="${FONT}color:#8a8fa3">curated from 511 generated assets</span></div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(${COLS},${TW}px)">
      ${gridIds.map((id) => `<div style="height:${TH}px;padding:10px">
        <div style="height:100%;background:linear-gradient(180deg,#fff 0%,#eceef4 100%);border-radius:22px;padding:14px;display:flex;flex-direction:column;box-shadow:0 2px 10px rgba(30,40,80,.08)">
          <div style="flex:1;display:flex;align-items:center;justify-content:center;min-height:0"><img src="${img(id)}" style="max-width:100%;max-height:100%"></div>
          <div style="font-size:15px;line-height:1.35;color:#3a4266;height:62px;overflow:hidden">“${meta[id].prompt}”</div>
        </div></div>`).join("")}
    </div>
  </div>`];

// how it works: prompt -> generated page with Export GLB -> the GLB
const EX = "x0022";
const shot = "file://" + path.resolve(`runs/imp/distill/${EX}/attempts/1/shots/asset.png`);
const step = (n, t) => `<div style="font-size:15px;font-weight:700;letter-spacing:2px;color:#9fb3ff;margin-bottom:14px">${n} · ${t}</div>`;
const arrow = `<div style="font-size:54px;color:#6f80c9;align-self:center;padding:0 18px">→</div>`;
pages["how_it_works_1600x640.png"] = [1600, 640, `
  <div style="width:1600px;height:640px;${dark}padding:56px 60px;display:flex;flex-direction:column">
    <div style="font-size:40px;font-weight:800;margin-bottom:34px">From one sentence to a GLB file</div>
    <div style="display:flex;flex:1;min-height:0">
      <div style="width:380px">${step(1, "PROMPT")}
        <div style="background:rgba(10,14,30,.7);border:1px solid rgba(170,190,255,.3);border-radius:16px;padding:22px;font-size:24px;line-height:1.4">${meta[EX].prompt}</div>
        <div style="font-size:16px;color:#8d9bd0;margin-top:16px">Static, animated or a small set.</div></div>
      ${arrow}
      <div style="width:470px">${step(2, "THREE.JS PAGE")}
        <img src="${shot}" style="width:470px;border-radius:14px;border:1px solid rgba(170,190,255,.3)">
        <div style="font-size:16px;color:#8d9bd0;margin-top:12px">Named parts, live preview, an Export GLB button.</div></div>
      ${arrow}
      <div style="width:420px;position:relative">${step(3, "GAME-READY GLB")}
        <img src="${img(EX)}" style="width:360px;margin-left:20px;filter:drop-shadow(0 18px 22px rgba(0,0,0,.45))">
        <div style="font-size:16px;color:#8d9bd0;margin-top:0">Grounded at y = 0, real-world scale.<br>Opens in Godot, Unity and Blender.</div></div>
    </div>
  </div>`];

// One slide: left column (kicker chip, two headline lines, rule, sub, quoted prompt) and the trimmed image on
// the right with an optional caption, plus the counter and the wordmark.
function slidePage(s, n, total, imageBase) {
  const src = "file://" + (path.isAbsolute(s.image) ? s.image : path.join(imageBase, s.image));
  const kicker = s.kicker ? `<span style="display:inline-block;padding:10px 20px;border-radius:999px;background:rgba(120,140,255,.14);
    border:1px solid rgba(170,190,255,.35);color:#9fb3ff;font-size:17px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase">${s.kicker}</span>` : "";
  const sub = s.sub ? `<div style="font-size:27px;line-height:1.45;color:#cfd8ff;max-width:620px;margin-top:4px">${s.sub}</div>` : "";
  const prompt = s.prompt ? `<div style="font-size:24px;line-height:1.45;color:#9fb3ff;max-width:620px;margin-top:28px">“${s.prompt}”</div>` : "";
  const caption = s.caption ? `<div style="font-size:19px;line-height:1.4;color:#8d9bd0;margin-top:28px;text-align:center;max-width:760px">${s.caption}</div>` : "";
  const counter = `${String(n).padStart(2, "0")} / ${String(total).padStart(2, "0")}`;
  return `<div style="position:relative;width:1920px;height:1080px;overflow:hidden;${dark}">
    ${gridFloor(340)}
    <div style="position:absolute;left:112px;top:0;width:820px;height:1080px;display:flex;flex-direction:column;justify-content:center">
      ${kicker}
      <div style="font-size:92px;font-weight:800;letter-spacing:-2.5px;line-height:1.02;color:#ffffff;margin-top:30px">${s.line1}</div>
      <div style="font-size:92px;font-weight:800;letter-spacing:-2.5px;line-height:1.02;color:#8fd3ff">${s.line2}</div>
      <div style="width:130px;height:6px;border-radius:3px;background:#9fb3ff;margin:34px 0 30px"></div>
      ${sub}
      ${prompt}
    </div>
    <div style="position:absolute;right:84px;top:0;width:860px;height:1080px;display:flex;flex-direction:column;align-items:center;justify-content:center">
      <img src="${src}" style="width:820px;height:700px;object-fit:contain;filter:drop-shadow(0 26px 34px rgba(0,0,0,.5))">
      ${caption}
    </div>
    <div style="position:absolute;right:56px;top:46px;${MONO}font-size:18px;font-weight:600;color:#8d9bd0">${counter}</div>
    <div style="position:absolute;right:56px;bottom:46px;font-size:20px;font-weight:700;color:#9fb3ff">Meshwright v1</div>
  </div>`;
}

// End card for the launch film (docs/15 section 7): slide 1's village diorama with the headline replaced by the
// one-line install command and the licence line (the film's ffmpeg has no text renderer, so it is pre-rendered).
function endCardPage(imageBase) {
  const src = "file://" + path.join(imageBase, "scenes_out", "village.png");
  return `<div style="position:relative;width:1920px;height:1080px;overflow:hidden;${dark}">
    ${gridFloor(340)}
    <div style="position:absolute;left:112px;top:0;width:900px;height:1080px;display:flex;flex-direction:column;justify-content:center">
      <span style="align-self:flex-start;display:inline-block;padding:10px 20px;border-radius:999px;background:rgba(120,140,255,.14);
        border:1px solid rgba(170,190,255,.35);color:#9fb3ff;font-size:17px;font-weight:700;letter-spacing:2.5px">RUN IT LOCALLY</span>
      <div style="font-size:66px;font-weight:800;letter-spacing:-1.5px;line-height:1.06;color:#ffffff;margin-top:30px">One sentence.<br>One game-ready GLB.</div>
      <div style="width:130px;height:6px;border-radius:3px;background:#9fb3ff;margin:34px 0 30px"></div>
      <div style="${MONO}font-size:24px;line-height:1.55;color:#9fb3ff">$ ${OLLAMA}<br>--think=false "a stone well with a wooden roof"</div>
      <div style="font-size:24px;line-height:1.45;color:#cfd8ff;margin-top:26px">Free and open · Apache 2.0 · Built on Muse Glimmer 30B</div>
    </div>
    <div style="position:absolute;right:84px;top:0;width:860px;height:1080px;display:flex;align-items:center;justify-content:center">
      <img src="${src}" style="max-width:820px;max-height:760px;filter:drop-shadow(0 26px 34px rgba(0,0,0,.5))">
    </div>
    <div style="position:absolute;right:56px;bottom:46px;font-size:20px;font-weight:700;color:#9fb3ff">Meshwright v1</div>
  </div>`;
}

const browser = await chromium.launch({ args: ["--allow-file-access-from-files"] });

// Render one page, trimming the transparent margins off the images whose src matches trimPattern.
async function renderPage(outDir, name, w, h, body, trimPattern) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  const tmp = path.join(outDir, `.${name}.html`);
  fs.writeFileSync(tmp, `<!doctype html><html><head><meta charset="utf-8"><style>${base}</style></head><body>${body}</body></html>`);
  await page.goto("file://" + tmp);
  await page.waitForFunction(() => [...document.images].every((i) => i.complete && i.naturalWidth > 0));
  const trimmed = await page.evaluate(async (pat) => {
    const re = new RegExp(pat);
    const hits = [...document.images].filter((i) => re.test(i.src));
    for (const im of hits) {
      const c = document.createElement("canvas"); c.width = im.naturalWidth; c.height = im.naturalHeight;
      const x = c.getContext("2d"); x.drawImage(im, 0, 0);
      const d = x.getImageData(0, 0, c.width, c.height).data;
      let a = c.width, b = c.height, r = 0, t = 0;
      for (let y = 0; y < c.height; y++) for (let k = 0; k < c.width; k++) if (d[(y * c.width + k) * 4 + 3] > 24) { if (k < a) a = k; if (k > r) r = k; if (y < b) b = y; if (y > t) t = y; }
      const o = document.createElement("canvas"); o.width = r - a + 1; o.height = t - b + 1;
      o.getContext("2d").drawImage(c, a, b, o.width, o.height, 0, 0, o.width, o.height);
      im.src = o.toDataURL(); await im.decode();
    }
    return [hits.length, [...document.images].map((i) => i.src.slice(0, 90))];
  }, trimPattern);
  if (process.env.PROMO_DEBUG) console.log(name, trimPattern, JSON.stringify(trimmed));
  await page.screenshot({ path: path.join(outDir, name), fullPage: true });
  await page.close();
  fs.rmSync(tmp);
}

if (SLIDES_MODE) {
  const slidesFile = path.resolve(opt("slides-file", path.join(DIR, "slides.json")));
  if (!fs.existsSync(slidesFile)) {
    console.error("usage: node release/v1/promo/make.mjs [--slides [--slides-file FILE] [--out DIR]]\nno slides file at " + slidesFile);
    await browser.close();
    process.exit(2);
  }
  let slides;
  try { slides = JSON.parse(fs.readFileSync(slidesFile, "utf8")); } catch (e) {
    console.error("could not read slides " + slidesFile + ": " + e.message);
    await browser.close();
    process.exit(2);
  }
  if (!Array.isArray(slides) || !slides.length) {
    console.error("slides file must be a non-empty array: " + slidesFile);
    await browser.close();
    process.exit(2);
  }
  const imageBase = path.dirname(slidesFile);   // a relative image is resolved next to the slides file
  const slideOut = path.resolve(opt("out", path.join(OUT, "slides")));
  fs.mkdirSync(slideOut, { recursive: true });
  for (let i = 0; i < slides.length; i++) {
    const file = String(i + 1).padStart(2, "0") + "_" + (slides[i].name || "slide") + ".png";
    await renderPage(slideOut, file, 1920, 1080, slidePage(slides[i], i + 1, slides.length, imageBase), "/(renders_hero|scenes_out)/");
    console.log("wrote", file);
  }
  await browser.close();
  process.exit(0);
}

if (ENDCARD_MODE) {
  const cardOut = path.resolve(opt("out", path.join(OUT, "film")));
  fs.mkdirSync(cardOut, { recursive: true });
  await renderPage(cardOut, "end_card.png", 1920, 1080, endCardPage(DIR), "/scenes_out/");
  console.log("wrote", path.join(cardOut, "end_card.png"));
  await browser.close();
  process.exit(0);
}

for (const [name, [w, h, body]] of Object.entries(pages)) {
  await renderPage(OUT, name, w, h, body, "/renders/");
  console.log("wrote", name);
}
await browser.close();
