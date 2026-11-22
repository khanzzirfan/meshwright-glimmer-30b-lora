// Chromium tests for the diorama scene composer (docs/15, promo-1 US-002).
// A layout of several makeGlb assets is placed on one plinth and rendered as one scene; overlaps, missing files
// and the --strict switch are asserted, along with the shared studio module showcase_render.mjs also uses.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';
import { makeGlb } from './glb_util.mjs';
import { parseGlb } from '../../scripts/glb_check.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = path.join(ROOT, 'scripts', 'showcase_scene.mjs');
const RENDER = path.join(ROOT, 'scripts', 'showcase_render.mjs');
const COMMON = path.join(ROOT, 'scripts', 'showcase_common.mjs');
const BOXES = [
  { min: [-0.6, 0, -0.4], max: [0.6, 1.2, 0.4] },
  { min: [0.6, 0, -0.4], max: [1.4, 0.6, 0.4] },
];

const boxGlb = () => makeGlb({ meshes: 2, indexed: false, boxes: BOXES, nodes: [{ mesh: 0 }, { mesh: 1 }] });

function writeAsset(dir, name) {
  const file = path.join(dir, name);
  fs.writeFileSync(file, boxGlb());
  return file;
}

function writeLayout(dir, name, layout) {
  const file = path.join(dir, name);
  fs.writeFileSync(file, JSON.stringify(layout));
  return file;
}

// Run the composer and pull the one JSON summary line out of stdout.
function run(args) {
  const res = spawnSync(process.execPath, [SCRIPT, ...args], { cwd: ROOT, encoding: 'utf8', timeout: 240000 });
  const lines = res.stdout.trim().split('\n').filter(Boolean);
  let summary = null;
  for (let i = lines.length - 1; i >= 0 && !summary; i--) {
    try { const o = JSON.parse(lines[i]); if (o && typeof o.items === 'number') summary = o; } catch { /* not the summary */ }
  }
  return { status: res.status, stdout: res.stdout, stderr: res.stderr, summary };
}

function decodePng(file) {
  const buf = fs.readFileSync(file);
  assert.ok(buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])), `${file} is not a PNG`);
  let off = 8, width = 0, height = 0, bitDepth = 0, colorType = 0, interlace = 0;
  const idat = [];
  while (off + 8 <= buf.length) {
    const len = buf.readUInt32BE(off);
    const type = buf.toString('ascii', off + 4, off + 8);
    const data = buf.subarray(off + 8, off + 8 + len);
    if (type === 'IHDR') { width = data.readUInt32BE(0); height = data.readUInt32BE(4); bitDepth = data[8]; colorType = data[9]; interlace = data[12]; }
    else if (type === 'IDAT') idat.push(data);
    else if (type === 'IEND') break;
    off += 12 + len;
  }
  assert.equal(bitDepth, 8);
  assert.equal(interlace, 0);
  const channels = colorType === 6 ? 4 : colorType === 2 ? 3 : 0;
  assert.ok(channels > 0, `unsupported PNG colour type ${colorType}`);
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const stride = width * channels;
  const out = Buffer.alloc(height * stride);
  let p = 0;
  for (let y = 0; y < height; y++) {
    const filter = raw[p++];
    const rowStart = y * stride;
    for (let x = 0; x < stride; x++) {
      const rb = raw[p++];
      const a = x >= channels ? out[rowStart + x - channels] : 0;
      const b = y > 0 ? out[rowStart - stride + x] : 0;
      const c = x >= channels && y > 0 ? out[rowStart - stride + x - channels] : 0;
      let v;
      if (filter === 0) v = rb;
      else if (filter === 1) v = rb + a;
      else if (filter === 2) v = rb + b;
      else if (filter === 3) v = rb + ((a + b) >> 1);
      else if (filter === 4) { const pp = a + b - c, pa = Math.abs(pp - a), pb = Math.abs(pp - b), pc = Math.abs(pp - c); v = rb + (pa <= pb && pa <= pc ? a : pb <= pc ? b : c); }
      else throw new Error(`bad PNG filter ${filter}`);
      out[rowStart + x] = v & 0xff;
    }
  }
  return { width, height, channels, data: out, stride };
}

const transparentPixels = (file) => {
  const img = decodePng(file);
  let n = 0;
  for (let i = 3; i < img.data.length; i += img.channels) if (img.data[i] < 10) n++;
  return n;
};

test('showcase_scene: three assets render as one scene, 3 items and 0 overlaps', { timeout: 240000 }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'showcase-scene-three-'));
  try {
    const a = writeAsset(tmp, 'a.glb'), b = writeAsset(tmp, 'b.glb'), c = writeAsset(tmp, 'c.glb');
    const layout = writeLayout(tmp, 'village.json', {
      plinth: { shape: 'round', size_m: 12 },
      items: [
        { id: 'a', glb: a, x: -3, z: 0, rot_y_deg: 0 },
        { id: 'b', glb: b, x: 0, z: 0, rot_y_deg: 0 },
        { id: 'c', glb: c, x: 3, z: 0, rot_y_deg: 0 },
      ],
    });
    const out = path.join(tmp, 'out');
    const { status, summary } = run(['--layout', layout, '--out', out, '--width', '320', '--height', '180', '--name', 'village']);
    assert.equal(status, 0, `composer failed\n${JSON.stringify(summary)}`);
    assert.deepEqual(summary, { items: 3, overlaps: 0, missing: 0 });
    const still = decodePng(path.join(out, 'village.png'));
    assert.equal(still.width, 320);
    assert.equal(still.height, 180);
    assert.ok(transparentPixels(path.join(out, 'village.png')) > 0, 'the still should keep a transparent background');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('showcase_scene: two items at the same x/z report 1 overlap and fail with --strict', { timeout: 240000 }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'showcase-scene-overlap-'));
  try {
    const a = writeAsset(tmp, 'a.glb');
    const layout = writeLayout(tmp, 'overlap.json', {
      plinth: { shape: 'square', size_m: 8 },
      items: [
        { id: 'one', glb: a, x: 0, z: 0, rot_y_deg: 0 },
        { id: 'two', glb: a, x: 0, z: 0, rot_y_deg: 0 },
      ],
    });
    const out = path.join(tmp, 'out');
    const lenient = run(['--layout', layout, '--out', out, '--width', '320', '--height', '180']);
    assert.equal(lenient.status, 0, 'without --strict an overlap should only warn');
    assert.equal(lenient.summary.overlaps, 1);
    assert.match(lenient.stderr, /overlap: one two area=/);

    const strictOut = path.join(tmp, 'out-strict');
    const strictRun = run(['--layout', layout, '--out', strictOut, '--width', '320', '--height', '180', '--strict']);
    assert.equal(strictRun.status, 1, '--strict must fail on an overlap');
    assert.equal(strictRun.summary.overlaps, 1);
    assert.ok(!fs.existsSync(path.join(strictOut, 'overlap.png')), '--strict must not render on an overlap');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('showcase_scene: a missing GLB fails naming its path', { timeout: 120000 }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'showcase-scene-missing-'));
  try {
    const gone = path.join(tmp, 'does-not-exist.glb');
    const layout = writeLayout(tmp, 'missing.json', {
      plinth: { shape: 'round', size_m: 8 },
      items: [{ id: 'gone', glb: gone, x: 0, z: 0, rot_y_deg: 0 }],
    });
    const out = path.join(tmp, 'out');
    const { status, stderr, summary } = run(['--layout', layout, '--out', out, '--width', '320', '--height', '180']);
    assert.equal(status, 1);
    assert.equal(summary.missing, 1);
    assert.ok(stderr.includes(gone), 'the error must name the missing path');
    assert.ok(!fs.existsSync(path.join(out, 'missing.png')), 'a missing GLB must not render');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('showcase_scene: --frames 4 writes 4 orbit frames', { timeout: 240000 }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'showcase-scene-frames-'));
  try {
    const a = writeAsset(tmp, 'a.glb'), b = writeAsset(tmp, 'b.glb');
    const layout = writeLayout(tmp, 'orbit.json', {
      plinth: { shape: 'round', size_m: 10 },
      items: [
        { id: 'a', glb: a, x: -2.5, z: 0, rot_y_deg: 0 },
        { id: 'b', glb: b, x: 2.5, z: 0, rot_y_deg: 0 },
      ],
    });
    const out = path.join(tmp, 'out');
    const { status } = run(['--layout', layout, '--out', out, '--width', '320', '--height', '180', '--frames', '4', '--name', 'orbit']);
    assert.equal(status, 0);
    for (let i = 0; i < 4; i++) {
      assert.ok(fs.existsSync(path.join(out, 'orbit_orbit', String(i).padStart(4, '0') + '.png')), `frame ${i} missing`);
    }
    assert.ok(!fs.existsSync(path.join(out, 'orbit_orbit', '0004.png')), 'more than 4 frames were written');
    const first = fs.readFileSync(path.join(out, 'orbit_orbit', '0000.png'));
    assert.ok(!first.equals(fs.readFileSync(path.join(out, 'orbit_orbit', '0002.png'))), 'the orbit did not move the camera');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('showcase_scene: placing a GLB does not modify its geometry or materials', { timeout: 240000 }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'showcase-scene-intact-'));
  try {
    const glb = writeAsset(tmp, 'a.glb');
    const before = fs.readFileSync(glb);
    assert.deepEqual({ meshes: parseGlb(before).meshes, materials: parseGlb(before).materials }, { meshes: 2, materials: 1 });
    const layout = writeLayout(tmp, 'one.json', {
      plinth: { shape: 'round', size_m: 6 },
      items: [{ id: 'a', glb, x: 0, z: 0, rot_y_deg: 45, scale: 2 }],
    });
    const { status } = run(['--layout', layout, '--out', path.join(tmp, 'out'), '--width', '256', '--height', '256']);
    assert.equal(status, 0);
    const after = fs.readFileSync(glb);
    assert.ok(before.equals(after), 'the GLB on disk changed after placing it');
    const parsed = parseGlb(after);
    assert.equal(parsed.meshes, 2, 'the placed GLB lost or gained meshes');
    assert.equal(parsed.materials, 1, 'the placed GLB lost or gained materials');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('showcase_scene: the shared studio module holds the lighting both renderers use', () => {
  const common = fs.readFileSync(COMMON, 'utf8');
  const render = fs.readFileSync(RENDER, 'utf8');
  const scene = fs.readFileSync(SCRIPT, 'utf8');
  for (const fn of ['createStudioRenderer', 'addStudioLights', 'addContactShadow', 'makePlinth']) {
    assert.ok(common.includes('export function ' + fn), `showcase_common.mjs does not export ${fn}`);
    assert.ok(render.includes('ST.' + fn) || render.includes('ST.makePlinth'), `showcase_render.mjs does not use ${fn}`);
    assert.ok(scene.includes('ST.' + fn) || scene.includes('ST.makePlinth'), `showcase_scene.mjs does not use ${fn}`);
  }
  for (const src of [render, scene]) {
    assert.ok(src.includes('showcase_common.js'), 'a renderer does not import the shared studio module');
    assert.ok(!src.includes('HemisphereLight'), 'the studio lights are copied instead of imported');
    assert.ok(!src.includes('ExtrudeGeometry'), 'the plinth geometry is copied instead of imported');
  }
});

test('showcase_scene: the usage line documents the flags and rejects a bad plinth', () => {
  const usage = spawnSync(process.execPath, [SCRIPT], { encoding: 'utf8' });
  assert.equal(usage.status, 2);
  const text = usage.stderr + usage.stdout;
  for (const flag of ['--layout', '--out', '--width', '--height', '--frames', '--name', '--strict']) {
    assert.ok(text.includes(flag), `usage does not mention ${flag}`);
  }

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'showcase-scene-usage-'));
  try {
    const layout = writeLayout(tmp, 'bad.json', { plinth: { shape: 'hexagon', size_m: 6 }, items: [] });
    const bad = spawnSync(process.execPath, [SCRIPT, '--layout', layout, '--out', path.join(tmp, 'out')], { encoding: 'utf8' });
    assert.equal(bad.status, 2);
    assert.match(bad.stderr, /shape: round\|square/);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('showcase_scene: a harbour water half renders blue at the front, land green behind', { timeout: 240000 }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'showcase-scene-water-'));
  try {
    const a = writeAsset(tmp, 'a.glb');
    const layout = writeLayout(tmp, 'harbour.json', {
      plinth: { shape: 'square', size_m: 8 },
      camera: { yaw: 30, pitch: 28, fov: 30, zoom: 1.6 },
      water: { color: '0x5aa0d8', side: 'front', drop_m: 0.01 },
      items: [
        { id: 'land', glb: a, x: 0, z: -2, rot_y_deg: 0 },
        { id: 'boat', glb: a, x: 0, z: 2, rot_y_deg: 0, on_water: true },
      ],
    });
    const out = path.join(tmp, 'out');
    const { status, summary } = run(['--layout', layout, '--out', out, '--width', '320', '--height', '180', '--name', 'harbour']);
    assert.equal(status, 0, `composer failed\n${JSON.stringify(summary)}`);
    assert.deepEqual(summary, { items: 2, overlaps: 0, missing: 0 });
    const img = decodePng(path.join(out, 'harbour.png'));
    const counts = (y0, y1) => {
      let blue = 0, green = 0;
      for (let y = y0; y < y1; y++) for (let x = 0; x < img.width; x++) {
        const i = y * img.stride + x * img.channels;
        if (img.data[i + 3] < 40) continue;
        const r = img.data[i], g = img.data[i + 1], b = img.data[i + 2];
        if (b > r + 15 && b >= g) blue++; else if (g > r + 8 && g >= b) green++;
      }
      return { blue, green };
    };
    const top = counts(0, Math.floor(img.height / 3));
    const bottom = counts(Math.floor((2 * img.height) / 3), img.height);
    assert.ok(bottom.blue > bottom.green, `the water half (front) should be blue: ${JSON.stringify(bottom)}`);
    assert.ok(top.green > top.blue, `the land half (back) should be green: ${JSON.stringify(top)}`);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('showcase_scene: water needs a square plinth', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'showcase-scene-water-bad-'));
  try {
    const a = writeAsset(tmp, 'a.glb');
    const layout = writeLayout(tmp, 'bad.json', {
      plinth: { shape: 'round', size_m: 8 },
      water: { color: '0x5aa0d8' },
      items: [{ id: 'a', glb: a, x: 0, z: 0, rot_y_deg: 0 }],
    });
    const bad = spawnSync(process.execPath, [SCRIPT, '--layout', layout, '--out', path.join(tmp, 'out')], { encoding: 'utf8' });
    assert.equal(bad.status, 2);
    assert.match(bad.stderr, /needs plinth\.shape 'square'/);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
