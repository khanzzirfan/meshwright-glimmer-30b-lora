import { test } from 'node:test';
import assert from 'node:assert/strict';
import { makeGlb } from './glb_util.mjs';
import { assembly } from '../../scripts/glb_check.mjs';

// Read the JSON chunk back out of a GLB built by makeGlb, the way parseGlb does.
function jsonOf(glb) {
  const len = glb.readUInt32LE(12);
  return JSON.parse(glb.subarray(20, 20 + len).toString('utf8'));
}

const S = Math.SQRT1_2; // sin(45 degrees)
const Q45 = [0, 0, Math.sin(Math.PI / 8), Math.cos(Math.PI / 8)]; // 45 degrees about z
const PLANK = { min: [-1, -0.05, -0.25], max: [1, 0.05, 0.25] }; // 2.0 long, 0.1 thick, 0.5 deep
const HALF_Y = S * (1 + 0.05); // world AABB half height of a 45-degree plank
const PERP = [-S, S, 0]; // the plank's local +y axis after the 45-degree z rotation

// Two parallel planks rotated 45 degrees, `sep` apart along the perpendicular (so the real gap is
// sep - 2*thickness). The first plank rests on the ground, the second sits above it.
function planks(sep) {
  const c1 = [0, HALF_Y, 0];
  const c2 = [c1[0] + sep * PERP[0], c1[1] + sep * PERP[1], c1[2] + sep * PERP[2]];
  return makeGlb({
    triangles: 1,
    indexed: false,
    meshes: 2,
    boxes: [PLANK, PLANK],
    nodes: [
      { mesh: 0, translation: c1, rotation: Q45 },
      { mesh: 1, translation: c2, rotation: Q45 },
    ],
  });
}

test('rotated planks with overlapping AABBs but a 0.5 gap are assembled but not assembled_obb', () => {
  const a = assembly(jsonOf(planks(0.5 + 2 * 0.05)));
  assert.equal(a.parts, 2);
  // the axis-aligned boxes overlap, so the old metric joins the parts
  assert.equal(a.components, 1);
  assert.equal(a.largest_share, 1);
  assert.equal(a.assembled, true);
  // the oriented boxes really are 0.5 apart, so the stricter metric keeps them separate
  assert.equal(a.components_obb, 2);
  assert.equal(a.largest_share_obb, 0.5);
  assert.equal(a.assembled_obb, false);
  // floaters and the ground rule are the existing ones
  assert.equal(a.floaters, 0);
  assert.ok(a.ground_gap <= a.tol);
});

test('touching rotated planks are assembled and assembled_obb', () => {
  const a = assembly(jsonOf(planks(2 * 0.05)));
  assert.equal(a.components, 1);
  assert.equal(a.assembled, true);
  assert.equal(a.components_obb, 1);
  assert.equal(a.largest_share_obb, 1);
  assert.equal(a.assembled_obb, true);
});

test('the oriented check keeps the kind-aware set rule', () => {
  // Two grounded boxes a metre apart are a set but not assembled static, under both metrics.
  const json = jsonOf(
    makeGlb({
      triangles: 1,
      indexed: false,
      meshes: 2,
      boxes: [{ min: [0, 0, 0], max: [1, 1, 1] }, { min: [2, 0, 0], max: [3, 1, 1] }],
      nodes: [{ mesh: 0 }, { mesh: 1 }],
    }),
  );
  const stat = assembly(json, { kind: 'static' });
  assert.equal(stat.components_obb, 2);
  assert.equal(stat.largest_share_obb, 0.5);
  assert.equal(stat.assembled, false);
  assert.equal(stat.assembled_obb, false);
  const set = assembly(json, { kind: 'set' });
  assert.equal(set.assembled, true);
  assert.equal(set.assembled_obb, true);
});

test('a degenerate flat box does not crash and reports both assembly booleans', () => {
  const flat = jsonOf(
    makeGlb({
      triangles: 1,
      indexed: false,
      meshes: 2,
      boxes: [{ min: [0, 0, 0], max: [1, 0, 1] }, { min: [1, 0, 0], max: [2, 0, 1] }],
      nodes: [{ mesh: 0 }, { mesh: 1 }],
    }),
  );
  let a;
  assert.doesNotThrow(() => {
    a = assembly(flat);
  });
  assert.equal(typeof a.assembled, 'boolean');
  assert.equal(typeof a.assembled_obb, 'boolean');
  assert.equal(Number.isFinite(a.largest_share_obb), true);
});

test('a zero-scale node does not produce NaN', () => {
  const glb = jsonOf(
    makeGlb({
      triangles: 1,
      indexed: false,
      meshes: 1,
      boxes: [{ min: [0, 0, 0], max: [1, 1, 1] }],
      nodes: [{ mesh: 0, scale: [0, 1, 1] }],
    }),
  );
  let a;
  assert.doesNotThrow(() => {
    a = assembly(glb);
  });
  assert.equal(Number.isFinite(a.largest_share_obb), true);
  assert.equal(typeof a.assembled_obb, 'boolean');
});

test('every previous field keeps its value next to the new ones', () => {
  const a = assembly(jsonOf(planks(0.5 + 2 * 0.05)));
  for (const key of ['parts', 'components', 'largest_share', 'floaters', 'min_y', 'ground_gap', 'tol', 'assembled']) {
    assert.ok(key in a, key);
  }
  assert.equal(a.components, 1);
  assert.equal(a.assembled, true);
});
