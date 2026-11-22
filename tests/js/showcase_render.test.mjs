// Chromium tests for the studio renderer's new --plinth / --aspect / --offset-x flags (docs/15, promo-1 US-001).
// The default path (plinth none, 1:1, offset 0) must be byte-identical to the render before the flags existed.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';
import { makeGlb } from './glb_util.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = path.join(ROOT, 'scripts', 'showcase_render.mjs');
const PNG_SIG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

// A makeGlb two-box asset. Its synthetic faces are single back-facing triangles from the 3/4 studio camera,
// so "no plinth" frames an empty image and any opaque pixels come from the plinth under test.
const BOXES = [
  { min: [-0.6, 0, -0.4], max: [0.6, 1.2, 0.4] },
  { min: [0.6, 0, -0.4], max: [1.4, 0.6, 0.4] },
];

function makeAsset(dir) {
  const file = path.join(dir, 'two-box.glb');
  fs.writeFileSync(file, makeGlb({ meshes: 2, indexed: false, boxes: BOXES, nodes: [{ mesh: 0 }, { mesh: 1 }] }));
  return file;
}

function render(glb, out, extra = []) {
  execFileSync(process.execPath, [SCRIPT, '--glb', glb, '--out', out, '--size', '256', ...extra], { cwd: ROOT, encoding: 'utf8', timeout: 180000 });
}

function decodePng(file) {
  const buf = fs.readFileSync(file);
  assert.ok(buf.subarray(0, 8).equals(PNG_SIG), `${file} is not a PNG`);
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
  assert.equal(bitDepth, 8, 'expected an 8-bit PNG');
  assert.equal(interlace, 0, 'expected a non-interlaced PNG');
  const channels = colorType === 6 ? 4 : colorType === 2 ? 3 : colorType === 0 ? 1 : 0;
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

function opaqueInBottomBand(file, frac = 0.3) {
  const img = decodePng(file);
  const from = Math.floor(img.height * (1 - frac));
  let n = 0;
  for (let y = from; y < img.height; y++) {
    for (let x = 0; x < img.width; x++) if (img.data[y * img.stride + x * img.channels + 3] > 250) n++;
  }
  return { n, img };
}

test('showcase_render: the default path is byte-identical with and without the new flags', { timeout: 240000 }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'showcase-render-default-'));
  try {
    const glb = makeAsset(tmp);
    // Three ways to ask for the old output: no new flags, --plinth none, and every new flag at its default.
    render(glb, path.join(tmp, 'plain'));
    render(glb, path.join(tmp, 'none'), ['--plinth', 'none']);
    render(glb, path.join(tmp, 'defaults'), ['--plinth', 'none', '--plinth-color', '0x9ccf7a', '--plinth-side', '0x8a5a3c', '--aspect', '1:1', '--offset-x', '0']);
    const plain = fs.readFileSync(path.join(tmp, 'plain', 'two-box.png'));
    assert.ok(plain.equals(fs.readFileSync(path.join(tmp, 'none', 'two-box.png'))), '--plinth none changed the default render');
    assert.ok(plain.equals(fs.readFileSync(path.join(tmp, 'defaults', 'two-box.png'))), 'explicit default flags changed the render');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('showcase_render: --plinth round changes the image and adds an opaque base', { timeout: 240000 }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'showcase-render-plinth-'));
  try {
    const glb = makeAsset(tmp);
    const none = path.join(tmp, 'none'), round = path.join(tmp, 'round');
    render(glb, none);
    render(glb, round, ['--plinth', 'round']);
    const noneFile = path.join(none, 'two-box.png');
    assert.ok(!fs.readFileSync(noneFile).equals(fs.readFileSync(path.join(round, 'two-box.png'))), '--plinth round did not change the image');
    const base = opaqueInBottomBand(path.join(round, 'two-box.png'));
    const blank = opaqueInBottomBand(noneFile);
    assert.equal(blank.n, 0, 'the plinthless render already had opaque pixels in the bottom band');
    assert.ok(base.n > 0, 'the plinth render has no opaque pixels in the bottom band');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('showcase_render: --aspect 16:9 renders at --size wide by 9/16 tall', { timeout: 180000 }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'showcase-render-aspect-'));
  try {
    const glb = makeAsset(tmp);
    const out = path.join(tmp, 'wide');
    execFileSync(process.execPath, [SCRIPT, '--glb', glb, '--out', out, '--size', '320', '--aspect', '16:9', '--plinth', 'round'], { cwd: ROOT, encoding: 'utf8', timeout: 180000 });
    const img = decodePng(path.join(out, 'two-box.png'));
    assert.equal(img.width, 320, 'the width must stay --size');
    assert.equal(img.height, 180, 'the height must be size*9/16');
    assert.equal(img.width * 9, img.height * 16, 'the image is not 16:9');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('showcase_render: the usage line documents the new flags and rejects a bad plinth', () => {
  const usage = spawnSync(process.execPath, [SCRIPT], { encoding: 'utf8' });
  assert.equal(usage.status, 2);
  const text = usage.stderr + usage.stdout;
  for (const flag of ['--plinth', '--plinth-color', '--plinth-side', '--aspect', '--offset-x']) {
    assert.ok(text.includes(flag), `usage does not mention ${flag}`);
  }

  const bad = spawnSync(process.execPath, [SCRIPT, '--glb', 'x.glb', '--out', 'y', '--plinth', 'bogus'], { encoding: 'utf8' });
  assert.equal(bad.status, 2);
  assert.match(bad.stderr, /unknown --plinth bogus/);
  assert.ok(bad.stderr.includes('--plinth none|round|square'), 'usage line missing from the error');
});
