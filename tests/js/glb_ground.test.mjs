import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { makeGlb } from './glb_util.mjs';
import { parseGlb } from '../../scripts/glb_check.mjs';
import { groundGlb } from '../../scripts/glb_ground.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = path.join(ROOT, 'scripts', 'glb_ground.mjs');

const near = (a, b) => Math.abs(a - b) < 1e-6;

function jsonOf(glb) {
  const len = glb.readUInt32LE(12);
  return JSON.parse(glb.subarray(20, 20 + len).toString('utf8'));
}

const hovering = () => [{ min: [0, 5, 0], max: [1, 6, 1] }, { min: [1, 5, 0], max: [2, 6, 1] }];

test('a hovering two-part asset is dropped so its lowest point is on the ground', () => {
  const glb = makeGlb({ triangles: 1, indexed: false, meshes: 2, boxes: hovering(), nodes: [{ mesh: 0 }, { mesh: 1 }] });
  const r = groundGlb(glb, { kind: 'static' });
  assert.equal(r.assembly_before.assembled, false, 'hovering is not assembled before');
  assert.ok(near(r.assembly_before.min_y, 5));
  assert.ok(near(r.shift, -5));
  assert.equal(r.assembly_after.assembled, true);
  assert.equal(r.assembly_after.ground_gap, 0);
  assert.ok(near(r.assembly_after.min_y, 0));
  assert.equal(r.assembly_after.parts, 2);
});

test('a sunk asset is lifted to the ground', () => {
  const glb = makeGlb({ triangles: 1, indexed: false, meshes: 1, boxes: [{ min: [0, -2, 0], max: [1, -1, 1] }], nodes: [{ mesh: 0 }] });
  const r = groundGlb(glb, { kind: 'static' });
  assert.ok(near(r.assembly_before.min_y, -2));
  assert.ok(near(r.shift, 2));
  assert.ok(near(r.assembly_after.min_y, 0));
  assert.equal(r.assembly_after.ground_gap, 0);
  assert.equal(r.assembly_after.assembled, true);
});

test('an already grounded asset is returned byte-identical', () => {
  const glb = makeGlb({ triangles: 1, indexed: false, meshes: 1, boxes: [{ min: [0, 0, 0], max: [1, 1, 1] }], nodes: [{ mesh: 0 }] });
  const r = groundGlb(glb, { kind: 'static' });
  assert.equal(r.shift, 0);
  assert.strictEqual(r.buf, glb);
  assert.strictEqual(r.assembly_after, r.assembly_before);
  assert.deepEqual(r.buf, glb);
});

test('the grounded GLB still parses ok with the same triangle count', () => {
  const glb = makeGlb({ triangles: 4, indexed: true, meshes: 2, boxes: hovering(), nodes: [{ mesh: 0 }, { mesh: 1 }] });
  const before = parseGlb(glb);
  const r = groundGlb(glb, { kind: 'static' });
  const after = parseGlb(r.buf);
  assert.equal(after.ok, true);
  assert.equal(after.reason, null);
  assert.equal(after.triangles, before.triangles);
  assert.equal(after.meshes, before.meshes);
  assert.equal(after.nodes, before.nodes + 1, 'one ground_offset node is added');
});

test('an animated asset keeps its channel target indices and adds one node', () => {
  const glb = makeGlb({
    triangles: 1,
    indexed: false,
    meshes: 2,
    animations: 1,
    boxes: hovering(),
    nodes: [{ mesh: 0 }, { mesh: 1 }],
  });
  const beforeJson = jsonOf(glb);
  const beforeTargets = beforeJson.animations[0].channels.map((c) => c.target.node);

  const r = groundGlb(glb, { kind: 'animated' });
  const json = jsonOf(r.buf);
  assert.ok(near(r.shift, -5));
  assert.equal(json.animations.length, 1);
  assert.deepEqual(json.animations[0].channels.map((c) => c.target.node), beforeTargets, 'channel targets do not move');
  assert.deepEqual(json.nodes[0], { mesh: 0 }, 'existing node indices are unchanged');
  assert.equal(json.nodes.length, beforeJson.nodes.length + 1);
  const added = json.nodes[json.nodes.length - 1];
  assert.deepEqual(added, { name: 'ground_offset', translation: [0, -5, 0], children: [0, 1] });
  assert.deepEqual(json.scenes[0].nodes, [json.nodes.length - 1], 'the ground node is the only root');
  const parsed = parseGlb(r.buf);
  assert.equal(parsed.ok, true);
  assert.equal(parsed.animations, 1);
  assert.equal(parsed.triangles, parseGlb(glb).triangles);
});

test('the CLI writes the grounded GLB and prints one JSON line', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'glb-ground-'));
  try {
    const inFile = path.join(tmp, 'in.glb');
    const outFile = path.join(tmp, 'out.glb');
    const input = makeGlb({ triangles: 2, indexed: true, meshes: 2, boxes: hovering(), nodes: [{ mesh: 0 }, { mesh: 1 }] });
    fs.writeFileSync(inFile, input);

    const stdout = execFileSync(process.execPath, [SCRIPT, '--in', inFile, '--out', outFile, '--kind', 'static'], { encoding: 'utf8' });
    const lines = stdout.trim().split('\n');
    assert.equal(lines.length, 1);
    const line = JSON.parse(lines[0]);
    assert.ok(near(line.shift, -5));
    assert.equal(line.assembly_after.assembled, true);
    assert.equal(line.assembly_after.ground_gap, 0);

    const written = parseGlb(fs.readFileSync(outFile));
    assert.equal(written.ok, true);
    assert.equal(written.triangles, parseGlb(input).triangles);
    assert.equal(written.assembly.assembled, true);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
