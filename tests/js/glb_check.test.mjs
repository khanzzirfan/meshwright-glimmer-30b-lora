import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { makeGlb } from './glb_util.mjs';
import { parseGlb } from '../../scripts/glb_check.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = path.join(ROOT, 'scripts', 'glb_check.mjs');

function jsonChunk(buf) {
  const len = buf.readUInt32LE(12);
  return JSON.parse(buf.subarray(20, 20 + len).toString('utf8'));
}

function accessorBbox(glb) {
  const json = jsonChunk(glb);
  let min = null;
  let max = null;
  for (const mesh of json.meshes ?? []) {
    for (const prim of mesh.primitives ?? []) {
      const accessor = json.accessors[prim.attributes.POSITION];
      if (min === null) {
        min = accessor.min.slice();
        max = accessor.max.slice();
      } else {
        for (let i = 0; i < 3; i++) {
          min[i] = Math.min(min[i], accessor.min[i]);
          max[i] = Math.max(max[i], accessor.max[i]);
        }
      }
    }
  }
  return { min, max, size: max.map((v, i) => v - min[i]) };
}

test('one indexed triangle', () => {
  const glb = makeGlb({ triangles: 1, indexed: true });
  const result = parseGlb(glb);
  assert.equal(result.ok, true);
  assert.equal(result.reason, null);
  assert.equal(result.bytes, glb.length);
  assert.equal(result.version, 2);
  assert.equal(result.meshes, 1);
  assert.equal(result.primitives, 1);
  assert.equal(result.triangles, 1);
  assert.equal(result.vertices, 3);
  assert.equal(result.nodes, 1);
  assert.equal(result.animations, 0);
});

test('twelve triangles indexed and non-indexed', () => {
  const indexed = parseGlb(makeGlb({ triangles: 12, indexed: true }));
  assert.equal(indexed.triangles, 12);
  assert.equal(indexed.vertices, 36);

  const plain = parseGlb(makeGlb({ triangles: 12, indexed: false }));
  assert.equal(plain.triangles, 12);
  assert.equal(plain.vertices, 36);
});

test('three meshes, two per mesh', () => {
  const result = parseGlb(makeGlb({ triangles: 2, meshes: 3 }));
  assert.equal(result.meshes, 3);
  assert.equal(result.primitives, 3);
  assert.equal(result.nodes, 3);
  assert.equal(result.triangles, 6);
  assert.equal(result.vertices, 18);
});

test('animations are counted', () => {
  const result = parseGlb(makeGlb({ triangles: 1, animations: 2 }));
  assert.equal(result.ok, true);
  assert.equal(result.animations, 2);
});

test('bbox equals the union of the accessor min/max makeGlb wrote', () => {
  const glb = makeGlb({ triangles: 2, meshes: 3 });
  const result = parseGlb(glb);
  assert.deepEqual(result.bbox, accessorBbox(glb));
  assert.deepEqual(result.bbox, { min: [0, 0, 0], max: [25, 1, 2], size: [25, 1, 2] });
});

test('bad GLBs report bad_glb without throwing', () => {
  const broken = {
    magic: makeGlb({ triangles: 1, badMagic: true }),
    version: makeGlb({ triangles: 1, version: 1 }),
    truncated: makeGlb({ triangles: 1, truncate: true }),
    random: crypto.randomBytes(64),
  };
  for (const [name, glb] of Object.entries(broken)) {
    let result;
    assert.doesNotThrow(() => { result = parseGlb(glb); }, name);
    assert.equal(result.ok, false, name);
    assert.equal(result.reason, 'bad_glb', name);
  }
});

test('zero triangles and zero meshes are empty_glb', () => {
  const noTris = parseGlb(makeGlb({ triangles: 0 }));
  assert.equal(noTris.ok, false);
  assert.equal(noTris.reason, 'empty_glb');
  assert.equal(noTris.triangles, 0);

  const noMeshes = parseGlb(makeGlb({ meshes: 0 }));
  assert.equal(noMeshes.ok, false);
  assert.equal(noMeshes.reason, 'empty_glb');
  assert.equal(noMeshes.meshes, 0);
});

test('CLI prints one JSON line and exits 0 for ok, 1 for bad_glb', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'glb-check-'));
  try {
    const good = path.join(tmp, 'good.glb');
    fs.writeFileSync(good, makeGlb({ triangles: 1 }));
    const goodRun = spawnSync(process.execPath, [SCRIPT, good], { encoding: 'utf8' });
    assert.equal(goodRun.status, 0);
    const goodLines = goodRun.stdout.trim().split('\n');
    assert.equal(goodLines.length, 1);
    assert.equal(JSON.parse(goodLines[0]).ok, true);

    const badFile = path.join(tmp, 'bad.glb');
    fs.writeFileSync(badFile, makeGlb({ badMagic: true }));
    const badRun = spawnSync(process.execPath, [SCRIPT, badFile], { encoding: 'utf8' });
    assert.equal(badRun.status, 1);
    const badLines = badRun.stdout.trim().split('\n');
    assert.equal(badLines.length, 1);
    assert.equal(JSON.parse(badLines[0]).reason, 'bad_glb');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('importing the module prints nothing and does not exit', () => {
  const run = spawnSync(
    process.execPath,
    ['--input-type=module', '-e', `await import(${JSON.stringify(pathToFileURL(SCRIPT).href)});`],
    { encoding: 'utf8' },
  );
  assert.equal(run.status, 0);
  assert.equal(run.stdout, '');
  assert.equal(run.stderr, '');
});

test('glb_check.mjs imports only node: built-ins', () => {
  const source = fs.readFileSync(SCRIPT, 'utf8');
  const specs = [...source.matchAll(/^\s*import\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]/gm)].map((m) => m[1]);
  assert.ok(specs.length > 0);
  assert.deepEqual(specs.filter((s) => !s.startsWith('node:')), []);
});
