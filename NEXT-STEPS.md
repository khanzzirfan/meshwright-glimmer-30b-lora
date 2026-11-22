# Next steps

> **22 Nov 2026: Meshwright v1 released** (Hugging Face model and dataset, Ollama `khanzz_irfan/meshwright-glimmer-30b-lora:v1`, GitHub public). Next: the cross-platform GGUF tag (Ralph `rel-1`) and v2, the first trained weights; see [docs/15-release.md](docs/15-release.md).

Tracker for muse-threejs. Tick items as they are done, add a line to the results log for every run, and record
decisions with a date. Map of files: [INDEX.md](INDEX.md).

## Imp track (8 Nov 2026): GLB improvement
- [ ] Offline build: `ralph/imp-1.prd.json` (8 stories) — assembly metric, repair retry, best-of-N picker, phase 2 data from ccore's set, cost estimate and docs wiring. Spec: [docs/14-glb-improvement.md](docs/14-glb-improvement.md).
- [ ] Local ops: `ralph/imp-ops.prd.json` (8 stories) — assembly backfill, repair on v3's failures, two more v3 seeds and the best of 3, then the phase 2 dataset build. Every job runs through `scripts/imp_ops.sh`.
- [ ] Follow-up build: `ralph/imp-2.prd.json` (4 stories) — assembly repair mode, an adaptive best-of-N cost simulator, the `Assembled (of all briefs)` report column and the `imp_ops.sh` assembly-repair jobs. Spec: [docs/14-glb-improvement.md](docs/14-glb-improvement.md).
- [ ] Follow-up ops: `ralph/imp-ops-2.prd.json` (4 stories) — assembly repair on v3 seed 1 and seed 3 plus the adaptive cost, all through `scripts/imp_ops.sh`.
- [ ] Adaptive build: `ralph/imp-3.prd.json` (4 stories) — the `--ids-file` brief filter in the generator and bench, `glb_adaptive_ids.py` and the assembly-repair report fix. Spec: [docs/14-glb-improvement.md](docs/14-glb-improvement.md) sections 3 and 6.
- [ ] Adaptive ops: `ralph/imp-ops-3.prd.json` (6 stories) — fresh seeds 4-6 (seeds 5 and 6 only on the briefs still lacking a valid, assembled candidate), then the pick and blind sheet, through `scripts/imp_ops.sh start ad4`/`ad5`/`ad6`.
- [ ] Product build: `ralph/imp-4.prd.json` (4 stories) — the one-command generator `scripts/glb_generate.py`: sample the frozen prompt until a candidate is valid and assembled, one repair turn, batch mode with a per-run summary, then the evidence section and index wiring. Spec: [docs/14-glb-improvement.md](docs/14-glb-improvement.md) section 11.
- [ ] Self-distillation build: `ralph/imp-5.prd.json` (8 stories) — ground each exported GLB, an oriented-box touch check, the generator's triangle-budget stop and assembly-repair fallback, the `imp_ops.sh` real-parser test, 540 new non-eval briefs (`bench/distill/`) and `glb_distill_prep.py`. Spec: [docs/14-glb-improvement.md](docs/14-glb-improvement.md) section 12.
- [ ] Self-distillation ops: run the overnight generation through `scripts/imp_ops.sh start distill-smoke` then `start distill`, build the training set with `glb_distill_prep.py`, and approve any training (docs/14 section 12).
- [ ] Manual gate: owner reviews the imp-1 diff, then approves the phase 2 LoRA spend (docs/14 section 8).

## Now (7 Nov 2026): GLB code benchmark
- [ ] Ralph `ralph/glb-1.prd.json` (7 stories): GLB check, validator GLB mode, bench runner, report, blind sheet. Spec: [docs/13-glb-code-track.md](docs/13-glb-code-track.md).
- [ ] Paste ccore's system prompt into `prompts/ccore_glb_system.txt`; pull the Q8_0 GGUF.
- [ ] Run phase 1 overnight, rate blind, record outcome A/B/C in docs/13 section 10.

## Where we are (3 Nov 2026)
- **Pipeline works end to end up to the dataset**: briefs, teacher, render check and SFT files all run. Training, export and eval have not run.
- **Glimmer pilot**: finished, 37 of 51 passed (72.5%). 13 are rejected as static; 8 of those have tiny non-zero motion, so the static check is probably too strict (see review).
- **Spark Open**: 28 of 30 scenes pass with `--max-tokens 32000`. Much richer scenes than Glimmer. 577,688 tokens used, not priced.
- **Ralph**: 4 PRDs, 21 stories; running PRD 1 on `nvidia/deepseek-ai/deepseek-v4.1-flash` via opencode (the free NVIDIA endpoint, `NVIDIA_NIM_API_KEY`). Local Qwen 27B was too slow (22 min for a story that did not finish). Command Code needs `cmd login`.

## Review: what we learned and what it changes
| Finding | Evidence | Change |
|---|---|---|
| Spark Open reasons a lot; 16k cap truncated 11 of 30 | median 13.7k completion tokens; rerun at 32k: 8 of 11 passed | use `--max-tokens 32000` for Spark; budget about 15k tokens per scene |
| Validator wrongly rejected import maps | Spark's first scene used `"three"` mapped to the pinned CDN | fixed in `validate_scenes.mjs`; tests added to PRD 1 US-004 |
| Static check rejects gentle motion | Glimmer rejections with frame diff 0.0006-0.0018 (swaying lamp) | PRD 1 US-005 now samples 4 frames and keeps the largest diff |
| Spark quality is well above Glimmer | same brief (b00026): bookshelf, window, cat, captions vs armchair and table | teacher choice now depends mainly on the licence and cost, not quality |
| Corpus tooling assumed Glimmer only | | PRD 2 now takes `--teacher glimmer or spark` and merges several teachers |
| Briefs are lopsided | 16 of 51 are nature; sci-fi, historical, data-viz, voxel missing | PRD 1 US-003 balances domains |
| Hackathon credit is shared | same `BASETEN_API_KEY` as the live demo, due 4 Nov 21:00 ET | no more Spark batches until the submission is in, unless capped and agreed |

## Decisions needed (owner)
- [ ] **Teacher for the full dataset**: Spark Open (better scenes, licence unchecked, unpriced) or Glimmer (Apache 2.0, free, slower, simpler scenes), or both mixed.
- [ ] **Licence**: read the Muse Model License on the [Spark Open model card](https://huggingface.co/meta-models/Muse-Spark-Open-816B-A42B) and fill in [docs/01-licensing.md](docs/01-licensing.md). Blocks any Spark-trained model leaving this Mac.
- [ ] **Thinking traces**: train with Spark's reasoning (about half of each answer) or answer-only (`--no-reasoning`). Answer-only is shorter and cheaper to train; traces may help hard scenes.
- [ ] **Goal**: general Three.js coder, or a director that writes animation-timeline JSON (see [docs/06-budget-and-risks.md](docs/06-budget-and-risks.md) question 4).
- [ ] **Publish or private**: decides how much the licence matters.

## Next steps, in order

### Now (today, free)
- [x] Glimmer pilot finished and validated (37 of 51).
- [ ] Look at the Glimmer `static` screenshots in `data/shots/` and decide whether they are real failures.
- [ ] Add `TEACHER_MODEL=meta-models/muse-spark-open-1026` to `.env` so scripts no longer need `--model`. Optionally trim `.env` to only the keys this folder uses.
- [ ] `git init` here (no commit needed yet) so Ralph's work can be reviewed with `git diff`.

### Next (after the hackathon submission)
- [ ] Ralph PRD 1 (hardening): `ralph/run-all.sh --only 1 --tui`. Then `python3 ralph/build_prds.py --status`.
- [ ] Rerun the validator on both pilots with the tuned static check from PRD 1 and record the new pass rates below.
- [ ] Ralph PRD 2 (corpus tooling).
- [ ] Generate 1,000 balanced briefs (`gen_briefs.py --append`, from PRD 2).
- [ ] Teacher run, depending on the decision above:
  - Glimmer: about 18 h overnight, free (`run_corpus.py --teacher glimmer`).
  - Spark: about 1,000 x 15k = 15M tokens; get the price first, then run in capped chunks (`run_corpus.py --teacher spark --token-budget ...`).
- [ ] Build the dataset; write the kept count, by level and domain, into the results log.

### Then (training)
- [ ] Ralph PRD 3 (training tooling).
- [ ] `token_stats.py` to pick `--max-len`.
- [ ] MLX probe; if YES, a 200-iteration smoke LoRA on this Mac. If NO, a short RunPod LoRA (approve spend first).
- [ ] First LoRA on the 1,000-scene dataset.

### Then (measure and improve)
- [ ] Ralph PRD 4 (eval and export).
- [ ] Grow the eval set to at least 50 held-out briefs (3 today is too few to compare models).
- [ ] Evaluate untouched Qwen3.5-4B, Glimmer, Spark Open and the student on the same eval briefs; fill `docs/10-results.md`.
- [ ] Export the student to GGUF, run it in Ollama, measure speed on this Mac.
- [ ] Optional: rejection-sampling round, second LoRA, compare.

## Ideas parked
- Use ccore's MIT dataset (4,146 scenes, generated by MiniMax M3.1 Flash) as extra eval briefs or extra training data (check MiniMax's output terms first).
- Blind screenshot scoring with a local vision model (PRD 2 US-005) if "renders but wrong" turns out to be common.
- GLB export variant (second dataset, different system prompt).

## Results log
Add one line per run. Numbers only from real runs.

| Date | Run | Teacher | Briefs | Passed | Tokens | Time | Notes |
|---|---|---|---|---|---|---|---|
| 3 Nov | single-scene test | Glimmer, no thinking | 1 | 1 (rendered) | 2,300 | 66 s | 40.6 tok/s |
| 3 Nov | single-scene test | Glimmer, thinking | 1 | passed static checks | 6,354 | 168 s | 37.9 tok/s; rendered, but flagged static |
| 3 Nov | smoke | Spark Open | 1 | 1 | 11,247 | 35.8 s | 314 tok/s, import map |
| 3 Nov | 30-brief batch, 16k cap | Spark Open | 30 | 19 | 393,772 | 5 min 47 s | 11 truncated |
| 3 Nov | rerun of truncated, 32k cap | Spark Open | 11 | 8 | 183,916 | 2 min 49 s | 28 of 30 overall; 1 js_error, 1 runaway |
| 3 Nov | pilot (partial, first 21) | Glimmer, no thinking | 21 | 14 | median 2,149 | median 76 s each | 6 static, 1 blank; static check likely too strict |
| 3 Nov | pilot (full) | Glimmer, no thinking | 51 | 37 (72.5%) | median 2,150 | 100 min total (118 s each, slowed by sharing the GPU) | 13 static (5 with near-zero change, 8 with tiny change 0.0004-0.0018), 2 blank; by level 1: 3/3, 2: 7/9, 3: 6/10, 4: 6/9, 7: 3/5, 8: 4/5, 9: 4/5, 10: 4/5 |
