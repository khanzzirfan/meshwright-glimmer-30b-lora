import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { makeGlb } from './glb_util.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = path.join(ROOT, 'scripts', 'glb_sheet.mjs');
const PNG_SIG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function pngSize(file) {
  const b = fs.readFileSync(file);
  assert.ok(b.subarray(0, 8).equals(PNG_SIG), `${file} is not a PNG`);
  assert.equal(b.subarray(12, 16).toString('ascii'), 'IHDR');
  return { width: b.readUInt32BE(16), height: b.readUInt32BE(20) };
}

function readCsv(file) {
  return fs.readFileSync(file, 'utf8').trim().split('\n').map((line) => {
    const cells = [];
    let cell = '';
    let quoted = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (quoted) {
        if (c === '"' && line[i + 1] === '"') { cell += '"'; i++; }
        else if (c === '"') quoted = false;
        else cell += c;
      } else if (c === '"') quoted = true;
      else if (c === ',') { cells.push(cell); cell = ''; }
      else cell += c;
    }
    cells.push(cell);
    return cells;
  });
}

const BRIEFS = [
  { id: 'b1', title: 'Crate', brief: 'A wooden crate.', kind: 'static' },
  { id: 'b2', title: 'Chair', brief: 'A simple chair.', kind: 'static' },
  { id: 'b3', title: 'Wall', brief: 'A short wall.', kind: 'set' },
];

function makeRoot(tmp) {
  const root = path.join(tmp, 'bench');
  const briefs = path.join(tmp, 'briefs.jsonl');
  fs.writeFileSync(briefs, BRIEFS.map((brief) => JSON.stringify(brief)).join('\n') + '\n');

  const glb = (model, id, buffer) => {
    const dir = path.join(root, model, 'glb');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, id + '.glb'), buffer);
  };
  glb('m_a', 'b1', makeGlb({ triangles: 12, meshes: 2 }));
  glb('m_a', 'b2', makeGlb({ triangles: 6 }));
  glb('m_b', 'b1', makeGlb({ triangles: 3, indexed: false }));
  glb('m_b', 'b2', Buffer.from('this is not a glb'));
  return { root, briefs };
}

function run(root, briefs, out, size, seed, requestLog) {
  return execFileSync(
    process.execPath,
    [SCRIPT, '--root', root, '--out', out, '--briefs', briefs, '--size', String(size), '--seed', String(seed)],
    {
      cwd: ROOT,
      encoding: 'utf8',
      timeout: 180000,
      env: { ...process.env, GLB_SHEET_REQUEST_LOG: requestLog },
    },
  );
}

test('glb_sheet renders views, a sheet per model and a blind rating file', { timeout: 180000 }, () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'glb-sheet-'));
  const requestLog = path.join(tmp, 'requests.json');
  try {
    const { root, briefs } = makeRoot(tmp);
    const out = path.join(tmp, 'sheet');
    const size = 64;
    const first = run(root, briefs, out, size, 7, requestLog);
    assert.match(first, /rendered 3, skipped 1/);

    for (const [model, id] of [['m_a', 'b1'], ['m_a', 'b2'], ['m_b', 'b1']]) {
      const file = path.join(out, model, id + '.png');
      assert.ok(fs.existsSync(file), `missing ${file}`);
      assert.deepEqual(pngSize(file), { width: size * 2, height: size }, `${file} is not two views side by side`);
    }
    assert.ok(fs.existsSync(path.join(out, 'm_a', 'sheet.png')), 'm_a sheet missing');
    assert.ok(fs.existsSync(path.join(out, 'm_b', 'sheet.png')), 'm_b sheet missing');

    const skipped = JSON.parse(fs.readFileSync(path.join(out, 'skipped.json'), 'utf8'));
    assert.ok(
      skipped.some((entry) => entry.model === 'm_b' && entry.id === 'b2'),
      `corrupt GLB not in skipped.json: ${JSON.stringify(skipped)}`,
    );

    const keyMap = JSON.parse(fs.readFileSync(path.join(out, 'key_map.json'), 'utf8'));
    const rows = readCsv(path.join(out, 'rating.csv'));
    assert.deepEqual(rows[0], ['key', 'brief', 'image', 'rating']);
    const data = rows.slice(1);
    assert.equal(data.length, 6, 'one row per model x brief');
    assert.equal(new Set(data.map((row) => row[0])).size, 6, 'keys are not unique');
    assert.deepEqual(Object.keys(keyMap).sort(), data.map((row) => row[0]).sort(), 'key_map does not cover every row');

    const rating = fs.readFileSync(path.join(out, 'rating.csv'), 'utf8');
    for (const model of ['m_a', 'm_b']) assert.ok(!rating.includes(model), `rating.csv leaks ${model}`);

    let empty = 0;
    for (const [key, brief, image, value] of data) {
      assert.match(key, /^r\d{3}$/);
      assert.equal(keyMap[key].id, brief);
      assert.ok(['m_a', 'm_b'].includes(keyMap[key].model));
      assert.equal(value, '', 'rating must start empty');
      if (image === '') {
        empty++;
        assert.ok(!fs.existsSync(path.join(out, keyMap[key].model, brief + '.png')), `${key} has a PNG but no image`);
      } else {
        assert.ok(!image.includes(keyMap[key].model), `image path leaks the model: ${image}`);
        assert.ok(fs.existsSync(path.join(out, image)), `missing blind image ${image}`);
      }
    }
    assert.equal(empty, 3, 'missing GLBs and the corrupt one should have an empty image');

    assert.deepEqual(JSON.parse(fs.readFileSync(requestLog, 'utf8')), [], 'a page reached the network');

    const second = run(root, briefs, out, size, 7, requestLog);
    assert.match(second, /rendered 0/, 'a rerun rendered existing PNGs again');
    assert.equal(fs.readFileSync(path.join(out, 'rating.csv'), 'utf8'), rating, 'the same seed changed the order');
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
