// Tests for the 16:9 hero slides (docs/15, promo-1 US-004): `make.mjs --slides` writes 1920x1080 slides from
// slides.json and never touches the published out/ images. The content tests read the real slides.json/meta.json;
// the Chromium test renders a temp slides.json into a temp dir so nothing under release/v1/promo/out/ changes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { makeGlb } from './glb_util.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const MAKE = path.join(ROOT, 'release', 'v1', 'promo', 'make.mjs');
const RENDER = path.join(ROOT, 'scripts', 'showcase_render.mjs');
const PROMO = path.join(ROOT, 'release', 'v1', 'promo');
const SLIDES_FILE = path.join(PROMO, 'slides.json');
const META_FILE = path.join(PROMO, 'meta.json');
const OUT = path.join(PROMO, 'out');

const readSlides = () => JSON.parse(fs.readFileSync(SLIDES_FILE, 'utf8'));
const readMeta = () => JSON.parse(fs.readFileSync(META_FILE, 'utf8'));
const idOfImage = (image) => path.basename(image, '.png');

// The width/height live in the IHDR, right after the 8-byte signature, a length and the 'IHDR' tag.
function pngSize(file) {
  const buf = fs.readFileSync(file);
  assert.ok(buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])), `${file} is not a PNG`);
  assert.equal(buf.toString('ascii', 12, 16), 'IHDR');
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

// Hash every regular file at the top level of out/ (the published images), so a slides run that clobbers one fails.
function hashPublished() {
  const hashes = {};
  for (const name of fs.readdirSync(OUT)) {
    const file = path.join(OUT, name);
    if (!fs.statSync(file).isFile()) continue;
    hashes[name] = createHash('sha1').update(fs.readFileSync(file)).digest('hex');
  }
  return hashes;
}

test('slides: slides.json has six slides, the diorama captions and meta.json-exact prompts', () => {
  const slides = readSlides();
  const meta = readMeta();
  assert.equal(slides.length, 6, 'there must be six slides');

  let dioramas = 0, prompts = 0;
  for (const s of slides) {
    assert.ok(s.name && s.line1 && s.line2, `slide ${s.name} is missing a name or a headline line`);
    assert.ok(s.image, `slide ${s.name} has no image`);
    assert.ok(fs.existsSync(path.resolve(PROMO, s.image)), `slide ${s.name} image is missing: ${s.image}`);

    // The headline copy must not carry a number (no quality claim).
    for (const key of ['kicker', 'line1', 'line2', 'sub']) {
      const text = s[key] || '';
      assert.ok(!/[0-9%]/.test(text), `slide ${s.name} ${key} shows a number: ${JSON.stringify(text)}`);
    }

    if (s.caption) {
      dioramas++;
      assert.ok(s.caption.includes('Arranged by hand'), `slide ${s.name} caption must say "Arranged by hand"`);
    }
    if (s.prompt) {
      prompts++;
      const id = idOfImage(s.image);
      assert.ok(meta[id], `slide ${s.name} prompt has no meta.json entry for ${id}`);
      assert.equal(s.prompt, meta[id].prompt, `slide ${s.name} prompt differs from meta.json[${id}]`);
    }
  }
  assert.equal(dioramas, 2, 'both diorama slides must carry the caption');
  assert.equal(prompts, 4, 'the four asset slides must show their prompt');
});

test('slides: make.mjs renders the caption and the prompt and keeps the published pages', () => {
  const src = fs.readFileSync(MAKE, 'utf8');
  assert.ok(src.includes('s.caption'), 'the slide template must render the caption');
  assert.ok(src.includes('s.prompt'), 'the slide template must render the prompt');
  assert.ok(src.includes('Meshwright v1'), 'the slide template must show the wordmark');
  // The plain run still writes the four published pages.
  for (const name of ['cover_1280x640.png', 'social_1080.png', 'showcase_grid.png', 'how_it_works_1600x640.png']) {
    assert.ok(src.includes(name), `the plain-run pages lost ${name}`);
  }
});

test('slides: --slides writes 1920x1080 slides into the chosen dir and leaves the published images alone', { timeout: 300000 }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'promo-slides-'));
  try {
    const before = hashPublished();
    const glb = path.join(tmp, 'demo.glb');
    fs.writeFileSync(glb, makeGlb({ meshes: 2, indexed: false, boxes: [
      { min: [-0.6, 0, -0.4], max: [0.6, 1.2, 0.4] },
      { min: [0.6, 0, -0.4], max: [1.4, 0.6, 0.4] },
    ], nodes: [{ mesh: 0 }, { mesh: 1 }] }));
    const hero = path.join(tmp, 'renders_hero');
    execFileSync(process.execPath, [RENDER, '--glb', glb, '--out', hero, '--plinth', 'round', '--size', '256'], { cwd: ROOT, encoding: 'utf8', timeout: 240000 });

    const slidesFile = path.join(tmp, 'slides.json');
    fs.writeFileSync(slidesFile, JSON.stringify([
      { name: 'one', kicker: 'TEST', line1: 'ONE.', line2: 'TWO.', sub: 'sub', image: 'renders_hero/demo.png', caption: 'Arranged by hand. Every object generated by Meshwright v1.' },
      { name: 'two', kicker: 'TEST', line1: 'THREE.', line2: 'FOUR.', sub: 'sub', prompt: 'A demo asset.', image: 'renders_hero/demo.png' },
    ]));
    const out = path.join(tmp, 'out');
    const res = spawnSync(process.execPath, [MAKE, '--slides', '--slides-file', slidesFile, '--out', out], { cwd: ROOT, encoding: 'utf8', timeout: 240000 });
    assert.equal(res.status, 0, `make.mjs --slides failed\n${res.stderr}`);

    for (const name of ['01_one.png', '02_two.png']) {
      const file = path.join(out, name);
      assert.ok(fs.existsSync(file), `${name} was not written`);
      const { width, height } = pngSize(file);
      assert.equal(width, 1920, `${name} is not 1920 wide`);
      assert.equal(height, 1080, `${name} is not 1080 tall`);
    }
    assert.deepEqual(fs.readdirSync(out).filter((n) => n.endsWith('.png')).sort(), ['01_one.png', '02_two.png'], 'unexpected slides were written');
    assert.deepEqual(hashPublished(), before, 'the published out/ images changed after a --slides run');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('slides: a missing slides file exits 2 and the usage line documents the flags', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'promo-slides-usage-'));
  try {
    const bad = spawnSync(process.execPath, [MAKE, '--slides', '--slides-file', path.join(tmp, 'nope.json'), '--out', path.join(tmp, 'out')], { cwd: ROOT, encoding: 'utf8', timeout: 120000 });
    assert.equal(bad.status, 2);
    const text = bad.stderr + bad.stdout;
    for (const flag of ['--slides', '--slides-file', '--out']) assert.ok(text.includes(flag), `usage does not mention ${flag}`);
    assert.ok(!fs.existsSync(path.join(tmp, 'out')), 'a missing slides file must not create the output dir');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
