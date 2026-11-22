// Tests for the GLB name sanitizer (docs/15 section 7, promo-1 US-008): Blender 5.2 aborts importing a
// GLB whose node/mesh/etc. name ends in ".<long digits>" (std::stoi out_of_range on the duplicate-number
// suffix). sanitizeNames rewrites only those name strings, so the geometry is untouched.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { makeGlb } from './glb_util.mjs';
import { parseGlb } from '../../scripts/glb_check.mjs';
import { sanitizeName, sanitizeNames } from '../../scripts/glb_names.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = path.join(ROOT, 'scripts', 'glb_names.mjs');

function jsonOf(glb) {
  const len = glb.readUInt32LE(12);
  return JSON.parse(glb.subarray(20, 20 + len).toString('utf8'));
}

const run = (args) => execFileSync(process.execPath, [SCRIPT, ...args], { encoding: 'utf8' });

test('the two reported names are rewritten as stated', () => {
  const glb = makeGlb({
    triangles: 1,
    indexed: false,
    meshes: 2,
    nodes: [
      { mesh: 0, name: 'sack_0.5_1.0499999999999998' },
      { mesh: 1, name: 'bed_plank_0.09999999999999998' },
    ],
  });

  const r = sanitizeNames(glb);
  const json = jsonOf(r.buf);
  assert.equal(json.nodes[0].name, 'sack_0.5_1.05');
  assert.equal(json.nodes[1].name, 'bed_plank_0.1');
  assert.deepEqual(r.renamed, [
    { kind: 'node', index: 0, from: 'sack_0.5_1.0499999999999998', to: 'sack_0.5_1.05' },
    { kind: 'node', index: 1, from: 'bed_plank_0.09999999999999998', to: 'bed_plank_0.1' },
  ]);
});

test('names with at most three fractional digits are returned byte-identical', () => {
  const glb = makeGlb({
    triangles: 1,
    indexed: false,
    meshes: 2,
    nodes: [
      { mesh: 0, name: 'dormer_-3.5' },
      { mesh: 1, name: 'window_frame_2.2_2.8' },
    ],
  });

  const r = sanitizeNames(glb);
  assert.strictEqual(r.buf, glb, 'a GLB with no change is the same buffer');
  assert.deepEqual(r.renamed, []);
});

test('a name ending in a long dot-suffixed integer gets "_" instead of "."', () => {
  const glb = makeGlb({ triangles: 1, indexed: false, meshes: 1, nodes: [{ mesh: 0, name: 'root_sack.12345678901' }] });

  const r = sanitizeNames(glb);
  assert.equal(jsonOf(r.buf).nodes[0].name, 'root_sack_12345678901');
  // a dot suffix whose value is at most 999999 is a real name and stays
  assert.equal(sanitizeName('root_sack.123456'), 'root_sack.123456');
});

test('a decimal in the middle of a name is left alone (Blender only parses the ending)', () => {
  // measured: runs/imp/distill/x0020 has only mid-name decimals and imports into Blender 5.2 unchanged
  const glb = makeGlb({ triangles: 1, indexed: false, meshes: 1, nodes: [{ mesh: 0, name: 'wall_block_-3.5999999999999996_0' }] });

  const r = sanitizeNames(glb);
  assert.strictEqual(r.buf, glb);
  assert.deepEqual(r.renamed, []);
});

test('a rewrite that collides gets a "_2" suffix, and unchanged names are reserved first', () => {
  const glb = makeGlb({
    triangles: 1,
    indexed: false,
    meshes: 4,
    nodes: [
      { mesh: 0, name: 'part_2.05' },
      { mesh: 1, name: 'part_2.0499999999999998' },
      { mesh: 2, name: 'plank_1.0499999999999998' },
      { mesh: 3, name: 'plank_1.0500000001' },
    ],
  });

  const r = sanitizeNames(glb);
  const json = jsonOf(r.buf);
  assert.equal(json.nodes[0].name, 'part_2.05', 'a clean name stays');
  assert.equal(json.nodes[1].name, 'part_2.05_2', 'a rewrite avoids the reserved clean name');
  assert.equal(json.nodes[2].name, 'plank_1.05');
  assert.equal(json.nodes[3].name, 'plank_1.05_2', 'two rewrites that collide get _2');
  assert.deepEqual(r.renamed.map((e) => e.to), ['part_2.05_2', 'plank_1.05', 'plank_1.05_2']);
});

test('nodes, meshes, materials, animations and scenes are all sanitized', () => {
  const glb = makeGlb({
    triangles: 1,
    indexed: false,
    meshes: 1,
    animations: 1,
    nodes: [{ mesh: 0, name: 'node_1.0499999999999998' }],
    names: {
      meshes: ['mesh_2.0499999999999998'],
      materials: ['mat_3.0499999999999998'],
      animations: ['anim_4.0499999999999998'],
      scenes: ['scene_5.0499999999999998'],
    },
  });

  const r = sanitizeNames(glb);
  const json = jsonOf(r.buf);
  assert.equal(json.nodes[0].name, 'node_1.05');
  assert.equal(json.meshes[0].name, 'mesh_2.05');
  assert.equal(json.materials[0].name, 'mat_3.05');
  assert.equal(json.animations[0].name, 'anim_4.05');
  assert.equal(json.scenes[0].name, 'scene_5.05');
  assert.deepEqual(r.renamed.map((e) => e.kind).sort(), ['animation', 'material', 'mesh', 'node', 'scene']);
});

test('sanitizing keeps parseGlb ok with the same meshes, nodes and triangles', () => {
  const before = parseGlb(makeGlb({ triangles: 4, indexed: true, meshes: 2, nodes: [{ mesh: 0 }, { mesh: 1 }] }));
  const glb = makeGlb({
    triangles: 4,
    indexed: true,
    meshes: 2,
    nodes: [
      { mesh: 0, name: 'a_1.0499999999999998' },
      { mesh: 1, name: 'b' },
    ],
  });

  const r = sanitizeNames(glb);
  const after = parseGlb(r.buf);
  assert.equal(after.ok, true);
  assert.equal(after.reason, null);
  assert.equal(after.triangles, before.triangles);
  assert.equal(after.meshes, before.meshes);
  assert.equal(after.nodes, before.nodes);
});

test('an animated fixture keeps its channel target indices', () => {
  const glb = makeGlb({
    triangles: 1,
    indexed: false,
    meshes: 1,
    animations: 1,
    nodes: [{ mesh: 0, name: 'arm_0.09999999999999998' }],
  });
  const beforeTargets = jsonOf(glb).animations[0].channels.map((c) => c.target.node);

  const r = sanitizeNames(glb);
  const json = jsonOf(r.buf);
  assert.equal(json.nodes[0].name, 'arm_0.1');
  assert.deepEqual(json.animations[0].channels.map((c) => c.target.node), beforeTargets);
  assert.equal(parseGlb(r.buf).animations, 1);
});

test('the CLI writes the sanitized GLB and prints one JSON line', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'glb-names-'));
  try {
    const inFile = path.join(tmp, 'in.glb');
    const outFile = path.join(tmp, 'out.glb');
    fs.writeFileSync(inFile, makeGlb({ triangles: 1, indexed: false, meshes: 1, nodes: [{ mesh: 0, name: 'sack_0.5_1.0499999999999998' }] }));

    const stdout = run(['--in', inFile, '--out', outFile]);

    assert.deepEqual(JSON.parse(stdout.trim()), { renamed: 1 });
    assert.equal(jsonOf(fs.readFileSync(outFile)).nodes[0].name, 'sack_0.5_1.05');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('the CLI rewrites in place so the generator can sanitize a grounded copy', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'glb-names-inplace-'));
  try {
    const file = path.join(tmp, 'asset.glb');
    fs.writeFileSync(file, makeGlb({ triangles: 1, indexed: false, meshes: 1, nodes: [{ mesh: 0, name: 'sack_0.09999999999999998' }] }));

    const stdout = run(['--in', file, '--out', file]);

    assert.deepEqual(JSON.parse(stdout.trim()), { renamed: 1 });
    assert.equal(jsonOf(fs.readFileSync(file)).nodes[0].name, 'sack_0.1');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('--check reports only the files that would change, never writes and exits 0', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'glb-names-check-'));
  try {
    const dirty = path.join(tmp, 'dirty.glb');
    const clean = path.join(tmp, 'clean.glb');
    fs.writeFileSync(dirty, makeGlb({ triangles: 1, indexed: false, meshes: 1, nodes: [{ mesh: 0, name: 'sack_0.09999999999999998' }] }));
    fs.writeFileSync(clean, makeGlb({ triangles: 1, indexed: false, meshes: 1, nodes: [{ mesh: 0, name: 'sack_0.1' }] }));
    const before = fs.readFileSync(dirty);

    // comma-separated (the documented form) ...
    const lines = run(['--check', `${dirty},${clean}`]).trim().split('\n').filter(Boolean);
    assert.equal(lines.length, 1, 'only the dirty file is reported');
    assert.deepEqual(JSON.parse(lines[0]), { file: dirty, renamed: 1 });
    // ... and a shell-expanded list
    const spaced = run(['--check', dirty, clean]).trim().split('\n').filter(Boolean);
    assert.equal(spaced.length, 1);

    assert.deepEqual(fs.readFileSync(dirty), before, '--check never writes');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
