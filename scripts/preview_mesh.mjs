// Render converted text meshes (data/mesh/assets.jsonl) to a contact sheet PNG, to eyeball the conversion.
// usage: node scripts/preview_mesh.mjs --in data/mesh/assets.jsonl --out data/mesh/preview.png --names q-chair-1,van,...  (or --n 24)
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };
const rows = fs.readFileSync(arg('in', 'data/mesh/assets.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
const names = arg('names', '').split(',').filter(Boolean);
const n = +arg('n', 24);
const pick = names.length ? names.map(x => rows.find(r => r.name === x)).filter(Boolean)
  : rows.filter((_, i) => i % Math.max(1, Math.floor(rows.length / n)) === 0).slice(0, n);
const three = fs.readFileSync('node_modules/three/build/three.module.js', 'utf8');

const html = `<body style="margin:0;background:#222"><canvas id=c></canvas><script type=module>
import * as T from 'data:text/javascript;base64,${Buffer.from(three).toString('base64')}';
const items = ${JSON.stringify(pick.map(r => ({ name: r.name, text: r.text })))};
const cols = 6, cell = 220, rowsN = Math.ceil(items.length / cols);
const r = new T.WebGLRenderer({ canvas: c, antialias: true, preserveDrawingBuffer: true });
r.setSize(cols * cell, rowsN * cell); r.setScissorTest(true);
const cam = new T.PerspectiveCamera(35, 1, 0.1, 10); cam.position.set(2.0, 1.5, 2.0); cam.lookAt(0, 0.5, 0);
items.forEach((it, i) => {
  const verts = [], groups = []; let cur = null;
  for (const ln of it.text.split('\\n')) {
    const p = ln.split(' ');
    if (p[0] === 'v') verts.push(p.slice(1).map(x => x / 63 - 0.5));
    else if (p[0] === 'c') { cur = { col: p[1], idx: [] }; groups.push(cur); }
    else if (p[0] === 'f') cur.idx.push(...p.slice(1).map(x => x - 1));
  }
  const s = new T.Scene(); s.background = new T.Color(0x2b2b2b);
  s.add(new T.HemisphereLight(0xffffff, 0x444455, 1.6)); const d = new T.DirectionalLight(0xffffff, 1.8); d.position.set(2, 3, 1); s.add(d);
  for (const g of groups) {
    const geo = new T.BufferGeometry(); geo.setAttribute('position', new T.Float32BufferAttribute(verts.flat(), 3));
    geo.setIndex(g.idx); geo.computeVertexNormals();
    s.add(new T.Mesh(geo, new T.MeshStandardMaterial({ color: g.col, flatShading: true, side: T.DoubleSide })));
  }
  const x = (i % cols) * cell, y = (rowsN - 1 - Math.floor(i / cols)) * cell;
  r.setViewport(x, y, cell, cell); r.setScissor(x, y, cell, cell); r.render(s, cam);
});
window.done = true;
</script></body>`;

const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const pg = await b.newPage({ viewport: { width: 6 * 220, height: Math.ceil(pick.length / 6) * 220 } });
pg.on('pageerror', e => console.error('pageerror', e.message));
await pg.setContent(html);
await pg.waitForFunction('window.done', null, { timeout: 30000 });
const out = arg('out', 'data/mesh/preview.png');
fs.mkdirSync(path.dirname(out), { recursive: true });
await pg.locator('canvas').screenshot({ path: out });
await b.close();
console.log('wrote', out, pick.map(r => r.name).join(' '));
