// Studio renders of exported GLBs for promotion material (docs/15).
// usage: node scripts/showcase_render.mjs --glb FILE[,FILE...] --out DIR [--size 1024] [--frames 0] [--yaw 35]
//        [--pitch 22] [--plinth none|round|square] [--plinth-color 0x9ccf7a] [--plinth-side 0x8a5a3c]
//        [--aspect W:H] [--offset-x F]
//
// For each GLB writes DIR/<name>.png: a transparent-background 3/4 studio shot (soft key light, rim light,
// contact shadow on an invisible ground). With --frames N (N > 0) it also writes DIR/<name>_turn/0000.png...
// a full turntable (and plays the first animation clip, if any, over the turn). Offline: three.js is served
// from node_modules, nothing reaches the network. The studio look (renderer, lights, contact shadow, plinth) is
// shared with showcase_scene.mjs via scripts/showcase_common.mjs, which is served to the page with three.js.
//
// --plinth puts the asset on a low diorama slab like ccore's hero shots: a bevelled base (--plinth-side,
// brown) with a thin top layer (--plinth-color, green), sized 1.25x the asset's footprint, 6% thick, its top
// surface at y = 0, receiving shadows. --aspect W:H renders at --size wide by size*H/W tall (default 1:1, which
// is what every earlier render used) and --offset-x F shifts the subject F frame-widths to the right (default
// 0, centred). With plinth none, aspect 1:1 and offset 0 the output is byte-identical to before these flags.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const THREE_DIR = path.join(ROOT, "node_modules/three");
const COMMON = path.join(ROOT, "scripts/showcase_common.mjs");
const BASE = "http://showcase.local/";
const arg = (n, d) => { const i = process.argv.indexOf("--" + n); return i > -1 ? process.argv[i + 1] : d; };

const glbs = (arg("glb") || "").split(",").filter(Boolean);
const outDir = arg("out");
const size = +arg("size", 1024);
const frames = +arg("frames", 0);
const yaw = +arg("yaw", 35);
const pitch = +arg("pitch", 22);
const plinth = arg("plinth", "none");
const hex = (s, d) => { const n = parseInt(String(s).replace(/^#/, "").replace(/^0x/i, ""), 16); return Number.isInteger(n) ? n : d; };
const plinthColor = hex(arg("plinth-color", "0x9ccf7a"), 0x9ccf7a);
const plinthSide = hex(arg("plinth-side", "0x8a5a3c"), 0x8a5a3c);
const aspect = String(arg("aspect", "1:1")).split(":").map(Number);
const aspectW = aspect[0] > 0 ? aspect[0] : 1;
const aspectH = aspect[1] > 0 ? aspect[1] : 1;
const offsetX = +arg("offset-x", 0) || 0;
const usage = "usage: node scripts/showcase_render.mjs --glb FILE[,FILE...] --out DIR [--size N] [--frames N] [--yaw DEG] [--pitch DEG] [--plinth none|round|square] [--plinth-color HEX] [--plinth-side HEX] [--aspect W:H] [--offset-x F]";
if (!glbs.length || !outDir) {
  console.error(usage);
  process.exit(2);
}
if (!["none", "round", "square"].includes(plinth)) {
  console.error("unknown --plinth " + plinth + "\n" + usage);
  process.exit(2);
}
const outW = size;
const outH = Math.round(size * aspectH / aspectW);
fs.mkdirSync(outDir, { recursive: true });

const html = `<!doctype html><html><body style="margin:0;background:transparent">
<canvas id="c"></canvas>
<script type="importmap">{"imports":{"three":"${BASE}build/three.module.js","showcase_common.js":"${BASE}showcase_common.js"}}</script>
<script type="module">
import * as T from 'three';
import { GLTFLoader } from '${BASE}examples/jsm/loaders/GLTFLoader.js';
import * as ST from 'showcase_common.js';
const renderer = ST.createStudioRenderer(T, document.getElementById('c'));
let S = null;
window.load = (b64, opts) => new Promise((resolve) => {
  const { size, yaw: yawDeg, pitch: pitchDeg, plinth, plinthColor, plinthSide, aspectW, aspectH, offsetX } = opts;
  const raw = atob(b64); const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  new GLTFLoader().parse(bytes.buffer, '', (gltf) => {
    const root = gltf.scene;
    const scene = new T.Scene();
    root.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
    const pivot = new T.Group(); pivot.add(root); scene.add(pivot);
    const box = new T.Box3().setFromObject(root);
    const c = box.getCenter(new T.Vector3()); const e = box.getSize(new T.Vector3());
    root.position.sub(new T.Vector3(c.x, box.min.y, c.z));
    const r = Math.max(e.x, e.y, e.z) || 1;
    ST.addStudioLights(T, scene, r);
    let groundY = 0;
    if (plinth !== 'none') {
      const pSize = (Math.max(e.x, e.z) || 1) * 1.25;
      const thickness = pSize * 0.06;
      pivot.add(ST.makePlinth(T, plinth, pSize, thickness, plinthColor, plinthSide).group);
      groundY = -thickness;
    }
    ST.addContactShadow(T, scene, r, groundY);
    const fov = 30;
    const yw = yawDeg * Math.PI / 180, pt = pitchDeg * Math.PI / 180;
    const dir = new T.Vector3(Math.sin(yw) * Math.cos(pt), Math.sin(pt), Math.cos(yw) * Math.cos(pt));
    const outW = size, outH = Math.round(size * aspectH / aspectW);
    // frame on the bounding sphere (asset plus plinth) so every turntable angle fits
    const frameTarget = plinth === 'none' ? root : pivot;
    const sphere = new T.Box3().setFromObject(frameTarget).getBoundingSphere(new T.Sphere());
    const dist = sphere.radius / Math.sin(fov * Math.PI / 360) * 1.08;
    const camera = new T.PerspectiveCamera(fov, outW / outH, r / 500, dist * 10);
    camera.position.copy(sphere.center).addScaledVector(dir, dist);
    if (offsetX) {
      const right = new T.Vector3().crossVectors(dir.clone().negate(), new T.Vector3(0, 1, 0)).normalize();
      const shift = -offsetX * 2 * dist * Math.tan(fov * Math.PI / 360) * (outW / outH);   // +F moves the subject right
      camera.position.addScaledVector(right, shift);
      sphere.center.addScaledVector(right, shift);
    }
    camera.lookAt(sphere.center);
    renderer.setSize(outW, outH);
    let mixer = null, clip = null;
    if (gltf.animations && gltf.animations.length) { mixer = new T.AnimationMixer(root); clip = gltf.animations[0]; mixer.clipAction(clip).play(); }
    S = { scene, camera, pivot, mixer, clip };
    resolve({ ok: true, anim: !!clip, meshes: (() => { let n = 0; root.traverse((o) => { if (o.isMesh) n++; }); return n; })() });
  }, (err) => resolve({ ok: false, error: String(err) }));
});
window.frame = (t) => {
  S.pivot.rotation.y = t * Math.PI * 2;
  if (S.mixer) S.mixer.setTime(t * Math.max(S.clip.duration, 0.001) * Math.max(1, Math.round(4 / Math.max(S.clip.duration, 0.5))));
  renderer.render(S.scene, S.camera);
  return true;
};
window.ready = true;
</script></body></html>`;

const browser = await chromium.launch({ args: ["--use-angle=metal", "--enable-gpu"] });
const page = await browser.newPage({ viewport: { width: outW, height: outH } });
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

const shot = async (file) => {
  const b64 = await page.evaluate(() => document.getElementById("c").toDataURL("image/png").split(",")[1]);
  fs.writeFileSync(file, Buffer.from(b64, "base64"));
};

for (const glb of glbs) {
  const name = path.basename(glb, ".glb") === "asset" ? path.basename(path.dirname(glb)) : path.basename(glb, ".glb");
  const res = await page.evaluate(([b, o]) => window.load(b, o),
    [fs.readFileSync(glb).toString("base64"), { size, yaw, pitch, plinth, plinthColor, plinthSide, aspectW, aspectH, offsetX }]);
  if (!res.ok) { console.log(JSON.stringify({ name, ok: false, error: res.error })); continue; }
  await page.evaluate(() => window.frame(0));
  await shot(path.join(outDir, `${name}.png`));
  if (frames > 0) {
    const d = path.join(outDir, `${name}_turn`); fs.mkdirSync(d, { recursive: true });
    for (let i = 0; i < frames; i++) {
      await page.evaluate((t) => window.frame(t), i / frames);
      await shot(path.join(d, String(i).padStart(4, "0") + ".png"));
    }
  }
  console.log(JSON.stringify({ name, ok: true, meshes: res.meshes, anim: res.anim }));
}
await browser.close();
