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
  let emptyCache;
  try {
    emptyCache = fs.mkdtempSync(path.join(os.tmpdir(), 'no-three-'));
    runResult = run(rawDir, ['--mode', 'glb', '--glb-dir', glbDir, '--three-versions-dir', emptyCache]);
    const rows = new Map(runResult.rows.map((row) => [row.id, row]));

    for (const id of ['g_ok', 'g_unpkg', 'g_anim', 'g_bare']) {
      const row = rows.get(id);
      assert.ok(row, `missing report row for ${id}`);
      assert.equal(row.ok, true, `${id} should pass: ${JSON.stringify(row.reasons)}`);
      assert.deepEqual(row.reasons, []);
      assert.ok(fs.existsSync(path.join(glbDir, id + '.glb')), `${id}.glb not written`);
      // US-002: the validator adds a kind-aware assembly to stats.glb without touching the reasons.
      assert.equal(typeof row.stats.glb.assembly, 'object', `${id} is missing stats.glb.assembly`);
      assert.equal(row.stats.glb.assembly.parts, 1);
      assert.equal(row.stats.glb.assembly.assembled, true);
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
    if (emptyCache) fs.rmSync(emptyCache, { recursive: true, force: true });
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

test('--allow-addons accepts a Three.js add-on, and records it, only when asked', { timeout: 180000 }, () => {
  const rawDir = fs.mkdtempSync(path.join(os.tmpdir(), 'addon-raw-'));
  const glbDir = fs.mkdtempSync(path.join(os.tmpdir(), 'addon-glb-'));
  fs.copyFileSync(path.join(GLB_FIXTURES, 'g_addon.json'), path.join(rawDir, 'g_addon.json'));
  const results = [];
  try {
    const strict = run(rawDir, ['--mode', 'glb', '--glb-dir', glbDir]);
    results.push(strict);
    assert.ok(strict.rows[0].reasons.includes('bad_import'), JSON.stringify(strict.rows[0].reasons));
    const open = run(rawDir, ['--mode', 'glb', '--glb-dir', glbDir, '--allow-addons']);
    results.push(open);
    assert.equal(open.rows[0].ok, true, JSON.stringify(open.rows[0].reasons));
    assert.deepEqual(open.rows[0].stats.addons, ['controls/OrbitControls.js']);
    assert.deepEqual(open.requests, [], 'a page reached the network');
  } finally {
    fs.rmSync(rawDir, { recursive: true, force: true });
    fs.rmSync(glbDir, { recursive: true, force: true });
    for (const r of results) fs.rmSync(r.tmp, { recursive: true, force: true });
  }
});

test('a page gets the Three.js version it asked for when it is cached', { timeout: 180000 }, () => {
  const rawDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ver-raw-'));
  const glbDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ver-glb-'));
  const cache = fs.mkdtempSync(path.join(os.tmpdir(), 'ver-cache-'));
  fs.copyFileSync(path.join(GLB_FIXTURES, 'g_unpkg.json'), path.join(rawDir, 'g_unpkg.json')); // asks for three@0.165.0
  // a fake 0.165.0 release: the real files under a version folder, so the page loads without the network
  const pkg = path.join(ROOT, 'node_modules', 'three');
  fs.mkdirSync(path.join(cache, '0.165.0'));
  fs.symlinkSync(path.join(pkg, 'build'), path.join(cache, '0.165.0', 'build'));
  fs.symlinkSync(path.join(pkg, 'examples'), path.join(cache, '0.165.0', 'examples'));
  const results = [];
  try {
    const cached = run(rawDir, ['--mode', 'glb', '--glb-dir', glbDir, '--three-versions-dir', cache]);
    results.push(cached);
    const row = cached.rows[0];
    assert.equal(row.ok, true, JSON.stringify(row.reasons));
    assert.equal(row.stats.three_requested, '0.165.0');
    assert.equal(row.stats.three_served, '0.165.0');
    assert.equal(row.stats.version_rewritten, undefined, 'a cached version must not be flagged as rewritten');
    const empty = fs.mkdtempSync(path.join(os.tmpdir(), 'ver-empty-'));
    try {
      const fallback = run(rawDir, ['--mode', 'glb', '--glb-dir', glbDir, '--three-versions-dir', empty]);
      results.push(fallback);
      assert.equal(fallback.rows[0].stats.three_served, '0.160.0');
      assert.equal(fallback.rows[0].stats.version_rewritten, true);
    } finally { fs.rmSync(empty, { recursive: true, force: true }); }
  } finally {
    for (const d of [rawDir, glbDir, cache]) fs.rmSync(d, { recursive: true, force: true });
    for (const r of results) fs.rmSync(r.tmp, { recursive: true, force: true });
  }
});
