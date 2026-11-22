// Make a GLB's name strings safe for Blender 5.2 (docs/15 section 7, promo-1 US-008).
//
// Blender 5.2 parses a name that ends in ".<digits>" as a duplicate-number suffix and runs std::stoi on
// that digit run, which overflows (out_of_range) and aborts the whole import (SIGABRT) once the run is a
// long fractional coordinate. The model sometimes names parts with raw float coordinates
// ("sack_0.5_1.0499999999999998", "bed_plank_0.09999999999999998"); three.js is unaffected, so only the
// names change. Only a name-final ".<digits>" is parsed by Blender, which is why a run of decimals in the
// middle of a name (e.g. "wall_block_-3.5999999999999996_0") imports fine and is left alone (measured on
// the 540 distill GLBs: 15 of them abort Blender, all with a long fractional suffix).
//
// This rewrites the `name` strings of nodes, meshes, materials, animations and scenes in the JSON chunk —
// never indices, accessors, buffers, materials' values or animation channels (channels target node indices,
// so renaming nodes is safe) — and re-encodes the GLB the way glb_ground.mjs does.
//
// usage: node scripts/glb_names.mjs --in FILE --out FILE    # rewrite, print {"renamed": N}
//        node scripts/glb_names.mjs --check FILE[,FILE...]  # report files that would change (read only)
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
import { glbJson } from './glb_check.mjs';
import { rewriteGlb } from './glb_ground.mjs';

const USAGE = 'usage: node scripts/glb_names.mjs --in FILE --out FILE | --check FILE[,FILE...]';

// The name-bearing collections, in a fixed report order.
const KINDS = [
  ['node', 'nodes'],
  ['mesh', 'meshes'],
  ['material', 'materials'],
  ['animation', 'animations'],
  ['scene', 'scenes'],
];

// A decimal rounded to 3 fractional digits, trailing zeros dropped and -0 normalised to 0.
function roundDecimal(text) {
  let out = Number(text).toFixed(3).replace(/\.?0+$/, '');
  if (out === '' || out === '-0') out = '0';
  return out;
}

// One name: a final decimal with more than three fractional digits is rounded to at most three, then a
// name that still ends in ".<digits>" whose value exceeds 999999 gets "_" instead of that last "." (a
// suffix Blender would parse as a number). A name with no such ending is returned unchanged.
export function sanitizeName(name) {
  let out = name;
  const decimal = /-?\d+\.(\d+)$/.exec(out);
  if (decimal && decimal[1].length > 3) out = out.slice(0, decimal.index) + roundDecimal(decimal[0]);
  const tail = /\.(\d+)$/.exec(out);
  if (tail && Number(tail[1]) > 999999) out = `${out.slice(0, tail.index)}_${tail[1]}`;
  return out;
}

// sanitizeNames(buf) -> {buf, renamed: [{kind, index, from, to}]}. A name that needs no change stays
// byte-identical and a GLB with no change returns the input buffer. A rewrite that would make two names
// of the same kind equal gets a "_2", "_3", ... suffix (unchanged names are reserved first, so a rewrite
// never takes a name another entry already uses).
export function sanitizeNames(buf) {
  const json = glbJson(buf);
  if (json === null) return { buf, renamed: [] };
  const renamed = [];
  for (const [kind, key] of KINDS) {
    const list = Array.isArray(json[key]) ? json[key] : [];
    const used = new Set();
    const changed = [];
    list.forEach((entry, index) => {
      if (!entry || typeof entry.name !== 'string') return;
      const to = sanitizeName(entry.name);
      if (to === entry.name) used.add(entry.name);
      else changed.push({ entry, index, from: entry.name, to });
    });
    for (const item of changed) {
      let to = item.to;
      for (let n = 2; used.has(to); n++) to = `${item.to}_${n}`;
      used.add(to);
      item.entry.name = to;
      renamed.push({ kind, index: item.index, from: item.from, to });
    }
  }
  if (renamed.length === 0) return { buf, renamed };
  return { buf: rewriteGlb(buf, json), renamed };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const argv = process.argv.slice(2);
  const value = (name) => { const i = argv.indexOf('--' + name); return i > -1 ? argv[i + 1] : undefined; };
  const checkIndex = argv.indexOf('--check');
  if (checkIndex > -1) {
    const files = [];
    for (const token of argv.slice(checkIndex + 1)) {
      if (token.startsWith('--')) break;
      for (const part of token.split(',')) if (part) files.push(part);
    }
    for (const file of files) {
      let renamed = 0;
      try { renamed = sanitizeNames(fs.readFileSync(file)).renamed.length; } catch { renamed = 0; }
      if (renamed) console.log(JSON.stringify({ file, renamed }));
    }
  } else {
    const inFile = value('in');
    const outFile = value('out');
    if (!inFile || !outFile) {
      console.error(USAGE);
      process.exit(2);
    }
    let result;
    try {
      result = sanitizeNames(fs.readFileSync(inFile));
    } catch {
      console.error(USAGE);
      process.exit(2);
    }
    fs.writeFileSync(outFile, result.buf);
    console.log(JSON.stringify({ renamed: result.renamed.length }));
  }
}
