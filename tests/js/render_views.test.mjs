import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = path.join(ROOT, 'scripts', 'render_views.mjs');
const FIXTURE = path.join(ROOT, 'tests', 'fixtures', 'local', 'meshes.jsonl');
const PNG_SIG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function run(args) {
  return execFileSync('node', [SCRIPT, ...args], { cwd: ROOT, encoding: 'utf8' });
}

function pngSize(file) {
  const b = fs.readFileSync(file);
  assert.ok(b.subarray(0, 8).equals(PNG_SIG), `${file} is not a PNG`);
  assert.equal(b.subarray(12, 16).toString('ascii'), 'IHDR');
  return { width: b.readUInt32BE(16), height: b.readUInt32BE(20) };
}

test('render_views renders valid rows, skips broken ones and is resumable', { timeout: 180000 }, () => {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'render-views-'));
  try {
    const first = run(['--in', FIXTURE, '--out-dir', out, '--views', '4', '--size', '224']);

    for (const name of ['cube', 'pyramid']) {
      for (let i = 0; i < 4; i++) {
        const file = path.join(out, name, `view${i}.png`);
        assert.ok(fs.existsSync(file), `missing ${file}`);
        assert.deepEqual(pngSize(file), { width: 224, height: 224 }, `${file} wrong IHDR size`);
      }
    }

    const skipped = JSON.parse(fs.readFileSync(path.join(out, 'skipped.json'), 'utf8'));
    assert.ok(skipped.some((s) => s.name === 'broken'), 'broken row not recorded in skipped.json');

    assert.match(first, /rendered 2, skipped 1/);

    const second = run(['--in', FIXTURE, '--out-dir', out, '--views', '4', '--size', '224']);
    assert.match(second, /rendered 0/, 'a second run rendered files');
  } finally {
    fs.rmSync(out, { recursive: true, force: true });
  }
});
