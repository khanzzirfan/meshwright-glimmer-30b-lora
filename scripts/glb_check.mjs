// Parse a GLB and measure what a game engine would import: meshes, primitives, triangles,
// vertices, materials, nodes, animations and the approximate bounds (node transforms ignored).
// Pure Node: no dependency, and it never throws.
// usage: node scripts/glb_check.mjs FILE.glb
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

const MAGIC = 0x46546c67;
const JSON_CHUNK = 0x4e4f534a;

const emptyBbox = () => ({ min: null, max: null, size: null });

function bad(bytes, version = null) {
  return {
    ok: false,
    reason: 'bad_glb',
    bytes,
    version,
    meshes: 0,
    primitives: 0,
    triangles: 0,
    vertices: 0,
    materials: 0,
    nodes: 0,
    animations: 0,
    bbox: emptyBbox(),
  };
}

function triangleCount(mode, count) {
  if (mode === 4) return Math.floor(count / 3);
  if (mode === 5 || mode === 6) return Math.max(0, count - 2);
  return 0;
}

function measure(json, bytes, version) {
  const meshes = Array.isArray(json.meshes) ? json.meshes : [];
  const nodes = Array.isArray(json.nodes) ? json.nodes : [];
  const materials = Array.isArray(json.materials) ? json.materials : [];
  const animations = Array.isArray(json.animations) ? json.animations : [];
  const accessors = Array.isArray(json.accessors) ? json.accessors : [];

  let primitives = 0;
  let triangles = 0;
  let vertices = 0;
  let min = null;
  let max = null;

  for (const mesh of meshes) {
    const prims = Array.isArray(mesh?.primitives) ? mesh.primitives : [];
    for (const prim of prims) {
      primitives++;
      const pos = accessors[prim?.attributes?.POSITION];
      const posCount = Number.isFinite(pos?.count) ? pos.count : 0;
      vertices += posCount;

      const idx = prim?.indices == null ? null : accessors[prim.indices];
      const count = idx && Number.isFinite(idx.count) ? idx.count : posCount;
      triangles += triangleCount(prim?.mode === undefined ? 4 : prim.mode, count);

      if (Array.isArray(pos?.min) && pos.min.length >= 3 && Array.isArray(pos?.max) && pos.max.length >= 3) {
        const lo = pos.min.slice(0, 3).map(Number);
        const hi = pos.max.slice(0, 3).map(Number);
        if (lo.every(Number.isFinite) && hi.every(Number.isFinite)) {
          if (min === null) {
            min = lo;
            max = hi;
          } else {
            for (let i = 0; i < 3; i++) {
              min[i] = Math.min(min[i], lo[i]);
              max[i] = Math.max(max[i], hi[i]);
            }
          }
        }
      }
    }
  }

  const bbox = min === null ? emptyBbox() : { min, max, size: max.map((v, i) => v - min[i]) };
  const empty = meshes.length === 0 || triangles === 0;
  return {
    ok: !empty,
    reason: empty ? 'empty_glb' : null,
    bytes,
    version,
    meshes: meshes.length,
    primitives,
    triangles,
    vertices,
    materials: materials.length,
    nodes: nodes.length,
    animations: animations.length,
    bbox,
  };
}

export function parseGlb(buf) {
  let bytes = 0;
  try {
    if (buf == null) return bad(0);
    let data;
    if (Buffer.isBuffer(buf)) data = buf;
    else if (ArrayBuffer.isView(buf)) data = Buffer.from(buf.buffer, buf.byteOffset, buf.byteLength);
    else if (buf instanceof ArrayBuffer) data = Buffer.from(buf);
    else return bad(0);

    bytes = data.length;
    if (bytes < 12) return bad(bytes);

    if (data.readUInt32LE(0) !== MAGIC) return bad(bytes);
    const version = data.readUInt32LE(4);
    if (version !== 2) return bad(bytes, version);
    if (data.readUInt32LE(8) !== bytes) return bad(bytes, version);
    if (bytes < 20) return bad(bytes, version);

    const jsonLength = data.readUInt32LE(12);
    if (data.readUInt32LE(16) !== JSON_CHUNK) return bad(bytes, version);
    const jsonEnd = 20 + jsonLength;
    if (jsonEnd > bytes) return bad(bytes, version);

    let json;
    try {
      json = JSON.parse(data.subarray(20, jsonEnd).toString('utf8'));
    } catch {
      return bad(bytes, version);
    }
    if (json === null || typeof json !== 'object' || Array.isArray(json)) return bad(bytes, version);

    return measure(json, bytes, version);
  } catch {
    return bad(bytes);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  let result;
  try {
    result = parseGlb(fs.readFileSync(process.argv[2]));
  } catch {
    result = bad(0);
  }
  console.log(JSON.stringify(result));
  process.exit(result.ok ? 0 : 1);
}
