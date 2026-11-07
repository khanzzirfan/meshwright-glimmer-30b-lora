// Render every exported GLB next to its brief as a blind contact sheet for human rating.
// usage: node scripts/glb_sheet.mjs --root DIR --out DIR [--briefs FILE] [--size 256] [--seed 1]
//
// For each <root>/<model>/glb/<id>.glb this writes <out>/<model>/<id>.png (a 3/4 view and a top view
// side by side) and one <out>/<model>/sheet.png. A GLB that fails to load is listed in <out>/skipped.json
// and never stops the other files. A rerun skips PNGs that already exist.
//
// rating.csv is shuffled with a seeded PRNG and uses keys like r001, so it names neither the model nor a
// model folder. The image column points at a key-named copy under <out>/images/; briefs without a rendered
// GLB keep an empty image. key_map.json holds the real key -> {model, id} mapping.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const LOCAL_THREE = path.join(ROOT, "node_modules/three/build/three.module.js");
const LOCAL_GLTF_LOADER = path.join(ROOT, "node_modules/three/examples/jsm/loaders/GLTFLoader.js");
const LOCAL_BUFFER_UTILS = path.join(ROOT, "node_modules/three/examples/jsm/utils/BufferGeometryUtils.js");
const SHEET_URL = "http://glb-sheet.local/";
const BACKGROUND = 0xbfbfbf;

const arg = (n, d) => { const i = process.argv.indexOf("--" + n); return i > -1 ? process.argv[i + 1] : d; };

const rootDir = arg("root");
const outDir = arg("out");
const briefsPath = arg("briefs", "bench/glb/briefs.jsonl");
const size = Math.max(16, Math.floor(+arg("size", 256)));
const seed = (Number(arg("seed", 1)) >>> 0);

if (!rootDir || !outDir) {
  console.error("usage: node scripts/glb_sheet.mjs --root DIR --out DIR [--briefs FILE] [--size N] [--seed N]");
  process.exit(2);
}
if (!fs.existsSync(rootDir)) {
  console.error(`root not found: ${rootDir}`);
  process.exit(2);
}
if (!fs.existsSync(briefsPath)) {
  console.error(`briefs not found: ${briefsPath}`);
  process.exit(2);
}

// Set GLB_SHEET_REQUEST_LOG to a file path to record every request that was not served locally.
// The offline test uses it to prove that no page reaches the network.
const requestLogPath = process.env.GLB_SHEET_REQUEST_LOG || null;
const outsideRequests = [];
const isLocal = (url) => url.startsWith(SHEET_URL) || /^(?:data|blob|about):/.test(url);
const watchRequests = (page) => {
  page.on("request", (req) => { if (!isLocal(req.url())) outsideRequests.push(req.url()); });
};

const readBriefs = (file) => fs.readFileSync(file, "utf8").trim().split("\n").filter(Boolean)
  .map((line) => JSON.parse(line));

const listGlbs = () => {
  const models = new Map();
  for (const entry of fs.readdirSync(rootDir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    if (!entry.isDirectory()) continue;
    const glbDir = path.join(rootDir, entry.name, "glb");
    if (!fs.existsSync(glbDir)) continue;
    const ids = fs.readdirSync(glbDir).filter((name) => name.endsWith(".glb")).sort()
      .map((name) => name.slice(0, -4));
    models.set(entry.name, { dir: glbDir, ids });
  }
  return models;
};

// mulberry32: tiny deterministic PRNG, so the same seed always gives the same rating order.
function makeRng(seedValue) {
  let a = seedValue >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffled(values, rng) {
  const out = values.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

const pageHtml = `<!doctype html><html><body style="margin:0;overflow:hidden;background:#bfbfbf">
<canvas id="c"></canvas>
<script type="importmap">{"imports":{"three":"${SHEET_URL}build/three.module.js"}}</script>
<script type="module">
import * as T from '${SHEET_URL}build/three.module.js';
import { GLTFLoader } from '${SHEET_URL}examples/jsm/loaders/GLTFLoader.js';

const canvas = document.getElementById('c');
const renderer = new T.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);

window.renderGlb = (b64, size) => new Promise((resolve) => {
  const raw = atob(b64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);

  const loaded = (gltf) => {
    try {
      const root = gltf.scene || (gltf.scenes && gltf.scenes[0]);
      if (!root) { resolve({ ok: false, error: 'empty_scene' }); return; }
      const scene = new T.Scene();
      scene.background = new T.Color(${BACKGROUND});
      scene.add(new T.HemisphereLight(0xffffff, 0x444455, 1.6));
      const light = new T.DirectionalLight(0xffffff, 1.8);
      scene.add(light);
      scene.add(root);

      const box = new T.Box3().setFromObject(root);
      if (box.isEmpty()) { resolve({ ok: false, error: 'empty_scene' }); return; }
      const centre = box.getCenter(new T.Vector3());
      const extent = box.getSize(new T.Vector3());
      const maxDim = Math.max(extent.x, extent.y, extent.z) || 1;
      light.position.set(centre.x + maxDim * 2, centre.y + maxDim * 3, centre.z + maxDim * 2);

      const fov = 35;
      const dist = (maxDim / 2) / Math.tan(fov * Math.PI / 360) * 1.6;
      renderer.setSize(size * 2, size);
      renderer.autoClear = false;
      renderer.setClearColor(${BACKGROUND}, 1);
      renderer.setScissorTest(true);
      renderer.setViewport(0, 0, size * 2, size);
      renderer.setScissor(0, 0, size * 2, size);
      renderer.clear();

      const views = [
        { dir: new T.Vector3(1, 0.8, 1).normalize(), up: new T.Vector3(0, 1, 0) },
        { dir: new T.Vector3(0, 1, 0.0001).normalize(), up: new T.Vector3(0, 0, -1) },
      ];
      for (let i = 0; i < views.length; i++) {
        const view = views[i];
        const camera = new T.PerspectiveCamera(fov, 1, maxDim / 1000, dist * 10);
        camera.up.copy(view.up);
        camera.position.copy(centre).addScaledVector(view.dir, dist);
        camera.lookAt(centre);
        renderer.setViewport(i * size, 0, size, size);
        renderer.setScissor(i * size, 0, size, size);
        renderer.render(scene, camera);
      }
      resolve({ ok: true });
    } catch (error) {
      resolve({ ok: false, error: String(error && error.message || error) });
    }
  };
  try {
    new GLTFLoader().parse(bytes.buffer, '', loaded, (error) => {
      resolve({ ok: false, error: String(error && error.message || error) });
    });
  } catch (error) {
    resolve({ ok: false, error: String(error && error.message || error) });
  }
});
window.ready = true;
</script></body></html>`;

const escapeHtml = (text) => String(text).replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));

const csvCell = (value) => {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

async function openRenderPage(browser) {
  const page = await browser.newPage({ viewport: { width: size * 2, height: size }, deviceScaleFactor: 1 });
  watchRequests(page);
  page.on("pageerror", (e) => console.error("pageerror", e.message));
  await page.route("**/*", (route) => {
    const url = route.request().url();
    if (/^(?:data|blob|about):/.test(url)) return route.continue();
    if (url === SHEET_URL) return route.fulfill({ body: pageHtml, contentType: "text/html" });
    if (url === SHEET_URL + "build/three.module.js") {
      return route.fulfill({ path: LOCAL_THREE, contentType: "text/javascript" });
    }
    if (url === SHEET_URL + "examples/jsm/loaders/GLTFLoader.js") {
      return route.fulfill({ path: LOCAL_GLTF_LOADER, contentType: "text/javascript" });
    }
    if (url === SHEET_URL + "examples/jsm/utils/BufferGeometryUtils.js") {
      return route.fulfill({ path: LOCAL_BUFFER_UTILS, contentType: "text/javascript" });
    }
    return route.abort();
  });
  await page.goto(SHEET_URL, { waitUntil: "load", timeout: 15000 });
  await page.waitForFunction("window.ready === true", null, { timeout: 30000 });
  return page;
}

async function writeSheet(browser, model, entries) {
  if (entries.length === 0) return;
  const page = await browser.newPage({ viewport: { width: 1200, height: 800 }, deviceScaleFactor: 1 });
  try {
    watchRequests(page);
    const columns = Math.min(4, entries.length);
    const tiles = entries.map(({ id, file }) => {
      const dataUrl = "data:image/png;base64," + fs.readFileSync(file).toString("base64");
      return `<figure style="margin:0"><img src="${dataUrl}" style="width:${size}px;height:auto;display:block;border:1px solid #aaa"><figcaption style="font:12px sans-serif;text-align:center;padding-top:4px">${escapeHtml(id)}</figcaption></figure>`;
    }).join("");
    const html = `<!doctype html><html><body style="margin:0;padding:12px;background:#fff">
<div id="sheet" style="display:inline-grid;grid-template-columns:repeat(${columns},${size}px);gap:12px">${tiles}</div>
</body></html>`;
    await page.setContent(html, { waitUntil: "load" });
    await page.waitForFunction(() => Array.from(document.images).every((img) => img.complete), null, { timeout: 30000 });
    await page.locator("#sheet").screenshot({ path: path.join(outDir, model, "sheet.png") });
  } finally {
    await page.close();
  }
}

fs.mkdirSync(outDir, { recursive: true });
const briefs = readBriefs(briefsPath);
const models = listGlbs();
const skipped = [];
let rendered = 0;
let already = 0;

const browser = await chromium.launch({
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
});
try {
  const page = await openRenderPage(browser);
  for (const [model, info] of models) {
    const modelOut = path.join(outDir, model);
    fs.mkdirSync(modelOut, { recursive: true });
    for (const id of info.ids) {
      const png = path.join(modelOut, id + ".png");
      if (fs.existsSync(png)) { already++; continue; }
      const b64 = fs.readFileSync(path.join(info.dir, id + ".glb")).toString("base64");
      const result = await page.evaluate(({ data, pixels }) => window.renderGlb(data, pixels), { data: b64, pixels: size });
      if (!result.ok) {
        skipped.push({ model, id, reason: result.error || "load_fail" });
        continue;
      }
      await page.locator("canvas").screenshot({ path: png });
      rendered++;
    }
  }
  await page.close();

  for (const [model, info] of models) {
    const entries = info.ids
      .map((id) => ({ id, file: path.join(outDir, model, id + ".png") }))
      .filter((entry) => fs.existsSync(entry.file));
    await writeSheet(browser, model, entries);
  }
} finally {
  await browser.close();
}

fs.writeFileSync(path.join(outDir, "skipped.json"), JSON.stringify(skipped, null, 2) + "\n");

// One blind row per model x brief. Keys are assigned after the seeded shuffle, so neither the order nor the
// keys reveal a model. Images are copied to key-named files because the per-model PNGs name their model.
const rng = makeRng(seed);
const rows = [];
for (const model of models.keys()) {
  for (const brief of briefs) rows.push({ model, id: brief.id });
}
const order = shuffled(rows, rng);
const imagesDir = path.join(outDir, "images");
fs.mkdirSync(imagesDir, { recursive: true });
const keyMap = {};
const csv = ["key,brief,image,rating"];
order.forEach((row, index) => {
  const key = "r" + String(index + 1).padStart(3, "0");
  keyMap[key] = { model: row.model, id: row.id };
  const source = path.join(outDir, row.model, row.id + ".png");
  let image = "";
  if (fs.existsSync(source)) {
    image = "images/" + key + ".png";
    fs.copyFileSync(source, path.join(outDir, image));
  }
  csv.push([key, row.id, image, ""].map(csvCell).join(","));
});
fs.writeFileSync(path.join(outDir, "rating.csv"), csv.join("\n") + "\n");
fs.writeFileSync(path.join(outDir, "key_map.json"), JSON.stringify(keyMap, null, 2) + "\n");

if (requestLogPath) fs.writeFileSync(requestLogPath, JSON.stringify(outsideRequests, null, 2) + "\n");
console.log(`rendered ${rendered}, skipped ${skipped.length}, already done ${already}, rating rows ${order.length}`);
