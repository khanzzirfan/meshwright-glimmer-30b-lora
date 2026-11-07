# Ralph Progress Log

This file tracks progress across iterations. Agents update this file
after each iteration and it's included in prompts for context.

## Codebase Patterns (Study These First)

- **Local Three.js loading in headless Chromium:** serve `node_modules/three/**` through `page.route()` with a fake origin (e.g. `http://glb-sheet.local/`), and register a `request` listener that logs anything not on that origin. That log (env-var path) is how tests assert zero network requests.
- **Deterministic blind sheets:** build a mulberry32 PRNG seeded from `--seed`, shuffle model x brief rows, then assign keys (`r001`) in shuffled order so neither order nor key reveals the model. Copy PNGs to key-named paths because per-model directories leak names.
- **Resumable renderers:** skip outputs that already exist and record broken inputs in `<out>/skipped.json` instead of aborting.
- **Docs/runbook parity test:** parse the fenced bash block of docs/13 section 6, shlex-split with `comments=True`, find `scripts/<name>.py|.mjs`, and assert each `--flag` appears in that script's source. A renamed flag then fails the test; glb_sheet.mjs keeps literal flags in its usage comment so the substring check works.

---

## 2026-11-07 - US-006
- Verified/locked in `scripts/glb_sheet.mjs`: renders each `<root>/<model>/glb/<id>.glb` with the local pinned Three.js 0.160.0 GLTFLoader (3/4 + top view side by side, light grey, hemisphere + directional light), writes `<out>/<model>/<id>.png` and `<out>/<model>/sheet.png`, plus a seeded-shuffled blind `rating.csv` (`key, brief, image, rating`), `key_map.json`, and `skipped.json`.
- Added a README section documenting `--root`, `--out`, `--briefs`, `--size`, `--seed`, the blind-image copy under `images/`, and the empty-image row for briefs with no GLB.
- Files changed: README.md (docs section). Already present and passing: scripts/glb_sheet.mjs, tests/js/glb_sheet.test.mjs, tests/js/index.js (import).
- **Learnings:**
  - The story was already implemented in a prior iteration; the only missing gate was README documentation of the flags/behaviour.
  - `bash scripts/check.sh` passes (14 node tests incl. glb_sheet; pytest green; Chromium launches).
  - rating.csv must not contain a model name anywhere — images are copied to key-named files because the per-model PNG path would leak it.
---

## 2026-11-07 - US-007
- Added `tests/py/test_docs_glb.py`: parses docs/13 section 6's bash block, asserts every named script exists and every `--flag` appears in its source; a second test runs the checker on a copy with `--ratings` renamed and asserts it fails; a third asserts section 10 still says `not run`.
- Updated `INDEX.md`: docs table row 13 plus a "Bench: GLB code track" section listing `bench/glb/briefs.jsonl`, `bench/glb/models.json`, `prompts/system_glb.txt`, `prompts/ccore_glb_system.txt`; added the four GLB scripts to the scripts table.
- Updated `ralph/README.md`: glb-1 row (7 stories) with its manual gate, the standalone `ralph/run-models.sh ralph/glb-1.prd.json` run line, and a note that Ralph never records results.
- Files changed: tests/py/test_docs_glb.py (new), INDEX.md, ralph/README.md, .ralph-tui/progress.md.
- **Learnings:**
  - glb_sheet.mjs parses args via `"--" + n`, so the literal flags only exist in its usage comments; the substring check relies on those comments staying.
  - `bash scripts/check.sh` passes (14 node tests, pytest green); docs/13 section 10 was already `not run`.
---

