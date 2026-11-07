// Download Three.js releases into a local cache so the validator can serve each page the version it asked for.
// usage: node scripts/fetch_three.mjs --versions 0.164.1,0.169.0 [--from-raw DIR] [--dir .cache/three]
// --from-raw scans raw answer JSON files for three@X.Y.Z and three.js/X.Y.Z/ and fetches those versions.
// Network: one `npm pack three@X` per missing version (the npm registry). The cache is gitignored; nothing else is touched.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };

export function versionsInText(text) {
  const found = new Set();
  for (const m of text.matchAll(/three@(\d+\.\d+\.\d+)|three\.js\/(\d+\.\d+\.\d+)\//g)) found.add(m[1] || m[2]);
  return found;
}

export function versionsFromRaw(dir) {
  const found = new Set();
  for (const f of fs.readdirSync(dir).filter((n) => n.endsWith('.json'))) {
    try {
      const raw = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
      for (const v of versionsInText(raw.content || '')) found.add(v);
    } catch { /* a bad row is skipped */ }
  }
  return found;
}

function fetchOne(version, cacheDir) {
  const target = path.join(cacheDir, version);
  if (fs.existsSync(path.join(target, 'build', 'three.module.js'))) return 'cached';
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'three-pack-'));
  try {
    const out = execFileSync('npm', ['pack', `three@${version}`, '--silent'], { cwd: tmp, encoding: 'utf8' }).trim().split('\n').pop();
    execFileSync('tar', ['xzf', path.join(tmp, out), '-C', tmp]);
    fs.mkdirSync(cacheDir, { recursive: true });
    fs.rmSync(target, { recursive: true, force: true });
    fs.renameSync(path.join(tmp, 'package'), target);
    return 'fetched';
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

if (process.argv[1] && import.meta.url === new URL(`file://${path.resolve(process.argv[1])}`).href) {
  const cacheDir = path.resolve(arg('dir', path.join(ROOT, '.cache/three')));
  const wanted = new Set((arg('versions', '') || '').split(',').filter(Boolean));
  const fromRaw = arg('from-raw');
  if (fromRaw) for (const v of versionsFromRaw(fromRaw)) wanted.add(v);
  wanted.delete('0.160.0'); // the repo already has it in node_modules
  if (!wanted.size) { console.log('nothing to fetch'); process.exit(0); }
  for (const v of [...wanted].sort()) {
    try { console.log(v, fetchOne(v, cacheDir)); } catch (e) { console.log(v, 'FAILED', String(e.message).split('\n')[0]); }
  }
}
