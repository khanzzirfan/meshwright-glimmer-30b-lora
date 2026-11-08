import { test } from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { makeGlb } from './glb_util.mjs';
import { assembly, parseGlb } from '../../scripts/glb_check.mjs';

// Read the JSON chunk back out of a GLB built by makeGlb, the way parseGlb does.
function jsonOf(glb) {
  const len = glb.readUInt32LE(12);
  return JSON.parse(glb.subarray(20, 20 + len).toString('utf8'));
}

// meshes = boxes.length, one box per mesh unless the test passes its own nodes.
function glbWith(boxes, nodes, extra = {}) {
  return makeGlb({ triangles: 1, indexed: false, meshes: boxes.length, boxes, nodes, ...extra });
}

const near = (a, b) => Math.abs(a - b) < 1e-6;

test('two touching boxes are one assembled component', () => {
  const json = jsonOf(glbWith([{ min: [0, 0, 0], max: [1, 1, 1] }, { min: [1, 0, 0], max: [2, 1, 1] }], [{ mesh: 0 }, { mesh: 1 }]));
  const a = assembly(json);
  assert.equal(a.parts, 2);
  assert.equal(a.components, 1);
  assert.equal(a.largest_share, 1);
  assert.equal(a.floaters, 0);
  assert.equal(a.assembled, true);
});

test('two boxes a metre apart are not assembled static but are a set', () => {
  const json = jsonOf(glbWith([{ min: [0, 0, 0], max: [1, 1, 1] }, { min: [2, 0, 0], max: [3, 1, 1] }], [{ mesh: 0 }, { mesh: 1 }]));
  const stat = assembly(json, { kind: 'static' });
  assert.equal(stat.components, 2);
  assert.equal(stat.largest_share, 0.5);
  assert.equal(stat.floaters, 0);
  assert.equal(stat.assembled, false);

  const set = assembly(json, { kind: 'set' });
  assert.equal(set.components, 2);
  assert.equal(set.largest_share, 0.5);
  assert.equal(set.floaters, 0);
  assert.equal(set.assembled, true);
});

test('a box lifted off the ground touching nothing is a floater', () => {
  const json = jsonOf(glbWith([{ min: [0, 0.5, 0], max: [1, 1.5, 1] }], [{ mesh: 0 }]));
  const a = assembly(json);
  assert.equal(a.parts, 1);
  assert.equal(a.components, 1);
  assert.equal(a.floaters, 1);
  assert.ok(near(a.min_y, 0.5));
  assert.ok(near(a.ground_gap, 0.5));
  assert.equal(a.assembled, false);
});

test('a box resting on another box is not a floater', () => {
  const json = jsonOf(glbWith([{ min: [0, 0, 0], max: [1, 1, 1] }, { min: [0, 1, 0], max: [1, 2, 1] }], [{ mesh: 0 }, { mesh: 1 }]));
  const a = assembly(json);
  assert.equal(a.components, 1);
  assert.equal(a.floaters, 0);
  assert.equal(a.assembled, true);
});

test('a child node is translated by its parent', () => {
  const json = jsonOf(
    glbWith([{ min: [0, 0, 0], max: [1, 1, 1] }], [{ name: 'root', translation: [0, 2, 0], children: [1] }, { mesh: 0 }], {
      scene: [0],
    }),
  );
  const a = assembly(json);
  assert.equal(a.parts, 1);
  assert.equal(a.components, 1);
  assert.ok(near(a.min_y, 2));
  assert.equal(a.floaters, 1);
});

test('a node with a 90 degree quaternion rotation is transformed', () => {
  const box = { min: [0, 1, 0], max: [2, 2, 1] };
  const flat = assembly(jsonOf(glbWith([box], [{ mesh: 0 }])));
  assert.equal(flat.floaters, 1, 'the unrotated box is lifted off the ground');

  const rotated = assembly(
    jsonOf(glbWith([box], [{ mesh: 0, rotation: [0, 0, 0.7071067811865476, 0.7071067811865476] }])),
  );
  assert.equal(rotated.parts, 1);
  assert.ok(near(rotated.min_y, 0));
  assert.equal(rotated.floaters, 0);
});

test('a node using a matrix is transformed', () => {
  const matrix = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 3, 4, 5, 1];
  const a = assembly(jsonOf(glbWith([{ min: [0, 0, 0], max: [1, 1, 1] }], [{ mesh: 0, matrix }])));
  assert.equal(a.parts, 1);
  assert.ok(near(a.min_y, 4));
  assert.ok(near(a.ground_gap, 4));
  assert.equal(a.floaters, 1);
});

test('malformed json never throws', () => {
  const malformed = [null, 42, 'nope', { nodes: [{ mesh: 0, children: [0] }] }];
  for (const input of malformed) {
    let a;
    assert.doesNotThrow(() => {
      a = assembly(input);
    });
    assert.equal(a.parts, 0);
    assert.equal(a.assembled, false);
    assert.equal(typeof a.error, 'string');
  }
});

test('makeGlb without the new options is byte-identical to the loader-era builder', () => {
  const cases = [
    [{}, 'f1af6e21ec01fed0c00eadc0c09928c762172c31d8b2df337f4a4284413cbd58'],
    [{ triangles: 12, indexed: false }, 'abc817f1af2cd868279b822239b66add07c9bcf11ff8dcc053056297f163f4a6'],
    [{ triangles: 2, meshes: 3 }, '24ce83de46b329872f60c30ce76d4695e0d9a17a2f3adedd27bdad6074ee1de8'],
    [{ triangles: 1, animations: 2 }, '1446c63af029d48b26fe04964c41116a1a126d039d3030fe885647a52cc8bfb3'],
    [{ triangles: 1, badMagic: true }, '24766b0d8da58c51151a91066b920c703310033fd71c0dbb11630fed3557b7e7'],
    [{ triangles: 1, version: 1 }, '08ea5f514646fd9c9622295e7b6449bf4d681d3416928d16a8a6c118f971ce1e'],
  ];
  for (const [opts, hash] of cases) {
    assert.equal(crypto.createHash('sha256').update(makeGlb(opts)).digest('hex'), hash);
  }
});

test('parseGlb keeps every previous field and adds assembly', () => {
  const glb = makeGlb({ triangles: 2, meshes: 3 });
  const r = parseGlb(glb);
  assert.equal(r.ok, true);
  assert.equal(r.reason, null);
  assert.equal(r.bytes, glb.length);
  assert.equal(r.version, 2);
  assert.equal(r.meshes, 3);
  assert.equal(r.primitives, 3);
  assert.equal(r.triangles, 6);
  assert.equal(r.vertices, 18);
  assert.equal(r.materials, 1);
  assert.equal(r.nodes, 3);
  assert.equal(r.animations, 0);
  assert.deepEqual(r.bbox, { min: [0, 0, 0], max: [25, 1, 2], size: [25, 1, 2] });
  assert.equal(typeof r.assembly, 'object');
  assert.equal(r.assembly.parts, 3);
  assert.equal(r.assembly.components, 3);
  assert.equal(r.assembly.floaters, 0);
  assert.equal(r.assembly.assembled, false);
});
