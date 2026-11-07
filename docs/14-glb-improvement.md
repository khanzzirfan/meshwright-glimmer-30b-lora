# 14. GLB improvement track (prefix `imp`)

Status: planned 8 Nov 2026. Follows [13-glb-code-track.md](13-glb-code-track.md). Ralph PRDs: `ralph/imp-1.prd.json` (offline build, 8 stories) then `ralph/imp-ops.prd.json` (local operator runs, 8 stories). Phase 2 training on a rented GPU is a manual gate for the owner (section 8).

## 1. Where we are

Numbers come from runs/glb_v2 and runs/glb_v3 (48 eval briefs). The quality columns are an unblinded first pass by Claude from the contact sheets, saved in `runs/glb_v3/claude_ratings_unblinded.csv`. They are not the owner's blind rating.

| Out of 48 | Glimmer v2 | Glimmer v3 | ccore Q8 |
|---|---|---|---|
| Valid GLB | 91.7% | 89.6% | 62.5% |
| Animated briefs that keep their motion | 8/11 | 7/11 | 7/11 |
| Median triangles | 581 | 994 | 2,476 |
| Median seconds per asset | 51 (Mac) | 58 (Mac) | 736 (rented 4090, not like for like) |
| Recognisable, rated 1 or 2 (unblinded) | 40 | 40 | 29 |
| Good game asset, rated 2 (unblinded) | 11 | 13 | 24 |

Under the docs/13 section 7 rule (recognisable rate), Glimmer is ahead. On good assets ccore is about twice as good: 80% of its valid outputs are good, against 25-30% for Glimmer. Three prompt versions (v1, v2, v3) all sit at 23-27% good, so prompting has plateaued.

ccore's training set (`ccore/ThreeJS-3D-GLB-Assets`, MIT, 3,501 train and 417 validation) was downloaded to `runs/ccore_data/raw/*.parquet`. A seeded sample of 300 train answers passed our GLB validator 299 times (99.7%). Answers are long: the median is 27K characters, mostly geometry code, not page boilerplate. Only 653 are 22K characters or less. The card does not name the model that generated the data, so the generator's terms are unverified (section 9).

## 2. Glimmer's failure modes (what to fix)

1. **Assembly.** This is the main one. The parts exist but are not joined: floating planks (v3 g001), chest boards in a cross (g004), the scattered bedroom set (v2 g008), the boat as one plank (v2 g016), road tiles (g046).
2. **Primitive shapes.** The apple is a sphere and the duck is two blobs. The model stops at the first primitive.
3. **Animated briefs break.** Mismatched keyframe arrays cause load_fail (g043, g044) or drop the clip (g031, g042, g048 in v3).

## 3. Plan

| # | Lever | What it fixes | Cost | Where |
|---|---|---|---|---|
| A | Assembly metric in the validator | measures failure mode 1 automatically; feeds B and the report | free | imp-1 US-001 to US-003 |
| B | One-shot repair retry | recovers js_error, load_fail and no_download answers | free, about 1 min per failed brief | imp-1 US-004, imp-ops US-003 |
| C | Best-of-3 picker | picks the valid, assembled candidate out of 3 seeds | free, 3x generation time | imp-1 US-005, imp-ops US-004 to US-007 |
| D | Phase 2 data from ccore's set (plus Glimmer's own good outputs) | teaches assembly and detail | free to build | imp-1 US-006, imp-ops US-008 |
| E | Phase 2 LoRA on Glimmer | the real quality lever | rented GPU, owner approves | manual gate, section 8 |

B and C are product features. The benchmark's primary number stays single-shot pass and recognisable rate, as frozen in docs/13. Report B and C as separate rows ("pass after 1 repair", "best of 3"), never in place of the single-shot row.

## 4. Assembly metric (A)

Computed from the exported GLB only, in `scripts/glb_check.mjs`, as `assembly(json)`:

- Walk the node tree from the scene roots and apply each node's `matrix`, or its `translation`/`rotation`/`scale`, to get a world matrix per mesh node. Transform the 8 corners of each POSITION accessor's min/max box to get a world-space axis-aligned box per mesh node. Skins and morph targets are ignored.
- `parts`: the number of mesh nodes.
- Two parts touch when their boxes overlap or the gap between them on every axis is at most `tol` = 2% of the diagonal of the union box.
- `components`: connected components of the touch graph. `largest_share`: the largest component's part count divided by `parts`.
- `floaters`: parts in components of size 1 that have no box below them within `tol` (not resting on another part) and do not reach the ground (`min y > tol`).
- `min_y`: the lowest world y. `ground_gap = max(0, min_y)`.
- `assembled` (boolean): for briefs of kind `static` or `animated`, `largest_share >= 0.9 && floaters == 0 && ground_gap <= tol`. For kind `set`, `floaters == 0 && ground_gap <= tol` (several components are expected in a set).

The validator adds this to `stats.glb.assembly` in GLB mode. It never adds a failure reason: assembly is a quality signal, not a validity rule. A backfill CLI writes `assembly.jsonl` next to an existing run's `validation.jsonl` without re-rendering, so old runs can be compared.

Thresholds are first guesses. imp-ops US-002 compares `assembled` with the unblinded ratings, and the owner may tune `tol` once with the result recorded in section 10.

## 5. Repair retry (B)

`scripts/glb_repair.py --run RUN_DIR --model-row NAME [--models bench/glb/models.json] [--ollama-url URL] [--limit N]`

- **Selects:** ids in `RUN_DIR/validation.jsonl` with `ok == false` and a reason in {js_error, load_fail, no_download, export_error, bad_glb, empty_glb, no_export_button}. It never selects `truncated`, `no_html` or `external_dep`: those are not one-line bugs.
- **Request:** one Ollama `/api/chat` call per id, with messages [system (the model row's system file), user (the brief), assistant (the original `content`), user (the fix message)]. Sampling comes from the model row.
- **Fix message:** "The page you wrote failed when tested: <reason list>. First error: <stats.error, or 'none recorded'>. Reply with the complete corrected HTML file in one ```html block. Keep the asset the same and fix only what is broken. Remember the GLB exporter rules in the system prompt."
- **Output:** raw rows go to `RUN_DIR/repair/raw/<id>.json` (same shape as teacher_generate rows, plus `repair_of` and `fix_message`), and validation goes to `RUN_DIR/repair/validation.jsonl` with the same GLB-mode flags as the bench.
- **Summary:** it prints `repaired X of Y` and writes `RUN_DIR/repair/summary.json`.
- **Resumable:** an existing raw file is skipped.

## 6. Seeds and best-of-N (C)

- `teacher_generate.py --seed N`: passed as `options.seed` on the Ollama native route. It is recorded in each raw row and changes nothing when absent.
- `glb_bench.py --seed N --run-suffix S`: the run directory becomes `<out-root>/<name><S>`.
- `scripts/glb_best_of.py --runs DIR [DIR ...] --briefs FILE --out DIR`: for each brief, rank the candidates and copy the winner's raw JSON, GLB, screenshot and validation row into `--out`, adding `picked_from`. It also writes `assembly.jsonl` and `picks.json`. The output works with glb_report.py and glb_sheet.mjs. Ranking keys, in order:
  1. `ok`
  2. `assembled`
  3. parts within 8-60
  4. triangles ≤ 5000
  5. higher `largest_share`
  6. the run order given on the command line, as the tie-break

  The ranking uses only automatic signals, never the eval ratings.

## 7. Phase 2 data (D)

`scripts/ccore_prep.py --parquet-dir runs/ccore_data/raw --out DIR [--max-chars 22000] [--system ccore|FILE] [--leak-file bench/glb/eval_subjects.json] [--extra-run DIR ...] [--extra-system FILE] [--seed 7]`

- **Rows:** one per conversation. The prompt is [system, user] and the completion is [assistant `content` only]; `reasoning_content` is dropped because Glimmer runs without thinking. This is the conversational prompt/completion format that `scripts/mesh_lora_hf.py` reads (`check_data`), written to `DIR/train.jsonl` and `DIR/val.jsonl`. ccore's own train and validation split is kept.
- **Drop rules,** each counted in `DIR/stats.json`:
  1. no ```html block, or no "Export GLB" text
  2. answer longer than `--max-chars`
  3. title matches an eval subject (whole-word, case-insensitive, title only)
  4. duplicate answer text
- **System prompt:** the default `--system ccore` uses `prompts/ccore_glb_system.txt` verbatim. Its answers use OrbitControls and Three.js 0.160-0.170, which break our v3 rules, so the student is evaluated with ccore's prompt (`--allow-addons` and the version cache already make that fair). Using our v3 prompt instead is an owner decision (section 9).
- **`--extra-run`:** adds the valid and assembled rows of a Glimmer run (for example the best-of-3 output). Their system prompt is `--extra-system`, and rows whose brief id is in the eval briefs are refused. In practice, generate extra Glimmer data on new briefs (`gen_briefs.py`), never on g001-g048.
- **Stats:** `stats.json` holds kept and dropped counts by reason, kept counts by domain, the completion-length median and max, and the sha256 of each input parquet.

## 8. Phase 2 training (E): manual gate

The owner approves the spend first. Starting points, all of them estimates, not measurements:

- **Data:** about 600 rows after drops at `--max-chars 22000`, roughly 4-6K tokens each.
- **Method:** QLoRA on Muse Glimmer 30B with `scripts/mesh_lora_hf.py --data DIR --quant 4bit --max-len 9728 --rank 16 --epochs 2`, on an A100 80 GB or L40S. Run a 20-step smoke run first (`--max-steps 20`) and time it before running the full job.
- **Cost:** the earlier "$4-8" figure was a guess. Use `scripts/glb_phase2_estimate.py --data DIR --sec-per-step S --price-per-hour P` with S taken from the smoke run.
- **Eval:** merge or convert the adapter for Ollama (`scripts/export_gguf.sh` or MLX), add a `glimmer-lora` row (disabled), and run the 12 dev briefs first, then the 48 eval briefs. Report it beside v2, v3 and ccore, with seconds per asset, because longer answers are slower on the Mac.
- **Go/no-go:** good-asset rate at least 10 points above v3, with valid GLB at or above 85% and median seconds per asset at or below 180 on the Mac.

## 9. Owner decisions

- [ ] **Generator terms** for the ccore dataset (not named on its card). Experiments on this Mac are fine. Settle the terms before any trained model leaves it.
- [ ] **Training system prompt:** ccore's verbatim prompt (the default) or our v3 prompt.
- [ ] **Leak list:** `bench/glb/eval_subjects.json` is strict (drops every chair, sword or robot). Keep it strict, or narrow it to exact titles.
- [ ] **Blind rating** of runs/glb_v2 and runs/glb_v3 sheets, to confirm or replace the unblinded numbers in section 1.

## 10. Results

| Date | Step | Result |
|---|---|---|
| 8 Nov 2026 | ccore data sample check | 299 of 300 valid (99.7%) |
| | assembly backfill vs ratings | not run |
| | repair on v3 failures | not run |
| | best of 3 (v3) | not run |
| | phase 2 data build | not run |
| | phase 2 LoRA | not run |
