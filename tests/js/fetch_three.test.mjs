import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { versionsInText, versionsFromRaw } from '../../scripts/fetch_three.mjs';

test('versionsInText finds jsDelivr, unpkg and cdnjs style versions', () => {
  const text = [
    '"three": "https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js"',
    'import * as T from "https://unpkg.com/three@0.164.1/build/three.module.js"',
    'https://cdnjs.cloudflare.com/ajax/libs/three.js/0.150.1/three.module.min.js',
    'three@latest is not a version',
  ].join('\n');
  assert.deepEqual([...versionsInText(text)].sort(), ['0.150.1', '0.164.1', '0.169.0']);
});

test('versionsFromRaw reads raw answers and skips a broken file', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fetch-three-'));
  try {
    fs.writeFileSync(path.join(dir, 'a.json'), JSON.stringify({ content: 'x three@0.166.1/build y' }));
    fs.writeFileSync(path.join(dir, 'b.json'), '{not json');
    fs.writeFileSync(path.join(dir, 'c.txt'), 'three@0.1.2/');
    assert.deepEqual([...versionsFromRaw(dir)], ['0.166.1']);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});
