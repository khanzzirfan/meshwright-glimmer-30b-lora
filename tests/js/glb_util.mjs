// Build minimal GLB buffers by hand for the glb_check tests.
// Every mesh gets one primitive with a FLOAT VEC3 POSITION accessor (with min/max) and, when
// indexed, an UNSIGNED_SHORT element accessor. Animations are dummy sampler/channel pairs.
const MAGIC = 0x46546c67;
const JSON_CHUNK = 0x4e4f534a;
const BIN_CHUNK = 0x004e4942;

const pad4 = (n) => (4 - (n % 4)) % 4;

export function makeGlb({
  triangles = 1,
  indexed = true,
  animations = 0,
  meshes = 1,
  version = 2,
  badMagic = false,
  truncate = false,
  nodes = null,
  scene = null,
  boxes = null,
  names = null,
} = {}) {
  triangles = Math.max(0, Math.floor(triangles));
  animations = Math.max(0, Math.floor(animations));
  meshes = Math.max(0, Math.floor(meshes));

  let bin = Buffer.alloc(0);
  const bufferViews = [];
  const accessors = [];

  const addView = (data, target) => {
    const byteOffset = bin.length;
    bufferViews.push({ buffer: 0, byteOffset, byteLength: data.length, target });
    bin = Buffer.concat([bin, data, Buffer.alloc(pad4(bin.length + data.length))]);
    return bufferViews.length - 1;
  };

  const gltfMeshes = [];
  const boxList = Array.isArray(boxes) ? boxes : [];
  for (let m = 0; m < meshes; m++) {
    const vertexCount = triangles * 3;
    const positions = Buffer.alloc(vertexCount * 3 * 4);
    const box = boxList[m];
    let min;
    let max;
    if (box && Array.isArray(box.min) && Array.isArray(box.max)) {
      min = box.min.slice(0, 3).map(Number);
      max = box.max.slice(0, 3).map(Number);
      const corners = [];
      for (const cx of [min[0], max[0]]) for (const cy of [min[1], max[1]]) for (const cz of [min[2], max[2]]) corners.push([cx, cy, cz]);
      for (let k = 0; k < vertexCount; k++) {
        const c = corners[k % corners.length];
        const o = k * 12;
        positions.writeFloatLE(c[0], o);
        positions.writeFloatLE(c[1], o + 4);
        positions.writeFloatLE(c[2], o + 8);
      }
    } else {
      const baseX = m * 10;
      for (let k = 0; k < vertexCount; k++) {
        const o = k * 12;
        positions.writeFloatLE(baseX + k, o);
        positions.writeFloatLE(k % 2, o + 4);
        positions.writeFloatLE(m, o + 8);
      }
      min = vertexCount === 0 ? [0, 0, 0] : [baseX, 0, m];
      max = vertexCount === 0 ? [0, 0, 0] : [baseX + vertexCount - 1, 1, m];
    }
    const posView = addView(positions, 34962);
    const posAccessor = accessors.length;
    accessors.push({
      bufferView: posView,
      componentType: 5126,
      count: vertexCount,
      type: 'VEC3',
      min,
      max,
    });

    let indexAccessor = null;
    if (indexed) {
      const indices = Buffer.alloc(vertexCount * 2);
      for (let k = 0; k < vertexCount; k++) indices.writeUInt16LE(k, k * 2);
      const idxView = addView(indices, 34963);
      indexAccessor = accessors.length;
      accessors.push({
        bufferView: idxView,
        componentType: 5123,
        count: vertexCount,
        type: 'SCALAR',
      });
    }

    gltfMeshes.push({
      name: names?.meshes?.[m] ?? `mesh${m}`,
      primitives: [
        {
          attributes: { POSITION: posAccessor },
          ...(indexed ? { indices: indexAccessor } : {}),
          material: 0,
          mode: 4,
        },
      ],
    });
  }

  const gltfAnimations = [];
  if (animations > 0) {
    const times = Buffer.alloc(2 * 4);
    times.writeFloatLE(0, 0);
    times.writeFloatLE(1, 4);
    const timeView = addView(times);
    const timeAccessor = accessors.length;
    accessors.push({ bufferView: timeView, componentType: 5126, count: 2, type: 'SCALAR', min: [0], max: [1] });

    const values = Buffer.alloc(2 * 3 * 4);
    const valueView = addView(values);
    const valueAccessor = accessors.length;
    accessors.push({
      bufferView: valueView,
      componentType: 5126,
      count: 2,
      type: 'VEC3',
      min: [0, 0, 0],
      max: [0, 0, 0],
    });

    for (let a = 0; a < animations; a++) {
      gltfAnimations.push({
        name: names?.animations?.[a] ?? `anim${a}`,
        samplers: [{ input: timeAccessor, output: valueAccessor, interpolation: 'LINEAR' }],
        channels: [{ sampler: 0, target: { node: 0, path: 'translation' } }],
      });
    }
  }

  const gltfNodes = Array.isArray(nodes) ? nodes : Array.from({ length: meshes }, (_, i) => ({ mesh: i, name: `node${i}` }));
  const sceneNodes = Array.isArray(scene) ? scene : gltfNodes.map((_, i) => i);
  const sceneName = names?.scenes?.[0];
  const json = {
    asset: { version: '2.0', generator: 'tests/js/glb_util.mjs' },
    scene: 0,
    scenes: [{ nodes: sceneNodes, ...(sceneName !== undefined ? { name: sceneName } : {}) }],
    nodes: gltfNodes,
    meshes: gltfMeshes,
    materials: meshes > 0 ? [{ name: names?.materials?.[0] ?? 'mat', pbrMetallicRoughness: { baseColorFactor: [0.7, 0.7, 0.7, 1] } }] : [],
    accessors,
    bufferViews,
    buffers: [{ byteLength: bin.length }],
    animations: gltfAnimations,
  };

  const jsonBytes = Buffer.from(JSON.stringify(json), 'utf8');
  const jsonChunk = Buffer.concat([jsonBytes, Buffer.alloc(pad4(jsonBytes.length), 0x20)]);
  const binChunk = Buffer.concat([bin, Buffer.alloc(pad4(bin.length), 0)]);

  const total = 12 + 8 + jsonChunk.length + 8 + binChunk.length;
  const out = Buffer.alloc(total);
  out.writeUInt32LE(MAGIC, 0);
  out.writeUInt32LE(version >>> 0, 4);
  out.writeUInt32LE(total, 8);
  out.writeUInt32LE(jsonChunk.length, 12);
  out.writeUInt32LE(JSON_CHUNK, 16);
  jsonChunk.copy(out, 20);
  const binHeader = 20 + jsonChunk.length;
  out.writeUInt32LE(binChunk.length, binHeader);
  out.writeUInt32LE(BIN_CHUNK, binHeader + 4);
  binChunk.copy(out, binHeader + 8);

  if (badMagic) out.write('BAD!', 0, 'ascii');
  if (truncate) return out.subarray(0, Math.max(0, out.length - 8));
  return out;
}
