// Render each text mesh from a JSONL file to a few small PNG views so an image-text model can score them.
// usage: node scripts/render_views.mjs --in FILE.jsonl --out-dir DIR [--views 4] [--size 224]
// Rows are {name, text}. Valid rows write DIR/<name>/view0.png .. view{N-1}.png.
// Broken rows are listed in DIR/skipped.json and never stop the other rows. A row whose views all exist is not
// rendered again, so a rerun is resumable.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };

const inFile = arg('in');
const outDir = arg('out-dir');
const views = +arg('views', 4);
const size = +arg('size', 224);

if (!inFile || !outDir) {
  console.error('usage: node scripts/render_views.mjs --in FILE.jsonl --out-dir DIR [--views N] [--size N]');
  process.exit(2);
}

const rows = fs.readFileSync(inFile, 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l));

// Parse a text mesh into vertices and colour groups, or return {error}. Face indices are 1-based in the text and
// validated against the vertex count after the whole row is read, so a forward reference cannot fool the check.
function parseMesh(text) {
  const verts = [];
  const groups = [];
  const faces = [];
  let cur = null;
  for (const ln of String(text ?? '').split('\n')) {
    const p = ln.trim().split(/\s+/);
    if (p[0] === 'v') {
      const xyz = p.slice(1).map(Number);
      if (xyz.length !== 3 || xyz.some((n) => !Number.isFinite(n))) return { error: 'bad_vertex_line' };
      verts.push(xyz);
    } else if (p[0] === 'c') {
      cur = { col: /^#[0-9a-fA-F]{6}$/.test(p[1]) ? p[1] : '#cccccc', idx: [] };
      groups.push(cur);
    } else if (p[0] === 'f') {
      if (!cur) { cur = { col: '#cccccc', idx: [] }; groups.push(cur); }
      const idx = p.slice(1).map(Number);
      if (idx.length !== 3 || idx.some((n) => !Number.isInteger(n))) return { error: 'bad_face_line' };
      faces.push({ group: cur, idx });
    }
  }
  if (verts.length === 0) return { error: 'no_vertices' };
  if (faces.length === 0) return { error: 'no_faces' };
  for (const f of faces) {
    if (f.idx.some((n) => n < 1 || n > verts.length)) return { error: 'face_index_out_of_range' };
    f.group.idx.push(...f.idx.map((n) => n - 1));
  }
  const nonEmpty = groups.filter((g) => g.idx.length > 0);
  if (nonEmpty.length === 0) return { error: 'no_faces' };
  return { verts, groups: nonEmpty };
}

const viewPath = (name, i) => path.join(outDir, name, `view${i}.png`);
const allViewsExist = (name) => {
  for (let i = 0; i < views; i++) if (!fs.existsSync(viewPath(name, i))) return false;
  return true;
};

fs.mkdirSync(outDir, { recursive: true });

const toRender = [];
const skipped = [];
let already = 0;
for (const row of rows) {
  if (allViewsExist(row.name)) { already++; continue; }
  const mesh = parseMesh(row.text);
  if (mesh.error) { skipped.push({ name: row.name, reason: mesh.error }); continue; }
  toRender.push({ name: row.name, mesh });
}

const three = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'node_modules/three/build/three.module.js'), 'utf8');

const html = `<body style="margin:0;overflow:hidden;background:#808080"><canvas id="c"></canvas><script type="module">
import * as T from 'data:text/javascript;base64,${Buffer.from(three).toString('base64')}';
const size = ${size};
const r = new T.WebGLRenderer({ canvas: c, antialias: true, preserveDrawingBuffer: true });
r.setPixelRatio(1);
r.setSize(size, size);
const bg = new T.Color(0x808080);
window.renderView = (data, azDeg, elDeg) => {
  const s = new T.Scene(); s.background = bg;
  s.add(new T.HemisphereLight(0xffffff, 0x444455, 1.6));
  const d = new T.DirectionalLight(0xffffff, 1.8); d.position.set(2, 3, 1); s.add(d);
  const mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
  for (const v of data.verts) for (let i = 0; i < 3; i++) { if (v[i] < mn[i]) mn[i] = v[i]; if (v[i] > mx[i]) mx[i] = v[i]; }
  const centre = [0, 1, 2].map((i) => (mn[i] + mx[i]) / 2);
  const ext = Math.max(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]) || 1;
  const pos = data.verts.map((v) => [0, 1, 2].map((i) => (v[i] - centre[i]) / ext));
  for (const g of data.groups) {
    const geo = new T.BufferGeometry();
    geo.setAttribute('position', new T.Float32BufferAttribute(pos.flat(), 3));
    geo.setIndex(g.idx); geo.computeVertexNormals();
    s.add(new T.Mesh(geo, new T.MeshStandardMaterial({ color: g.col, flatShading: true, side: T.DoubleSide, metalness: 0, roughness: 1 })));
  }
  const fov = 35;
  const dist = (0.5 / Math.tan(fov * Math.PI / 360)) * 1.35;
  const az = azDeg * Math.PI / 180, el = elDeg * Math.PI / 180;
  const cam = new T.PerspectiveCamera(fov, 1, 0.01, 100);
  cam.position.set(dist * Math.cos(el) * Math.sin(az), dist * Math.sin(el), dist * Math.cos(el) * Math.cos(az));
  cam.lookAt(0, 0, 0);
  r.render(s, cam);
};
window.ready = true;
</script></body>`;

let rendered = 0;
if (toRender.length > 0) {
  const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
  page.on('pageerror', (e) => console.error('pageerror', e.message));
  await page.setContent(html);
  await page.waitForFunction('window.ready', null, { timeout: 30000 });
  for (const { name, mesh } of toRender) {
    fs.mkdirSync(path.join(outDir, name), { recursive: true });
    for (let i = 0; i < views; i++) {
      const az = 45 + i * 360 / views;
      await page.evaluate(({ d, a, e }) => window.renderView(d, a, e), { d: mesh, a: az, e: 25 });
      await page.locator('canvas').screenshot({ path: viewPath(name, i) });
    }
    rendered++;
  }
  await browser.close();
}

fs.writeFileSync(path.join(outDir, 'skipped.json'), JSON.stringify(skipped, null, 2) + '\n');
console.log(`rendered ${rendered}, skipped ${skipped.length}, already done ${already}`);
