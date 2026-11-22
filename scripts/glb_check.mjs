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

// --- assembly metric (docs/14 section 4) ------------------------------------

const IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];

const num = (v, d) => (Number.isFinite(Number(v)) ? Number(v) : d);

// Column-major 4x4 (glTF layout): element (row r, col c) lives at index c * 4 + r.
function matMul(a, b) {
  const o = new Array(16);
  for (let c = 0; c < 4; c++) {
    for (let r = 0; r < 4; r++) {
      o[c * 4 + r] =
        a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
    }
  }
  return o;
}

function matFromTRS(t, r, s) {
  const tx = num(t && t[0], 0);
  const ty = num(t && t[1], 0);
  const tz = num(t && t[2], 0);
  const sx = num(s && s[0], 1);
  const sy = num(s && s[1], 1);
  const sz = num(s && s[2], 1);
  let x = num(r && r[0], 0);
  let y = num(r && r[1], 0);
  let z = num(r && r[2], 0);
  let w = num(r && r[3], 1);
  const len = Math.hypot(x, y, z, w);
  if (len > 0) {
    x /= len;
    y /= len;
    z /= len;
    w /= len;
  } else {
    x = 0;
    y = 0;
    z = 0;
    w = 1;
  }
  const m = new Array(16);
  m[0] = (1 - 2 * (y * y + z * z)) * sx;
  m[1] = 2 * (x * y + z * w) * sx;
  m[2] = 2 * (x * z - y * w) * sx;
  m[3] = 0;
  m[4] = 2 * (x * y - z * w) * sy;
  m[5] = (1 - 2 * (x * x + z * z)) * sy;
  m[6] = 2 * (y * z + x * w) * sy;
  m[7] = 0;
  m[8] = 2 * (x * z + y * w) * sz;
  m[9] = 2 * (y * z - x * w) * sz;
  m[10] = (1 - 2 * (x * x + y * y)) * sz;
  m[11] = 0;
  m[12] = tx;
  m[13] = ty;
  m[14] = tz;
  m[15] = 1;
  return m;
}

function nodeMatrix(node) {
  if (Array.isArray(node.matrix) && node.matrix.length === 16 && node.matrix.every((v) => Number.isFinite(Number(v)))) {
    return node.matrix.map(Number);
  }
  return matFromTRS(node.translation, node.rotation, node.scale);
}

function matApply(m, p) {
  return [
    m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12],
    m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13],
    m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14],
  ];
}

const unionBox = (a, b) => ({
  min: [Math.min(a.min[0], b.min[0]), Math.min(a.min[1], b.min[1]), Math.min(a.min[2], b.min[2])],
  max: [Math.max(a.max[0], b.max[0]), Math.max(a.max[1], b.max[1]), Math.max(a.max[2], b.max[2])],
});

// Transform the 8 corners of a local min/max box and return the world axis-aligned box.
function transformBox(m, box) {
  let min = null;
  let max = null;
  for (const cx of [box.min[0], box.max[0]]) {
    for (const cy of [box.min[1], box.max[1]]) {
      for (const cz of [box.min[2], box.max[2]]) {
        const w = matApply(m, [cx, cy, cz]);
        if (min === null) {
          min = w;
          max = w.slice();
        } else {
          for (let i = 0; i < 3; i++) {
            min[i] = Math.min(min[i], w[i]);
            max[i] = Math.max(max[i], w[i]);
          }
        }
      }
    }
  }
  return { min, max };
}

// Signed separation between two 1D intervals: 0 when they overlap, positive gap otherwise.
const axisGap = (aMin, aMax, bMin, bMax) => Math.max(aMin - bMax, bMin - aMax, 0);

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

// A mesh node's local POSITION box scaled, rotated and translated by its world matrix: a centre, three
// orthonormal axes and a half extent along each. A zero-length transformed axis (a zero scale) falls back
// to a canonical direction with half extent 0, so a degenerate box never yields NaN (imp-5 US-002).
function obbFromBox(m, box) {
  const center = matApply(m, [
    (box.min[0] + box.max[0]) / 2,
    (box.min[1] + box.max[1]) / 2,
    (box.min[2] + box.max[2]) / 2,
  ]);
  const half = [(box.max[0] - box.min[0]) / 2, (box.max[1] - box.min[1]) / 2, (box.max[2] - box.min[2]) / 2];
  const axes = [];
  const halfExtents = [];
  for (let c = 0; c < 3; c++) {
    const v = [m[c * 4], m[c * 4 + 1], m[c * 4 + 2]];
    const len = Math.hypot(v[0], v[1], v[2]);
    if (len > 0) {
      axes.push([v[0] / len, v[1] / len, v[2] / len]);
      halfExtents.push(half[c] * len);
    } else {
      axes.push([c === 0 ? 1 : 0, c === 1 ? 1 : 0, c === 2 ? 1 : 0]);
      halfExtents.push(0);
    }
  }
  return { center, axes, half: halfExtents };
}

// The projected radius of an oriented box onto a unit axis.
const obbRadius = (o, n) =>
  o.half[0] * Math.abs(dot(o.axes[0], n)) + o.half[1] * Math.abs(dot(o.axes[1], n)) + o.half[2] * Math.abs(dot(o.axes[2], n));

// Separating-axis test over the 15 candidate axes: the 3 axes of each box and the 9 cross products. Two
// boxes touch when no axis separates them by more than tol. Near-zero cross products (parallel edges) are
// skipped. Axis-aligned boxes of rotated parts can overlap while the parts do not, which is why this is
// stricter than the box test (docs/14 section 4, imp-5 US-002).
function obbTouches(A, B, tol) {
  const axes = [A.axes[0], A.axes[1], A.axes[2], B.axes[0], B.axes[1], B.axes[2]];
  for (const a of A.axes) for (const b of B.axes) axes.push(cross(a, b));
  for (const raw of axes) {
    const len = Math.hypot(raw[0], raw[1], raw[2]);
    if (!(len > 1e-9)) continue;
    const n = [raw[0] / len, raw[1] / len, raw[2] / len];
    const ca = dot(A.center, n);
    const cb = dot(B.center, n);
    const gap = axisGap(ca - obbRadius(A, n), ca + obbRadius(A, n), cb - obbRadius(B, n), cb + obbRadius(B, n));
    if (gap > tol) return false;
  }
  return true;
}

// The axis-aligned test the original metric uses: two world boxes touch when neither axis separates them.
const boxTouches = (A, B, tol) => {
  for (let i = 0; i < 3; i++) if (axisGap(A.min[i], A.max[i], B.min[i], B.max[i]) > tol) return false;
  return true;
};

// Connected components of a touch graph on n parts. Returns the component count, the largest component's
// part count and share, and the union-find root lookup (used by the floater rule).
function componentOf(n, touches) {
  const parent = Array.from({ length: n }, (_, i) => i);
  const find = (i) => {
    while (parent[i] !== i) {
      parent[i] = parent[parent[i]];
      i = parent[i];
    }
    return i;
  };
  const join = (a, b) => {
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parent[ra] = rb;
  };
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) if (touches(i, j)) join(i, j);
  }
  const sizes = new Map();
  for (let i = 0; i < n; i++) {
    const r = find(i);
    sizes.set(r, (sizes.get(r) || 0) + 1);
  }
  let largest = 0;
  for (const s of sizes.values()) largest = Math.max(largest, s);
  return { components: sizes.size, largest, largest_share: n ? largest / n : 0, sizes, find };
}

// The world axis-aligned boxes and oriented boxes of the mesh nodes, walking the node tree from the scene
// roots. The two lists are parallel: entry i of each belongs to the same mesh node.
function walkBoxes(json) {
  const accessors = Array.isArray(json.accessors) ? json.accessors : [];
  const meshes = Array.isArray(json.meshes) ? json.meshes : [];
  const nodes = Array.isArray(json.nodes) ? json.nodes : [];

  const scenes = Array.isArray(json.scenes) ? json.scenes : [];
  const sceneIndex = Number.isInteger(json.scene) ? json.scene : 0;
  const scene = scenes[sceneIndex] ?? scenes[0];
  const roots = scene && Array.isArray(scene.nodes) ? scene.nodes : nodes.map((_, i) => i);

  const boxes = [];
  const obbs = [];
  const visited = new Set();
  const walk = (index, parentMatrix) => {
    const node = nodes[index];
    if (!node || typeof node !== 'object') throw new Error('bad_node');
    if (visited.has(index)) throw new Error('cycle');
    visited.add(index);
    const world = matMul(parentMatrix, nodeMatrix(node));
    if (Number.isInteger(node.mesh) && meshes[node.mesh]) {
      let box = null;
      let local = null;
      const prims = Array.isArray(meshes[node.mesh].primitives) ? meshes[node.mesh].primitives : [];
      for (const prim of prims) {
        const pos = accessors[prim?.attributes?.POSITION];
        if (!Array.isArray(pos?.min) || !Array.isArray(pos?.max)) continue;
        const partLocal = { min: pos.min.slice(0, 3).map(Number), max: pos.max.slice(0, 3).map(Number) };
        if (![...partLocal.min, ...partLocal.max].every(Number.isFinite)) continue;
        const world2 = transformBox(world, partLocal);
        box = box ? unionBox(box, world2) : world2;
        local = local ? unionBox(local, partLocal) : partLocal;
      }
      if (box) {
        boxes.push(box);
        obbs.push(obbFromBox(world, local));
      }
    }
    if (Array.isArray(node.children)) for (const c of node.children) walk(c, world);
  };
  for (const r of roots) walk(r, IDENTITY);
  return { boxes, obbs };
}

export function assembly(json, { kind = 'static', tolFrac = 0.02 } = {}) {
  try {
    if (json === null || typeof json !== 'object' || Array.isArray(json)) {
      return { parts: 0, assembled: false, error: 'not_an_object' };
    }
    const { boxes: parts, obbs } = walkBoxes(json);
    const n = parts.length;

    let union = null;
    for (const b of parts) union = union ? unionBox(union, b) : b;
    const tol = union
      ? tolFrac * Math.hypot(union.max[0] - union.min[0], union.max[1] - union.min[1], union.max[2] - union.min[2])
      : 0;

    const aabb = componentOf(n, (i, j) => boxTouches(parts[i], parts[j], tol));
    const obb = componentOf(n, (i, j) => obbTouches(obbs[i], obbs[j], tol));
    const { components, largest_share, sizes, find } = aabb;
    const components_obb = obb.components;
    const largest_share_obb = obb.largest_share;

    const min_y = n ? parts.reduce((m, b) => Math.min(m, b.min[1]), Infinity) : null;
    const ground_gap = min_y === null ? null : Math.max(0, min_y);

    let floaters = 0;
    for (let i = 0; i < n; i++) {
      if (sizes.get(find(i)) !== 1) continue;
      const p = parts[i];
      if (p.min[1] <= tol) continue;
      let supported = false;
      for (let j = 0; j < n && !supported; j++) {
        if (j === i) continue;
        const q = parts[j];
        if (q.max[1] > p.min[1] + tol) continue;
        if (p.min[1] - q.max[1] > tol) continue;
        if (axisGap(p.min[0], p.max[0], q.min[0], q.max[0]) > tol) continue;
        if (axisGap(p.min[2], p.max[2], q.min[2], q.max[2]) > tol) continue;
        supported = true;
      }
      if (!supported) floaters++;
    }

    const grounded = ground_gap !== null && ground_gap <= tol;
    const assembled = kind === 'set' ? floaters === 0 && grounded : largest_share >= 0.9 && floaters === 0 && grounded;
    const assembled_obb =
      kind === 'set' ? floaters === 0 && grounded : largest_share_obb >= 0.9 && floaters === 0 && grounded;

    return {
      parts: n,
      components,
      largest_share,
      components_obb,
      largest_share_obb,
      floaters,
      min_y,
      ground_gap,
      tol,
      assembled,
      assembled_obb,
    };
  } catch (e) {
    return { parts: 0, assembled: false, assembled_obb: false, error: String((e && e.message) || e).slice(0, 80) };
  }
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
  // NaN in a page's transform is written as null by JSON: three.js silently hides the part and Blender refuses
  // the file ("Couldn't parse glTF"), so a node with a non-numeric transform makes the GLB invalid.
  const badTransform = (n) => ['translation', 'rotation', 'scale', 'matrix'].some((k) =>
    Array.isArray(n?.[k]) && n[k].some((v) => typeof v !== 'number' || !Number.isFinite(v)));
  const nanNodes = nodes.filter(badTransform).length;
  // The same for vertex data: an accessor whose min/max is not numeric holds NaN positions.
  const nanAccessors = accessors.filter((a) => ['min', 'max'].some((k) =>
    Array.isArray(a?.[k]) && a[k].some((v) => typeof v !== 'number' || !Number.isFinite(v)))).length;
  const result = {
    ok: !empty && nanNodes === 0 && nanAccessors === 0,
    reason: empty ? 'empty_glb' : (nanNodes ? 'nan_transform' : (nanAccessors ? 'nan_geometry' : null)),
    nan_transform_nodes: nanNodes,
    nan_geometry_accessors: nanAccessors,
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
  if (!empty) result.assembly = assembly(json);
  return result;
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

// Return the glTF JSON object of a GLB buffer, or null when it is unreadable. Used to compute the
// kind-aware assembly for a GLB already on disk (parseGlb only reports the static-kind assembly).
export function glbJson(buf) {
  try {
    let data;
    if (Buffer.isBuffer(buf)) data = buf;
    else if (ArrayBuffer.isView(buf)) data = Buffer.from(buf.buffer, buf.byteOffset, buf.byteLength);
    else if (buf instanceof ArrayBuffer) data = Buffer.from(buf);
    else return null;
    if (data.length < 20) return null;
    if (data.readUInt32LE(0) !== MAGIC) return null;
    if (data.readUInt32LE(4) !== 2) return null;
    if (data.readUInt32LE(8) !== data.length) return null;
    const jsonLength = data.readUInt32LE(12);
    if (data.readUInt32LE(16) !== JSON_CHUNK) return null;
    const jsonEnd = 20 + jsonLength;
    if (jsonEnd > data.length) return null;
    const json = JSON.parse(data.subarray(20, jsonEnd).toString('utf8'));
    if (json === null || typeof json !== 'object' || Array.isArray(json)) return null;
    return json;
  } catch {
    return null;
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
