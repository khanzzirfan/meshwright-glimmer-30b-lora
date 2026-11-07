import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = path.join(ROOT, 'scripts', 'validate_scenes.mjs');
const GLB_FIXTURES = path.join(ROOT, 'tests', 'fixtures', 'glb_raw');
const SCENE_FIXTURES = path.join(ROOT, 'tests', 'fixtures', 'raw');
const EXPECTED = path.join(GLB_FIXTURES, 'scene_mode_expected.jsonl');

function readRows(file) {
  return fs
    .readFileSync(file, 'utf8')
    .trim()
    .split('\n')
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function run(rawDir, extraArgs = []) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'validate-glb-'));
  const report = path.join(tmp, 'report.jsonl');
  const requestLog = path.join(tmp, 'requests.json');
  try {
    execFileSync(
      process.execPath,
      [
        SCRIPT,
        '--raw',
        rawDir,
        '--scenes',
        path.join(tmp, 'scenes'),
        '--shots',
        path.join(tmp, 'shots'),
        '--report',
        report,
        ...extraArgs,
      ],
      {
        cwd: ROOT,
        encoding: 'utf8',
        timeout: 180000,
        env: { ...process.env, VALIDATE_REQUEST_LOG: requestLog },
      },
    );
    return {
      tmp,
      rows: readRows(report),
      requests: JSON.parse(fs.readFileSync(requestLog, 'utf8')),
    };
  } catch (error) {
    fs.rmSync(tmp, { recursive: true, force: true });
    throw error;
  }
}

test('glb mode exports and checks the downloaded file', { timeout: 180000 }, () => {
  const rawDir = fs.mkdtempSync(path.join(os.tmpdir(), 'glb-raw-'));
  const glbDir = fs.mkdtempSync(path.join(os.tmpdir(), 'glb-out-'));
  for (const name of fs.readdirSync(GLB_FIXTURES)) {
    if (name.endsWith('.json')) fs.copyFileSync(path.join(GLB_FIXTURES, name), path.join(rawDir, name));
  }
  let runResult;
  try {
    runResult = run(rawDir, ['--mode', 'glb', '--glb-dir', glbDir]);
    const rows = new Map(runResult.rows.map((row) => [row.id, row]));

    for (const id of ['g_ok', 'g_unpkg', 'g_anim', 'g_bare']) {
      const row = rows.get(id);
      assert.ok(row, `missing report row for ${id}`);
      assert.equal(row.ok, true, `${id} should pass: ${JSON.stringify(row.reasons)}`);
      assert.deepEqual(row.reasons, []);
      assert.ok(fs.existsSync(path.join(glbDir, id + '.glb')), `${id}.glb not written`);
    }

    assert.equal(rows.get('g_unpkg').stats.version_rewritten, true);
    assert.equal(rows.get('g_unpkg').stats.three_requested, '0.165.0');
    assert.equal(rows.get('g_anim').stats.glb.animations, 1);

    assert.ok(rows.get('g_nobutton').reasons.includes('no_export_button'));
    const thrown = rows.get('g_throws').reasons;
    assert.ok(
      thrown.includes('export_error') || thrown.includes('no_download'),
      `g_throws reasons were ${JSON.stringify(thrown)}`,
    );
    assert.ok(rows.get('g_orbit').reasons.includes('bad_import'));
    assert.ok(rows.get('g_trunc').reasons.includes('truncated'));

    assert.deepEqual(runResult.requests, [], 'a page reached the network');
  } finally {
    fs.rmSync(rawDir, { recursive: true, force: true });
    fs.rmSync(glbDir, { recursive: true, force: true });
    if (runResult) fs.rmSync(runResult.tmp, { recursive: true, force: true });
  }
});

test('scene mode is unchanged on the old fixtures', { timeout: 180000 }, () => {
  const expected = readRows(EXPECTED);
  const runResult = run(SCENE_FIXTURES);
  try {
    const actual = runResult.rows.map(({ id, ok, reasons }) => ({ id, ok, reasons }));
    assert.deepEqual(actual, expected);
    assert.deepEqual(runResult.requests, [], 'a scene-mode page reached the network');
  } finally {
    fs.rmSync(runResult.tmp, { recursive: true, force: true });
  }
});

test('a reply that starts with <html> counts as a page in glb mode only', { timeout: 180000 }, () => {
  const rawDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bare-raw-'));
  const glbDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bare-glb-'));
  fs.copyFileSync(path.join(GLB_FIXTURES, 'g_bare.json'), path.join(rawDir, 'g_bare.json'));
  const results = [];
  try {
    const glb = run(rawDir, ['--mode', 'glb', '--glb-dir', glbDir]);
    results.push(glb);
    assert.equal(glb.rows[0].ok, true, JSON.stringify(glb.rows[0].reasons));
    const scene = run(rawDir);
    results.push(scene);
    assert.ok(scene.rows[0].reasons.includes('no_html'), 'scene mode must keep its old no_html rule');
  } finally {
    fs.rmSync(rawDir, { recursive: true, force: true });
    fs.rmSync(glbDir, { recursive: true, force: true });
    for (const r of results) fs.rmSync(r.tmp, { recursive: true, force: true });
  }
});
