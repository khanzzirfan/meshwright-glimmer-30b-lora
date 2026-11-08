// Drop an exported GLB onto the ground: append one translation node so the asset's lowest world y is 0,
// because a hovering or sunk asset fails assembly even when its parts fit together (docs/14 section 4,
// imp-5 US-001). When the asset already rests within tol the input buffer is returned unchanged.
// usage: node scripts/glb_ground.mjs --in FILE --out FILE [--kind static|animated|set] [--tol-frac 0.02]
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
import { assembly, glbJson } from './glb_check.mjs';

const MAGIC = 0x46546c67;
const JSON_CHUNK = 0x4e4f534a;

const USAGE = 'usage: node scripts/glb_ground.mjs --in FILE --out FILE [--kind static|animated|set] [--tol-frac 0.02]';
const arg = (n, d) => { const i = process.argv.indexOf('--' + n); return i > -1 ? process.argv[i + 1] : d; };

// Rebuild a GLB with a new JSON chunk. The JSON is re-encoded and space-padded to 4 bytes, every chunk
// after it (the BIN chunk) is copied byte for byte, and the total length is rewritten.
function rewriteGlb(buf, json) {
  const jsonLength = buf.readUInt32LE(12);
  const rest = buf.subarray(20 + jsonLength);
  let jsonBytes = Buffer.from(JSON.stringify(json), 'utf8');
  const pad = (4 - (jsonBytes.length % 4)) % 4;
  if (pad) jsonBytes = Buffer.concat([jsonBytes, Buffer.alloc(pad, 0x20)]);
  const total = 12 + 8 + jsonBytes.length + rest.length;
  const out = Buffer.alloc(total);
  out.writeUInt32LE(MAGIC, 0);
  out.writeUInt32LE(2, 4);
  out.writeUInt32LE(total, 8);
  out.writeUInt32LE(jsonBytes.length, 12);
  out.writeUInt32LE(JSON_CHUNK, 16);
  jsonBytes.copy(out, 20);
  rest.copy(out, 20 + jsonBytes.length);
  return out;
}

// groundGlb(buf, {kind, tolFrac}) -> {buf, shift, assembly_before, assembly_after}.
// When |min_y| > tol it appends ONE node {name: 'ground_offset', translation: [0, -min_y, 0],
// children: <the scene's old roots>} and makes it the scene's only root. Existing node indices do not
// change, so animation channels and skins stay valid. Otherwise the input buffer is returned unchanged.
export function groundGlb(buf, { kind = 'static', tolFrac = 0.02 } = {}) {
  const json = glbJson(buf);
  const assembly_before = assembly(json, { kind, tolFrac });
  const min_y = assembly_before.min_y;
  const tol = Number.isFinite(Number(assembly_before.tol)) ? Number(assembly_before.tol) : 0;
  if (json === null || !Number.isFinite(min_y) || Math.abs(min_y) <= tol) {
    return { buf, shift: 0, assembly_before, assembly_after: assembly_before };
  }
  const shift = -min_y;

  if (!Array.isArray(json.nodes)) json.nodes = [];
  if (!Array.isArray(json.scenes) || json.scenes.length === 0) json.scenes = [{}];
  const sceneIndex = Number.isInteger(json.scene) && json.scenes[json.scene] ? json.scene : 0;
  const scene = json.scenes[sceneIndex];
  const roots = Array.isArray(scene.nodes) ? scene.nodes : json.nodes.map((_, i) => i);

  const index = json.nodes.length;
  scene.nodes = [index];
  json.scene = sceneIndex;
  json.nodes.push({ name: 'ground_offset', translation: [0, shift, 0], children: roots });

  return { buf: rewriteGlb(buf, json), shift, assembly_before, assembly_after: assembly(json, { kind, tolFrac }) };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const inFile = arg('in');
  const outFile = arg('out');
  if (!inFile || !outFile) {
    console.error(USAGE);
    process.exit(2);
  }
  let result;
  try {
    result = groundGlb(fs.readFileSync(inFile), { kind: arg('kind', 'static'), tolFrac: Number(arg('tol-frac', '0.02')) });
  } catch {
    console.error(USAGE);
    process.exit(2);
  }
  fs.writeFileSync(outFile, result.buf);
  console.log(JSON.stringify({ shift: result.shift, assembly_before: result.assembly_before, assembly_after: result.assembly_after }));
}
