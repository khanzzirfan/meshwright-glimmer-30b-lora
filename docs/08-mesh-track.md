# 08. Mesh track: Muse writes 3D models (not just Three.js code)

Goal: fine-tune a Muse model so a prompt like "a wooden chair with a ladder back" returns a
low-poly mesh as text, which loads as a GLB. Training data is CC0 3D assets. This is the
LLaMA-Mesh recipe with Muse as the model. The Three.js-code track (docs 01-07) stays as the fallback.

## Source assets (all CC0, licence file ships with each pack)
| Pack | Where | Kept models |
|---|---|---|
| Kenney car-kit, city-kit-commercial, city-kit-roads | `eyecast-api-monorepo/debug/special-kits/kenney` | 168 |
| Quaternius downtown-city, medieval-village, stylized-nature megakits | `.../special-kits/quaternius` | 354 |
| PixiTween props (30 `q-*` Quaternius plus 13 others, **licence of the 13 unconfirmed**) | `pixitween-director/web/public/cartoon/props` | 43 |

Each pack folder also holds `clay/` (untextured copies) and `original/` (the zip); the converter skips both.

## Text format
```
v 43 63 17        vertex, integer 0..63 per axis (x, y, z)
c #5a3b2e         starts a colour group (material base colour)
f 1 2 3           triangle, 1-based vertex indices, belongs to the latest `c`
```
Rules the converter applies: scene nodes flattened to world space; longest side scaled to 1, centred
on x and z, standing on y = 0; coordinates quantised to 64 bins (same as LLaMA-Mesh); duplicate
vertices merged; degenerate and repeated faces dropped; models over 2,000 triangles skipped.

## Run it
```bash
K=/Users/irfankhan/Documents/code/trolio/eyecast-api-monorepo/debug/special-kits
.venv/bin/python scripts/glb_to_text.py --root $K/kenney --root $K/quaternius \
  --root /Users/irfankhan/Documents/code/trolio/pixitween-director/web/public/cartoon/props --check
node scripts/preview_mesh.mjs --n 30 --out data/mesh/preview.png     # contact sheet to eyeball
```
Output: `data/mesh/assets.jsonl` (`id, name, pack, source, verts, tris, text`).

## Result of the first run (3 Nov 2026)
565 meshes kept; 50 skipped as too big, 11 as exact duplicates. Triangles: median 128, p90 924, max 1,986.
Text length: median about 2,200 characters, so most fit easily in a few thousand tokens.
The contact sheet shows chairs, a bed, a van, a tractor, a plant and a cake recognisable after quantisation.

## Known gaps
- **Colour.** Only the material base colour is read. Kits that use a texture atlas (cars, some nature
  pieces) come out grey. Either accept shape-only data for those or sample the atlas per face.
- **Size.** 565 meshes is a start, not enough alone. Plan: augment (rotate, scale, recolour, mirror),
  and add more CC0 kits (Kenney and Quaternius publish many; Poly Pizza; filtered Objaverse).
- **Variety.** Today it is mostly city, medieval, nature and cars. Furniture, food and props need more packs.
- **Captions not written yet.** Next: render each mesh from 4 angles and have a Muse model describe it.
  Spark Open is the intended captioner but its licence and whether it accepts images are unverified;
  Glimmer is the fallback for text-only captions from names and tags.
- **Student.** Glimmer 30B needs HF weights, a GGUF-capable llama.cpp and a rented GPU (see docs 04-05);
  none of that is confirmed yet.

## Quality, not just validity
`mesh_validate.validate` only checks structure, so a 12-triangle cube passes for "construction barrier".
`scripts/mesh_quality.py` compares each answer with the real object:
- **fscore**: F-score of surface samples at a 4-bin tolerance (about 6% of the size), best over 4 quarter
  turns and a mirror. Primary shape metric; forgives small proportion changes a vague caption cannot pin down.
- **iou**: voxel IoU of surface samples, 16^3 grid. Stricter; shown for reference.
- **face_ratio**: generated triangles / reference triangles.
- **detailed** = valid and fscore >= 0.5 and face_ratio >= 0.25.

```bash
python scripts/mesh_quality.py --run eval/mesh_baseline --pairs data/mesh/baseline_pairs.jsonl
node scripts/preview_mesh.mjs --in data/mesh/baseline_pairs.jsonl --n 100 --out data/mesh/baseline_pairs.png
```
The PNG alternates reference and generated meshes. Writes `quality.json` into the run folder.

Untrained Glimmer, 3-shot, 30 held-out captions (3 Nov 2026): 9 valid, **0 detailed**. Median fscore of the
valid answers 0.17, median face ratio 0.20. 11 of 30 hit the 9,000-token cap and all 11 are invalid: Glimmer keeps
emitting vertices and does not stop. Its valid answers are often the right idea (a cone for "cone", a crate for
"prop crate") but 5-10x coarser than the real asset. Plants, grass, doors and rocks mostly fail. Some captions repeat
across objects (name-derived), which makes a few low scores unfair; see docs/00-architecture.md section 7.

## Next steps
1. Caption the 565 meshes (4-view renders, then Muse).
2. Build `train.jsonl` (prompt = caption, completion = mesh text) with augmentation.
3. Mesh validator for model output: parses, has at least N faces, not flat, renders non-blank; reuse as the eval pass rate.
4. Baseline: plain Glimmer on 30 held-out captions, measured with that validator.
