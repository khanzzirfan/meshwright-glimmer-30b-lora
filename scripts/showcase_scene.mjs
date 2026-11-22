// Compose many generated GLBs on one plinth and render the group as a diorama (docs/15, promo-1 US-002).
// usage: node scripts/showcase_scene.mjs --layout FILE --out DIR [--width 1920] [--height 1080] [--frames N]
//        [--name NAME] [--strict]
//
// The layout JSON is {plinth: {shape: 'round'|'square', size_m, top, side}, camera: {yaw, pitch, fov, zoom},
// items: [{glb, x, z, rot_y_deg, height_m?, scale?}]}. Each item is loaded and placed whole: its lowest point
// sits on the plinth top (y = 0) and its x/z centre moves to (x, z). height_m scales it uniformly to that
// height, otherwise scale (default 1, the asset's own metres). Geometry, materials and animation are never
// edited — only whole-asset translate, rotate and uniform scale. An item with on_water: true sits on the water
// surface instead (see below).
//
// An optional layout.water {color, side, drop_m} makes one half of a square plinth a harbour's water: the plinth
// top is drawn in water.color (default 0x5aa0d8) and lowered by drop_m (default 0.01 m), a land shelf in the
// plinth top colour covers the other half, so the water surface sits drop_m below the land top. side is which
// half is water: front (+z) | back (-z) | left (-x) | right (+x).
//
// Before rendering it checks the placed items' x/z footprints and prints a warning line per overlapping pair;
// --strict turns any overlap into an error. One JSON line {items, overlaps, missing} is always printed last. A
// missing GLB is an error naming the path. It writes DIR/NAME.png (a transparent-background still at width x
// height), and with --frames N also DIR/NAME_orbit/0000.png... (a full 360-degree camera orbit around the plinth
// centre, playing each animated item's first clip). Offline: three.js is served from node_modules and the studio
// look comes from scripts/showcase_common.mjs, which is served to the page with three.js.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const THREE_DIR = path.join(ROOT, "node_modules/three");
const COMMON = path.join(ROOT, "scripts/showcase_common.mjs");
const BASE = "http://showcase.local/";
const arg = (n, d) => { const i = process.argv.indexOf("--" + n); return i > -1 ? process.argv[i + 1] : d; };
const hex = (s, d) => { const n = parseInt(String(s).replace(/^#/, "").replace(/^0x/i, ""), 16); return Number.isInteger(n) ? n : d; };

const usage = "usage: node scripts/showcase_scene.mjs --layout FILE --out DIR [--width N] [--height N] [--frames N] [--name NAME] [--strict]";
const layoutFile = arg("layout");
const outDir = arg("out");
const width = +arg("width", 1920);
const height = +arg("height", 1080);
const frames = +arg("frames", 0);
const strict = process.argv.includes("--strict");
if (!layoutFile || !outDir) {
  console.error(usage);
  process.exit(2);
}

let layout;
try {
  layout = JSON.parse(fs.readFileSync(layoutFile, "utf8"));
} catch (e) {
  console.error("could not read layout " + layoutFile + ": " + e.message + "\n" + usage);
  process.exit(2);
}
const layoutDir = path.dirname(path.resolve(layoutFile));
const rawItems = Array.isArray(layout.items) ? layout.items : null;
const plinthSpec = layout.plinth;
if (!rawItems || !plinthSpec || !["round", "square"].includes(plinthSpec.shape) || !(Number(plinthSpec.size_m) > 0)) {
  console.error("layout needs {plinth: {shape: round|square, size_m}, items: [...]}\n" + usage);
  process.exit(2);
}
const name = arg("name", path.basename(layoutFile).replace(/\.json$/i, ""));
const camera = {
  yaw: Number.isFinite(+layout.camera?.yaw) ? +layout.camera.yaw : 35,
  pitch: Number.isFinite(+layout.camera?.pitch) ? +layout.camera.pitch : 22,
  fov: Number.isFinite(+layout.camera?.fov) ? +layout.camera.fov : 30,
  zoom: Number.isFinite(+layout.camera?.zoom) ? +layout.camera.zoom : 1,
};
const plinth = { shape: plinthSpec.shape, size_m: Number(plinthSpec.size_m), top: hex(plinthSpec.top, 0x9ccf7a), side: hex(plinthSpec.side, 0x8a5a3c) };

// Optional harbour water: layout.water {color, side, drop_m} makes one half of a square plinth the water
// surface. The plinth top is drawn in the water colour and lowered by drop_m; a land shelf in the plinth top
// colour covers the other half, so the water sits drop_m below the land. Items with on_water: true sit on it.
const waterSpec = layout.water;
const water = waterSpec && waterSpec.color != null ? {
  color: hex(waterSpec.color, 0x5aa0d8),
  side: ['front', 'back', 'left', 'right'].includes(waterSpec.side) ? waterSpec.side : 'front',
  drop_m: Number.isFinite(+waterSpec.drop_m) ? +waterSpec.drop_m : 0.01,
} : null;
if (water && plinth.shape !== 'square') {
  console.error("layout.water needs plinth.shape 'square'\n" + usage);
  process.exit(2);
}

// Resolve each item's GLB (absolute, repo-relative, or relative to the layout file) and flag the missing ones.
const items = rawItems.map((it, i) => {
  const id = it.id || path.basename(String(it.glb), ".glb") || "item" + i;
  const p = path.isAbsolute(it.glb) ? it.glb
    : fs.existsSync(path.resolve(process.cwd(), it.glb)) ? path.resolve(process.cwd(), it.glb)
      : path.resolve(layoutDir, it.glb);
  return {
    id, path: p, x: +it.x || 0, z: +it.z || 0, rot_y_deg: +it.rot_y_deg || 0,
    height_m: it.height_m == null ? null : +it.height_m,
    scale: it.scale == null ? 1 : +it.scale,
    on_water: it.on_water === true,
  };
});
const missing = items.filter((it) => !fs.existsSync(it.path));
const summary = (overlaps, miss) => ({ items: items.length - miss, overlaps, missing: miss });
if (missing.length) {
  for (const it of missing) console.error("missing GLB: " + it.path);
  console.log(JSON.stringify(summary(0, missing.length)));
  process.exit(1);
}

const html = `<!doctype html><html><body style="margin:0;background:transparent">
<canvas id="c"></canvas>
<script type="importmap">{"imports":{"three":"${BASE}build/three.module.js","showcase_common.js":"${BASE}showcase_common.js"}}</script>
<script type="module">
import * as T from 'three';
import { GLTFLoader } from '${BASE}examples/jsm/loaders/GLTFLoader.js';
import * as ST from 'showcase_common.js';
const renderer = ST.createStudioRenderer(T, document.getElementById('c'));
renderer.setSize(${width}, ${height});
// Load one item's GLB from base64; resolve with {it, gltf} or {it, error}.
const loadOne = (loader, it) => new Promise((resolve) => {
  const raw = atob(it.b64); const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  loader.parse(bytes.buffer, '', (gltf) => resolve({ it, gltf }), (err) => resolve({ it, error: String(err) }));
});
window.load = (spec) => new Promise(async (resolve) => {
  const loader = new GLTFLoader();
  const loaded = await Promise.all(spec.items.map((it) => loadOne(loader, it)));
  const scene = new T.Scene();
  const placed = [];
  const mixers = [];
  const errors = [];
  for (const { it, gltf, error } of loaded) {
    if (error || !gltf) { errors.push({ id: it.id, error: error || 'load failed' }); continue; }
    const root = gltf.scene;
    root.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
    const pivot = new T.Group(); pivot.add(root);
    let s = it.scale;
    if (it.height_m != null) { const b = new T.Box3().setFromObject(root); const h = b.getSize(new T.Vector3()).y; s = h > 0 ? it.height_m / h : 1; }
    pivot.scale.setScalar(s);
    pivot.rotation.y = it.rot_y_deg * Math.PI / 180;
    pivot.updateMatrixWorld(true);
    const box = new T.Box3().setFromObject(pivot);
    const c = box.getCenter(new T.Vector3());
    pivot.position.set(it.x - c.x, it.base_y - box.min.y, it.z - c.z);   // lowest point to the item's ground, centre to (x, z)
    pivot.updateMatrixWorld(true);
    scene.add(pivot);
    let meshes = 0; const materials = new Set();
    root.traverse((o) => {
      if (!o.isMesh) return;
      meshes++;
      for (const mat of (Array.isArray(o.material) ? o.material : [o.material])) if (mat) materials.add(mat.uuid);
    });
    let anim = false;
    if (gltf.animations && gltf.animations.length) {
      const mixer = new T.AnimationMixer(root); const clip = gltf.animations[0]; mixer.clipAction(clip).play();
      mixers.push({ mixer, clip }); anim = true;
    }
    placed.push({ id: it.id, x: it.x, z: it.z, hx: (box.max.x - box.min.x) / 2, hz: (box.max.z - box.min.z) / 2, meshes, materials: materials.size, anim });
  }
  const thickness = spec.plinth.size_m * 0.06;
  const drop = spec.water ? spec.water.drop_m : 0;
  if (spec.water) {
    const opposite = { front: 'back', back: 'front', left: 'right', right: 'left' }[spec.water.side];
    const base = ST.makePlinth(T, 'square', spec.plinth.size_m, thickness, spec.water.color, spec.plinth.side);
    base.group.position.y = -drop;                 // the plinth top is the water surface, drop below the land
    scene.add(base.group);
    scene.add(ST.makeLandShelf(T, spec.plinth.size_m, opposite, drop, spec.plinth.top));
  } else {
    scene.add(ST.makePlinth(T, spec.plinth.shape, spec.plinth.size_m, thickness, spec.plinth.top, spec.plinth.side).group);
  }
  const sphere = new T.Box3().setFromObject(scene).getBoundingSphere(new T.Sphere());
  const r = sphere.radius || 1;
  ST.addStudioLights(T, scene, r);
  ST.addContactShadow(T, scene, r, -thickness - drop);
  const center = sphere.center.clone(); center.x = 0; center.z = 0;   // orbit the plinth centre
  const fov = spec.camera.fov, yaw0 = spec.camera.yaw, pitch = spec.camera.pitch, zoom = spec.camera.zoom;
  const dist = r / Math.sin(fov * Math.PI / 360) * 1.08 / (zoom || 1);
  const camera = new T.PerspectiveCamera(fov, spec.width / spec.height, r / 500, dist * 10);
  const dirFor = (yawDeg) => { const yw = yawDeg * Math.PI / 180, pt = pitch * Math.PI / 180; return new T.Vector3(Math.sin(yw) * Math.cos(pt), Math.sin(pt), Math.cos(yw) * Math.cos(pt)); };
  window.frame = (t) => {
    const orbit = typeof t === 'number' ? t : 0;
    camera.position.copy(center).addScaledVector(dirFor(yaw0 + orbit * 360), dist);
    camera.lookAt(center);
    for (const m of mixers) m.mixer.setTime(orbit * Math.max(m.clip.duration, 0.001) * Math.max(1, Math.round(4 / Math.max(m.clip.duration, 0.5))));
    renderer.render(scene, camera);
    return true;
  };
  resolve({ ok: errors.length === 0, items: placed, errors });
});
window.ready = true;
</script></body></html>`;

const browser = await chromium.launch({ args: ["--use-angle=metal", "--enable-gpu"] });
const page = await browser.newPage({ viewport: { width, height } });
await page.route(BASE + "**", (route) => {
  const rel = route.request().url().slice(BASE.length);
  if (rel === "" || rel === "index.html") return route.fulfill({ contentType: "text/html", body: html });
  if (rel === "showcase_common.js") return route.fulfill({ contentType: "text/javascript", body: fs.readFileSync(COMMON) });
  const file = path.join(THREE_DIR, rel);
  if (!file.startsWith(THREE_DIR) || !fs.existsSync(file)) return route.fulfill({ status: 404, body: "" });
  return route.fulfill({ contentType: "text/javascript", body: fs.readFileSync(file) });
});
await page.route(/^(?!http:\/\/showcase\.local\/)https?:/, (route) => route.abort());
await page.goto(BASE);
await page.waitForFunction(() => window.ready === true);

const spec = {
  width, height, camera, plinth, water,
  items: items.map((it) => ({ id: it.id, x: it.x, z: it.z, rot_y_deg: it.rot_y_deg, height_m: it.height_m, scale: it.scale, base_y: water && it.on_water ? -water.drop_m : 0, b64: fs.readFileSync(it.path).toString("base64") })),
};
const res = await page.evaluate((s) => window.load(s), spec);
if (!res.ok) {
  for (const e of res.errors) console.error("error: " + e.id + ": " + e.error);
  console.log(JSON.stringify(summary(0, 0)));
  await browser.close();
  process.exit(1);
}

// Footprint overlaps, before any rendering: one warning per overlapping pair, an error under --strict.
const overlaps = [];
for (let i = 0; i < res.items.length; i++) {
  for (let j = i + 1; j < res.items.length; j++) {
    const a = res.items[i], b = res.items[j];
    const ox = Math.min(a.x + a.hx, b.x + b.hx) - Math.max(a.x - a.hx, b.x - b.hx);
    const oz = Math.min(a.z + a.hz, b.z + b.hz) - Math.max(a.z - a.hz, b.z - b.hz);
    if (ox > 1e-6 && oz > 1e-6) overlaps.push({ a: a.id, b: b.id, area: ox * oz });
  }
}
for (const o of overlaps) console.error("overlap: " + o.a + " " + o.b + " area=" + o.area.toFixed(4));
if (strict && overlaps.length) {
  console.log(JSON.stringify(summary(overlaps.length, 0)));
  await browser.close();
  process.exit(1);
}

fs.mkdirSync(outDir, { recursive: true });
const shot = async (file) => {
  const b64 = await page.evaluate(() => document.getElementById("c").toDataURL("image/png").split(",")[1]);
  fs.writeFileSync(file, Buffer.from(b64, "base64"));
};
await page.evaluate(() => window.frame(null));
await shot(path.join(outDir, name + ".png"));
if (frames > 0) {
  const d = path.join(outDir, name + "_orbit");
  fs.mkdirSync(d, { recursive: true });
  for (let i = 0; i < frames; i++) {
    await page.evaluate((t) => window.frame(t), i / frames);
    await shot(path.join(d, String(i).padStart(4, "0") + ".png"));
  }
}
await browser.close();
console.log(JSON.stringify(summary(overlaps.length, 0)));
