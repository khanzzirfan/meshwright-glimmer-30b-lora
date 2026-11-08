import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { makeGlb } from './glb_util.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = path.join(ROOT, 'scripts', 'glb_assembly.mjs');

// One flat grounded box per entry in `boxes`, positioned by the matching mesh node.
function glb(boxes) {
  return makeGlb({ triangles: 1, indexed: false, meshes: boxes.length, boxes, nodes: boxes.map((_, i) => ({ mesh: i })) });
}

const readLines = (file) =>
  fs.readFileSync(file, 'utf8').trim().split('\n').filter(Boolean).map((line) => JSON.parse(line));
const sha = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

// A run directory with three valid GLBs (assembled static, scattered static, grounded set) and one failed row.
function makeRun(tmp) {
  const run = path.join(tmp, 'run');
  fs.mkdirSync(path.join(run, 'glb'), { recursive: true });
  const glbs = {
    a_ok: glb([{ min: [0, 0, 0], max: [1, 1, 1] }]),
    b_scatter: glb([{ min: [0, 0, 0], max: [1, 1, 1] }, { min: [2, 0, 0], max: [3, 1, 1] }]),
    c_set: glb([{ min: [0, 0, 0], max: [1, 1, 1] }, { min: [2, 0, 0], max: [3, 1, 1] }, { min: [4, 0, 0], max: [5, 1, 1] }]),
  };
  for (const [id, buf] of Object.entries(glbs)) fs.writeFileSync(path.join(run, 'glb', id + '.glb'), buf);
  const validation = [
    { id: 'a_ok', ok: true, reasons: [], stats: {} },
    { id: 'b_scatter', ok: true, reasons: [], stats: {} },
    { id: 'c_set', ok: true, reasons: [], stats: {} },
    { id: 'd_fail', ok: false, reasons: ['no_download'], stats: {} },
  ];
  fs.writeFileSync(path.join(run, 'validation.jsonl'), validation.map((r) => JSON.stringify(r)).join('\n') + '\n');
  const briefs = [
    { id: 'a_ok', kind: 'static' },
    { id: 'b_scatter', kind: 'static' },
    { id: 'c_set', kind: 'set' },
    { id: 'd_fail', kind: 'static' },
  ];
  const briefsFile = path.join(tmp, 'briefs.jsonl');
  fs.writeFileSync(briefsFile, briefs.map((b) => JSON.stringify(b)).join('\n') + '\n');
  return { run, briefsFile };
}

const runCli = (run, briefsFile, extra = []) =>
  execFileSync(process.execPath, [SCRIPT, '--run', run, '--briefs', briefsFile, ...extra], { encoding: 'utf8' });

test('backfill writes assembly.jsonl, prints the summary and leaves validation.jsonl alone', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'glb-assembly-'));
  try {
    const { run, briefsFile } = makeRun(tmp);
    const validation = path.join(run, 'validation.jsonl');
    const before = sha(validation);

    const out = runCli(run, briefsFile);
    assert.equal(out.trim(), 'assembled 2 of 3 valid');
    assert.equal(sha(validation), before, 'validation.jsonl must not be touched');

    const rows = readLines(path.join(run, 'assembly.jsonl'));
    assert.deepEqual(rows.map((r) => r.id), ['a_ok', 'b_scatter', 'c_set', 'd_fail']);
    assert.deepEqual(rows.map((r) => r.kind), ['static', 'static', 'set', 'static']);

    const [a, b, c, d] = rows;
    assert.equal(a.assembly.parts, 1);
    assert.equal(a.assembly.components, 1);
    assert.equal(a.assembly.largest_share, 1);
    assert.equal(a.assembly.floaters, 0);
    assert.equal(a.assembly.ground_gap, 0);
    assert.equal(a.assembly.assembled, true);

    assert.equal(b.assembly.parts, 2);
    assert.equal(b.assembly.components, 2);
    assert.equal(b.assembly.largest_share, 0.5);
    assert.equal(b.assembly.floaters, 0);
    assert.equal(b.assembly.assembled, false);

    assert.equal(c.assembly.parts, 3);
    assert.equal(c.assembly.components, 3);
    assert.ok(Math.abs(c.assembly.largest_share - 1 / 3) < 1e-9);
    assert.equal(c.assembly.floaters, 0);
    assert.equal(c.assembly.assembled, true, 'a grounded set is assembled');

    assert.equal(d.assembly, null);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('--tol-frac widens the touch radius', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'glb-assembly-tol-'));
  try {
    const { run, briefsFile } = makeRun(tmp);
    const out = runCli(run, briefsFile, ['--tol-frac', '1']);
    assert.equal(out.trim(), 'assembled 3 of 3 valid');
    const b = readLines(path.join(run, 'assembly.jsonl')).find((r) => r.id === 'b_scatter');
    assert.equal(b.assembly.components, 1, 'the metre gap is within a 1.0 tolerance');
    assert.equal(b.assembly.assembled, true);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test('a missing brief falls back to kind static', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'glb-assembly-kind-'));
  try {
    const { run, briefsFile } = makeRun(tmp);
    fs.writeFileSync(briefsFile, JSON.stringify({ id: 'a_ok', kind: 'static' }) + '\n');
    runCli(run, briefsFile);
    const rows = readLines(path.join(run, 'assembly.jsonl'));
    assert.deepEqual(rows.map((r) => r.kind), ['static', 'static', 'static', 'static']);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
