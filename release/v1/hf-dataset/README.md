---
license: apache-2.0
task_categories:
  - text-generation
tags:
  - text-to-3d
  - threejs
  - glb
  - low-poly
  - game-assets
  - synthetic
size_categories:
  - n<1K
configs:
  - config_name: default
    data_files:
      - split: train
        path: train.jsonl
      - split: validation
        path: val.jsonl
---

# Meshwright distill v1 (meshwright-glimmer-30b-lora-distill)

463 examples of a one-line asset brief paired with a complete Three.js page that builds a low-poly game asset
and exports it as GLB. It is the self-distillation set for Meshwright v2: every answer was written by
Muse Glimmer 30B running the Meshwright v1 setup, then kept only if it passed automatic checks.

> Generated with Muse Glimmer 30B (Apache 2.0). Independent project, not affiliated with or endorsed by Meta.

## Splits

| Split | Rows |
|---|---|
| train | 424 |
| validation | 39 |

By kind: 275 static, 107 animated, 81 sets. Twelve domains with 31-43 rows each: buildings, characters,
creatures, fantasy and medieval, food, furniture, modular kits, nature, props and tools, sci-fi, vehicles,
weapons and armour.

## Row format

```json
{"id": "x0001", "domain": "buildings", "title": "Timber cabin",
 "prompt": [{"role": "system", "content": "<system prompt>"}, {"role": "user", "content": "<brief>"}],
 "completion": [{"role": "assistant", "content": "```html ... ```"}]}
```

Answers only, no reasoning traces. The system message is the frozen v3 prompt (sha256
`712c3784165adf8f9a1c3cc380e11513c575109730ff7b224bb2a37a2998130d`). Answer length: median 6,099 characters,
maximum 9,371.

## How it was made

1. **Briefs.** 540 briefs over 12 domains, drafted with an AI coding agent during development and checked
   against the 48 evaluation briefs and their subjects so no eval subject appears (0 leaks dropped at the end).
2. **Answers.** Muse Glimmer 30B (4-bit MLX build in Ollama, thinking off, temperature 0.7, top_p 0.95) through
   an adaptive best-of-3 loop with error repair and assembly repair. About 34 hours on one Mac.
3. **Filter.** Each answer was loaded in headless Chromium, its Export GLB button clicked and the GLB parsed.
   Kept: valid GLB, parts assembled into one grounded object, at most 5,000 triangles. Dropped: 65 not
   assembled, 12 over the triangle budget.

## Limits

- The filter is automatic. Nobody has rated these assets by eye, so "passes the checks" is not "looks good".
- Training on this set teaches the model what the filter rewards. Evaluate any model trained on it by a blind
  human rating, not only by the same checks.
- Pages load Three.js 0.160.0 from jsDelivr.

## Licence

Apache 2.0.
