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

`glb_report.py` carries this: `Assembled (of valid)`, `Assembled (of all briefs)` and `Median parts` are appended from `assembly.jsonl` (or `stats.glb.assembly` in the validation rows; `not computed` when a model has neither) and `Good (rated 2), secondary` is the share of briefs rated exactly 2 next to the recognisable rate; `Assembled (of valid)` is the assembled count over the measured rows while `Assembled (of all briefs)` divides the same count by every brief, so a model cannot look better by failing more. `--extra-runs NAME=DIR` (repeatable) adds a derived run as an extra row: a repair directory (`<model>/repair`, section 5) is labelled `<model> after 1 repair` and its pass count is the original ok ids plus the repaired ids, and a `repair-asm` directory (section 5) is labelled `<model> after assembly repair`, taking the repaired ok and assembled values for the ids in its `summary.json` `ids_repaired` and the original run's values elsewhere, so single-shot, repair and best-of-3 sit side by side. The repaired assembled values come from `repair-asm/assembly.jsonl`, falling back to each validation row's `stats.glb.assembly` when that file is missing (imp-3; the imp-ops-2 layout, where the row silently kept the originals).

`scripts/imp_ops.sh` is the only way the imp-ops PRD starts the long local jobs, so an operator agent never runs a raw bench or repair command. It runs one job at a time, detached and resumable: `bash scripts/imp_ops.sh preflight`, `start JOB`, `wait JOB [SECONDS]` (540 s cap) and `status`. `start v3s2` runs `.venv/bin/python scripts/glb_bench.py --out-root runs/glb_v3 --only glimmer-v3 --seed 2 --run-suffix=-s2`, `start v3s3` is the same with `--seed 3 --run-suffix=-s3`, and `start repair-v3` runs `.venv/bin/python scripts/glb_repair.py --run runs/glb_v3/glimmer-v3 --model-row glimmer-v3`. The assembly repair of section 5 is two more jobs: `start repair-asm-v3` runs `.venv/bin/python scripts/glb_repair.py --run runs/glb_v3/glimmer-v3 --model-row glimmer-v3 --mode assembly` and `start repair-asm-v3s3` is the same on `runs/glb_v3/glimmer-v3-s3` (same `--model-row glimmer-v3`). `start` refuses unless `runs/glb_v3/PROMPT_FROZEN.json` matches `prompts/system_glb_v3.txt` and refuses a second job while one is alive; `IMP_OPS_DRY=1 start JOB` prints the command instead. The live adaptive run (section 6, imp-3) adds three more bench jobs: `start ad4` runs the bench on all 48 briefs with `--seed 4 --run-suffix=-s4`, `start ad5` adds `--seed 5 --run-suffix=-s5 --ids-file=runs/imp/adaptive/ids_after_s4.txt` and `start ad6` adds `--seed 6 --run-suffix=-s6 --ids-file=runs/imp/adaptive/ids_after_s5.txt`, so seeds 5 and 6 sample only the briefs that still lack a valid, assembled candidate (`glb_adaptive_ids.py`, section 6). `start ad5`/`ad6` refuses when its ids file is missing and prints `nothing to do` (exit 0) when the file is empty (nothing left to sample), and its job total is that file's line count (48 when the file is absent). `IMP_OPS_ADAPTIVE` overrides the ids directory (`runs/imp/adaptive`), as the tests need.

## 4. Assembly metric (A)

Computed from the exported GLB only, in `scripts/glb_check.mjs`, as `assembly(json)`:

- Walk the node tree from the scene roots and apply each node's `matrix`, or its `translation`/`rotation`/`scale`, to get a world matrix per mesh node. Transform the 8 corners of each POSITION accessor's min/max box to get a world-space axis-aligned box per mesh node. Skins and morph targets are ignored.
- `parts`: the number of mesh nodes.
- Two parts touch when their boxes overlap or the gap between them on every axis is at most `tol` = 2% of the diagonal of the union box.
- `components`: connected components of the touch graph. `largest_share`: the largest component's part count divided by `parts`.
- `floaters`: parts in components of size 1 that have no box below them within `tol` (not resting on another part) and do not reach the ground (`min y > tol`).
- `min_y`: the lowest world y. `ground_gap = max(0, min_y)`.
- `assembled` (boolean): for briefs of kind `static` or `animated`, `largest_share >= 0.9 && floaters == 0 && ground_gap <= tol`. For kind `set`, `floaters == 0 && ground_gap <= tol` (several components are expected in a set).

The validator adds this to `stats.glb.assembly` in GLB mode, using the kind from the raw row's brief (`raw.brief.kind`) and falling back to the optional `--briefs FILE` flag (then `static`). It never adds a failure reason: assembly is a quality signal, not a validity rule.

`scripts/glb_assembly.mjs --run RUN_DIR --briefs FILE [--tol-frac 0.02]` backfills a run already on disk: for every row in `RUN_DIR/validation.jsonl` it writes `RUN_DIR/assembly.jsonl` with lines `{id, kind, assembly}` — the kind-aware `assembly()` result, or `null` when the row is not `ok` — reading each ok row's `RUN_DIR/glb/<id>.glb` without re-rendering, printing `assembled X of Y valid`, and never rewriting `validation.jsonl`.

Thresholds are first guesses. imp-ops US-002 compares `assembled` with the unblinded ratings, and the owner may tune `tol` once with the result recorded in section 10.

## 5. Repair retry (B)

`scripts/glb_repair.py --run RUN_DIR --model-row NAME [--models bench/glb/models.json] [--ollama-url URL] [--limit N]`

- **Selects:** ids in `RUN_DIR/validation.jsonl` with `ok == false` and a reason in {js_error, load_fail, no_download, export_error, bad_glb, empty_glb, no_export_button}. It never selects `truncated`, `no_html` or `external_dep`: those are not one-line bugs.
- **Request:** one Ollama `/api/chat` call per id, with messages [system (the model row's system file), user (the brief), assistant (the original `content`), user (the fix message)]. Sampling comes from the model row.
- **Fix message:** "The page you wrote failed when tested: <reason list>. First error: <stats.error, or 'none recorded'>. Reply with the complete corrected HTML file in one ```html block. Keep the asset the same and fix only what is broken. Remember the GLB exporter rules in the system prompt."
- **Output:** raw rows go to `RUN_DIR/repair/raw/<id>.json` (same shape as teacher_generate rows, plus `repair_of` and `fix_message`), and validation goes to `RUN_DIR/repair/validation.jsonl` with the same GLB-mode flags as the bench.
- **Summary:** it prints `repaired X of Y` and writes `RUN_DIR/repair/summary.json`.
- **Resumable:** an existing raw file is skipped.

`--mode assembly` (imp-2) repairs the other measured failure: a page that is valid but whose asset is not assembled. It selects the ok rows whose `assembly.jsonl` entry has `assembled: false` and at least 3 parts; the fix message quotes the components, the largest component's share (percent, 2 decimals), the floaters and the ground gap (metres, 2 decimals) and asks the model to move or resize parts so they touch, rest on the ground with the lowest y = 0, and stay in one `THREE.Group` named `asset`. Output goes to `RUN_DIR/repair-asm/` (same layout) and `repair-asm/summary.json` adds `mode` and `assembled_after` (the repaired rows that are also assembled). It also writes `repair-asm/assembly.jsonl` with one `{id, kind, assembly}` line per selected id (imp-3): the assembly is the repaired row's `stats.glb.assembly`, or `null` when the row is not ok, and the kind comes from the original entry or the brief, so the report's assembly-repair row reads the repaired values instead of silently keeping the originals. Error mode stays the default and is unchanged.

## 6. Seeds and best-of-N (C)

- `teacher_generate.py --seed N`: passed as `options.seed` on the Ollama native route. It is recorded in each raw row and changes nothing when absent.
- `glb_bench.py --seed N --run-suffix S`: the run directory becomes `<out-root>/<name><S>`.
- `--ids-file FILE` (`teacher_generate.py`, forwarded by `glb_bench.py` as `--ids-file=FILE`, imp-3): generate only the briefs whose id is listed (one id per line, blank lines and `#` comments ignored), so a later seed runs only on the briefs that still need a sample; an id not in `--briefs` prints a warning and already-saved rows are still skipped.
- `scripts/glb_best_of.py --runs DIR [DIR ...] --briefs FILE --out DIR [--no-compute]`: for each brief, rank the candidates and copy the winner's raw JSON, GLB, screenshot and validation row into `--out`, adding `picked_from` (the winning run directory's name). It also writes `--out/assembly.jsonl` and `--out/picks.json` (`{id: {picked_from, rank_keys}}` for every brief, `null` when no run has a candidate). A run with no `assembly.jsonl` gets one from `glb_assembly.mjs`; `--no-compute` refuses instead. The output works with glb_report.py and glb_sheet.mjs. Ranking keys, in order:
  1. `ok`
  2. `assembled`
  3. parts within 8-60
  4. triangles ≤ 5000
  5. higher `largest_share`
  6. the run order given on the command line, as the tie-break

  The ranking uses only automatic signals, never the eval ratings.

`scripts/glb_best_of_cost.py --runs DIR [DIR ...] --briefs FILE [--out FILE.json]` replays samples already on disk to price an adaptive best-of-N rule (imp-2 US-002): per brief it stops at the first candidate that is `ok` and assembled, falling through to `glb_best_of.py`'s ranking otherwise, and reports mean samples, mean/median seconds and the ok/assembled shares of the picks against the always-N baseline; seconds are `raw/<id>.json` `usage.seconds`, a run without `assembly.jsonl` warns and its rows count as not assembled, and `--out` (the report JSON) must be outside `data/`, `out/` and `eval/`.

`scripts/glb_adaptive_ids.py --runs DIR [DIR ...] --briefs FILE --out FILE [--no-compute]` lists the briefs that still have no valid and assembled candidate across the runs sampled so far (imp-3 US-003), so a later seed can be limited to them: a brief is kept when no run holds a row that is both `ok` and assembled, checked with `glb_best_of.py`'s `candidates_for` (rank key 0 and 1), so the ranking is never copied and ids a run lacks are skipped. Each run needs a `validation.jsonl` (a missing one is an error); a run without `assembly.jsonl` gets one from `glb_assembly.mjs` unless `--no-compute`, when instead it warns and its rows count as not assembled. It writes one remaining id per line to `--out` and prints `remaining X of Y`.

## 7. Phase 2 data (D)

`scripts/ccore_prep.py --parquet-dir runs/ccore_data/raw --out DIR [--max-chars 22000] [--system ccore|FILE] [--leak-file bench/glb/eval_subjects.json] [--extra-run DIR ...] [--extra-system FILE] [--seed 7]`

- **Rows:** one per conversation. The prompt is [system, user] and the completion is [assistant `content` only]; `reasoning_content` is dropped because Glimmer runs without thinking. This is the conversational prompt/completion format that `scripts/mesh_lora_hf.py` reads (`check_data`), written to `DIR/train.jsonl` and `DIR/val.jsonl`. ccore's own train and validation split is kept.
- **Drop rules,** each counted in `DIR/stats.json`:
  1. no ```html block, or no "Export GLB" text
  2. answer longer than `--max-chars`
  3. title matches an eval subject (whole-word, case-insensitive, title only)
  4. duplicate answer text
- **System prompt:** the default `--system ccore` uses `prompts/ccore_glb_system.txt` verbatim. Its answers use OrbitControls and Three.js 0.160-0.170, which break our v3 rules, so the student is evaluated with ccore's prompt (`--allow-addons` and the version cache already make that fair). Using our v3 prompt instead is an owner decision (section 9).
- **`--extra-run`:** adds the valid and assembled rows of a Glimmer run (for example the best-of-3 output). Their system prompt is `--extra-system`, and rows whose brief id is in the eval briefs are refused (the whole command stops). In practice, generate extra Glimmer data on new briefs (`gen_briefs.py`), never on g001-g048.
- **`--seed`:** shuffles the train split with this seed (default 7) so domains are not clustered; the val split keeps ccore's order.
- **Stats:** `stats.json` holds kept and dropped counts by reason (per split), kept counts by domain, the completion-length median and max, the system and leak-file sha256, and the sha256 of each input parquet.

## 8. Phase 2 training (E): manual gate

The owner approves the spend first. Starting points, all of them estimates, not measurements:

- **Data:** about 600 rows after drops at `--max-chars 22000`, roughly 4-6K tokens each.
- **Method:** QLoRA on Muse Glimmer 30B with `scripts/mesh_lora_hf.py --data DIR --quant 4bit --max-len 9728 --rank 16 --epochs 2`, on an A100 80 GB or L40S. Run a 20-step smoke run first (`--max-steps 20`) and time it before running the full job.
- **Cost:** the earlier "$4-8" figure was a guess. Use `scripts/glb_phase2_estimate.py --data DIR --sec-per-step S --price-per-hour P [--epochs 2] [--grad-accum 8] [--batch 1] [--chars-per-token 3.3]` with S taken from the smoke run. It reads `DIR/train.jsonl` and `DIR/val.jsonl`, prints the rows, completion characters, an estimated token count (labelled `estimate, chars/token = X`), steps per epoch, total steps, hours and cost. Without `--sec-per-step` it prints `sec-per-step not measured: run the 20-step smoke first` and no cost, so no unmeasured number is reported (`--sec-per-step` and `--price-per-hour` are given together). It writes nothing.
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
| | assembly backfill vs ratings | assembled 26/44 (v2), 36/45 (v2-think), 26/30 (ccore-q8), 28/43 (v3); of rated-2 assets, assembled 5/11 (v2), 9/13 (v3), 21/24 (ccore) |
| | repair on v3 failures | repaired 4 of 5 |
| | best of 3 (v3) | valid 48/48, assembled 42/48 |
| | assembly repair on v3 seed 1 | repaired 15 of 15, assembled after 11 |
| | assembly repair on v3 seed 3 | repaired 14 of 14, assembled after 5 |
| | live adaptive best-of-N (seeds 4-6) | valid 48/48, assembled 45/48, mean samples 1.3750, mean seconds 84.5416 |
| | phase 2 data build | train 541, val 86 |
| | phase 2 LoRA | not run |
