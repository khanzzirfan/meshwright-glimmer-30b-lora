// Backfill assembly.jsonl for a GLB-mode run already on disk (docs/14 section 4).
// usage: node scripts/glb_assembly.mjs --run RUN_DIR --briefs FILE [--tol-frac 0.02]
//
// Reads RUN_DIR/validation.jsonl, computes assembly() for every ok row's RUN_DIR/glb/<id>.glb with the
// brief's kind (null for a row that is not ok), and writes RUN_DIR/assembly.jsonl lines {id, kind, assembly}.
// It never rewrites validation.jsonl.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { assembly, glbJson } from './glb_check.mjs';

const USAGE = 'usage: node scripts/glb_assembly.mjs --run RUN_DIR --briefs FILE [--tol-frac 0.02]';
const arg = (n, d) => { const i = process.argv.indexOf('--' + n); return i > -1 ? process.argv[i + 1] : d; };

// id -> kind from a briefs JSONL file, the same shape as bench/glb/briefs.jsonl.
export function readBriefKinds(file) {
  const kinds = new Map();
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    const b = JSON.parse(line);
    if (b && b.id) kinds.set(b.id, b.kind || 'static');
  }
  return kinds;
}

export function backfill(runDir, briefKinds, { tolFrac = 0.02 } = {}) {
  const raw = fs.readFileSync(path.join(runDir, 'validation.jsonl'), 'utf8');
  const rows = raw.trim() ? raw.trim().split('\n').map((l) => JSON.parse(l)) : [];
  const lines = [];
  let valid = 0;
  let assembled = 0;
  for (const row of rows) {
    const kind = briefKinds.get(row.id) || 'static';
    let result = null;
    if (row.ok) {
      valid++;
      const file = path.join(runDir, 'glb', row.id + '.glb');
      const json = fs.existsSync(file) ? glbJson(fs.readFileSync(file)) : null;
      result = assembly(json, { kind, tolFrac });
      if (result.assembled) assembled++;
    }
    lines.push({ id: row.id, kind, assembly: result });
  }
  return { lines, valid, assembled };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const runDir = arg('run');
  const briefs = arg('briefs');
  if (!runDir || !briefs || !fs.existsSync(path.join(runDir, 'validation.jsonl'))) {
    console.error(USAGE);
    process.exit(2);
  }
  const tolFrac = Number(arg('tol-frac', '0.02'));
  const { lines, valid, assembled } = backfill(runDir, readBriefKinds(briefs), { tolFrac });
  fs.writeFileSync(path.join(runDir, 'assembly.jsonl'), lines.map((l) => JSON.stringify(l)).join('\n') + '\n');
  console.log(`assembled ${assembled} of ${valid} valid`);
}
