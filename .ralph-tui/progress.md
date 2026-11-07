# Ralph Progress Log

This file tracks progress across iterations. Agents update this file
after each iteration and it's included in prompts for context.

## Codebase Patterns (Study These First)

- JS tests live in `tests/js/*.test.mjs`, use `node:test`/`node:assert/strict`, and must be imported from
  `tests/js/index.js` or `bash scripts/check.sh` will not run them.
- GLB test fixtures are built in code (`tests/js/glb_util.mjs`) instead of checked-in binaries: a 12-byte header,
  a space-padded JSON chunk and a zero-padded BIN chunk. `scripts/glb_check.mjs` is dependency-free and guards its
  CLI with `import.meta.url === pathToFileURL(process.argv[1]).href`.
- GLB mode serves `GLTFExporter.js` locally, but the exporter also imports `../utils/TextureUtils.js`; both URLs must
  be routed or the page dies with `js_error`/`no_download`.
- Offline browser tests can prove "no network" without changing report rows: set `VALIDATE_REQUEST_LOG=FILE` and the
  validator records every request it did not serve locally (empty list = pass).
- Offline Python HTTP tests patch `urllib.request.urlopen` with a fake taking `(req, timeout=None)` that records
  `json.loads(req.data)` and returns an object whose `read()` yields the response body.
- `scripts/glb_bench.py` stays stdlib-only and offline-testable: `plan(models, args)` builds command lists, refusals
  raise `BenchError` which `main()` turns into an argparse exit 2, and tests patch `subprocess.run` to prove a
  refused run started nothing.
- `scripts/glb_report.py` keeps the report maths in pure functions (`wilson`, `metrics`, `head_to_head`,
  `recognisable`) and a thin `main()`; fixtures live under `tests/fixtures/glb_bench/<model>/validation.jsonl`
  with `raw/<id>.json` usage rows, so the CLI tests copy the folder to a tmp dir and inspect report.json/report.md.
---

## 2026-11-07 - US-001
- Added a dependency-free GLB parser (`parseGlb`) with counts for meshes, primitives, triangles, vertices,
  materials, nodes, animations and an accessor-union bbox; it returns `bad_glb`/`empty_glb` instead of throwing.
- Added the `node scripts/glb_check.mjs FILE.glb` CLI (one JSON line, exit 0/1) and a `makeGlb` fixture builder.
- Files changed: `scripts/glb_check.mjs`, `tests/js/glb_util.mjs`, `tests/js/glb_check.test.mjs`,
  `tests/js/index.js`, `docs/13-glb-code-track.md`.
- **Learnings:**
  - `makeGlb` writes each mesh with distinct x offsets (mesh index * 10), so the bbox union is easy to assert
    against the accessors and matches `[0,0,0]..[25,1,2]` for 3 meshes x 2 triangles.
  - Parse errors are cheap to detect in header order: magic, version, declared length (catches truncation), then
    the JSON chunk type and payload; wrapping the whole function in try/catch keeps the never-throw promise.
---


## 2026-11-07 - US-002
- Added `--mode scene|glb` (default scene) and `--glb-dir` (default data/glb) to `scripts/validate_scenes.mjs`.
  GLB mode allows Three.js core plus `GLTFExporter.js` from cdnjs/jsDelivr/unpkg, serves them from local 0.160.0,
  records `stats.three_requested`/`version_rewritten`, drops `static`/`no_loop`, clicks the first visible
  button/a/[role=button] matching `/export|download|glb/i`, waits up to 20 s for a download, and scores it with
  `parseGlb`. Reasons match docs/13 5.1 (`no_export_button`, `no_download`, `export_error`, `bad_glb`, `empty_glb`).
- Added `VALIDATE_REQUEST_LOG=FILE`: records every request not served locally, used by the offline test to assert
  zero network requests in both modes.
- Added `tests/fixtures/glb_raw/` (g_ok, g_unpkg, g_anim, g_nobutton, g_throws, g_orbit, g_trunc and
  scene_mode_expected.jsonl) and `tests/js/validate_glb.test.mjs`, imported from `tests/js/index.js`.
- Files changed: `scripts/validate_scenes.mjs`, `tests/js/validate_glb.test.mjs`, `tests/js/index.js`,
  `tests/fixtures/glb_raw/*`, `docs/13-glb-code-track.md`, `.ralph-tui/progress.md`.
- **Learnings:**
  - `GLTFExporter.js` imports `../utils/TextureUtils.js`; serve it locally as a transitive dependency, but still
    report a direct `TextureUtils` import in an answer as `bad_import`.
  - Blob-URL anchor downloads do fire Playwright's `download` event; `download.saveAs()` writes the GLB directly.
  - A 20 s download wait makes a throwing button handler slow, so race the download against the pageerror list.
  - The existing `tests/fixtures/raw` rows contain no doctype and no fenced block, so scene mode reports `no_html`
    for all six; that is the captured baseline in `scene_mode_expected.jsonl`.
---

## 2026-11-07 - US-003
- Added `--system FILE` (default still `prompts/system.txt` via `common.system_prompt()`), plus `--top-k`,
  `--min-p` and `--repeat-penalty` (default `None`; omitted from Ollama `options` unless given, so `--min-p 0`
  is sent as `0.0`). Each saved raw row gains `system_file` and `system_sha256` of the exact text sent.
- Files changed: `scripts/teacher_generate.py`, `tests/py/test_teacher_generate.py`, `README.md`,
  `.ralph-tui/progress.md`.
- **Learnings:**
  - Fake `urllib.request.urlopen(req, timeout=None)` captures `json.loads(req.data)` and returns an object whose
    `read()` yields the `/api/chat` JSON; no real connection is opened.
  - `--system` text is sent byte-for-byte (no `.strip()`), so the saved `system_sha256` hashes exactly what the
    model receives; the default path keeps the old stripped `common.system_prompt()` behaviour.
  - Patch `sys.argv` and call `teacher_generate.main()` directly with `--ollama-native` to avoid constructing the
    OpenAI client during tests.
---

## 2026-11-07 - US-004
- Added `bench/glb/models.json` with the six docs/13 rows (only `ccore-q8` and `glimmer` enabled, `spark-open` paid).
- Added `scripts/glb_bench.py`: argparse CLI, pure `plan(models, args)` returning generate-then-validate command
  pairs, refusals for `--out-root` under `data/`/`out/`, missing or placeholder system prompts, paid rows without
  `--allow-paid`, unknown `--only`, and a one-time `ollama list` check on real runs.
- Added `tests/py/test_glb_bench.py` (13 tests): six-row config, per-model plan flags/order, `--only` on a disabled
  row, every refusal with `subprocess.run` patched to fail if called, and a dry-run subprocess that creates nothing.
- Documented every flag in README.md under "GLB benchmark (code track)".
- Files changed: `bench/glb/models.json`, `scripts/glb_bench.py`, `tests/py/test_glb_bench.py`, `README.md`,
  `.ralph-tui/progress.md`.
- **Learnings:**
  - `plan()` does selection itself, so `plan(all_six_rows, args)` is the single source of truth for "the two enabled
    rows"; tests never need to pre-filter.
  - Refusals use `argparse.ArgumentParser.error`, which exits 2; tests patch `subprocess.run` to prove no command ran.
  - `--dry-run` must not create the out root: `plan()` only builds strings and `main()` returns before any `mkdir`.
---

## 2026-11-07 - US-005
- Added `scripts/glb_report.py`: pure `wilson`, `load_model`, `metrics`, `head_to_head`, `recognisable`, plus
  `build_report` and a CLI that writes `<root>/report.json` and `<root>/report.md`.
- `metrics` scores every brief in the briefs file, so a brief absent from a model's `validation.jsonl` is a failure
  with reason `missing`; animated pass requires `ok` **and** `stats.glb.animations > 0`.
- The markdown has one row per model with pass rate and its 95% Wilson interval, then failures, by-domain and
  head-to-head tables. With no `--ratings` the recognisable column prints `not rated`.
- Added `tests/fixtures/glb_bench/` (6 briefs across static/animated/set, two model folders, raw usage rows, a
  shuffled `rating.csv` and `key_map.json`) and `tests/py/test_glb_report.py` (10 tests).
- Documented `--root`, `--briefs`, `--ratings`, `--key-map` and the report outputs in README.md.
- Files changed: `scripts/glb_report.py`, `tests/py/test_glb_report.py`, `tests/fixtures/glb_bench/*`, `README.md`,
  `.ralph-tui/progress.md`.
- **Learnings:**
  - `round(wilson(24, 48), 3)` is `(0.364, 0.636)` but `wilson(48, 48)[1]` is `0.9999999999999999`; clamp the
    interval to [0, 1] and round in assertions instead of expecting exact 1.0.
  - Export rate is easiest to define as `stats.glb` being present: the validator only sets it after a download and
    `parseGlb` call, so `bad_glb` still counts as exported.
  - Fixture design: m_a passes b4 (`ok: true`) with `animations: 0` so the animated-pass test fails if the
    `animations > 0` half is dropped; b6 is absent from both files to exercise the `missing` rule.
---
