# Running the muse-threejs build with Ralph TUI

Ralph runs one coding agent per **story** against a PRD, marks it `passes: true` when its criteria hold, and
moves on. Each iteration is a fresh agent with no memory, so every story names the files and docs it needs.
Command Code (`command-code-go` agent) first, local Ollama through
opencode only when Command Code credit runs out.

## The four PRDs (run in this order)

| # | PRD | Stories | What it builds | Manual gate afterwards |
|---|-----|---------|----------------|------------------------|
| 1 | `prd-01-hardening.json` | 6 | tests for every pilot script, balanced domains, validator module with resume, pilot report and contact sheet | read the pilot report on the real 51-brief run |
| 2 | `prd-02-corpus.json` | 5 | brief growth, chunked overnight driver, repair pass, merge and de-duplication, optional quality score | run the ~18 h Glimmer corpus job yourself |
| 3 | `prd-03-training.json` | 5 | data validator, token stats, MLX probe and wrapper, guarded RunPod runbook, train_sft options | MLX smoke train; approve any GPU spend |
| 4 | `prd-04-eval-export.json` | 5 | eval harness with pass@k, comparison report, export helpers, rejection sampling, docs test | evaluate baselines and the student |
| 5 | `prd-05-mesh.json` | 6 | **mesh track:** augmentation, text-to-GLB, four-angle renders, caption script, leak-free dataset builder, eval report | read the baseline quality report |
| 6 | `prd-06-captions-corpus.json` | 9 | **mesh track:** category tags, fact-grounded caption styles, caption quality filter, model bake-off, consensus corpus with provenance, prompt variants, CC0 kit intake with licence ledger, corpus report | run the bake-off and the real caption run yourself |
| 7 | `glb-1.prd.json` | 7 | **GLB code track:** GLB parser, validator `--mode glb`, per-model prompt and sampling, resumable benchmark runner, report with Wilson intervals and head-to-head, blind contact sheet, docs-consistency test | paste ccore's verbatim system prompt, run the benchmark overnight, rate `rating.csv` blind and record the outcome in docs/13 section 10 |
| 8 | `imp-1.prd.json` | 8 | **GLB improvement track (offline):** assembly metric, repair retry, best-of-N picker, phase 2 data from ccore's set, LoRA cost estimate, docs wiring | review the imp-1 diff, then run `imp-ops.prd.json` locally |
| 9 | `imp-ops.prd.json` | 8 | **GLB improvement ops (local only):** assembly backfill, repair on v3's failures, two more v3 seeds and best of 3, phase 2 dataset build, all through `scripts/imp_ops.sh` | rate the best-of-3 sheet and approve the phase 2 LoRA spend (docs/14 section 8) |
| 10 | `imp-2.prd.json` | 4 | **GLB improvement 2 (offline):** assembly repair mode in `glb_repair.py`, adaptive best-of-N cost simulator, `Assembled (of all briefs)` report column and the `repair-asm` rows, `imp_ops.sh` assembly-repair jobs | review the imp-2 diff, then run `imp-ops-2.prd.json` locally |
| 11 | `imp-ops-2.prd.json` | 4 | **GLB improvement ops 2 (local only):** assembly repair on v3 seed 1 and seed 3, adaptive best-of-N cost and the result reports, all through `scripts/imp_ops.sh` | rate a blind sample of the repaired assets before claiming a quality gain (docs/14 section 8) |
| 12 | `imp-3.prd.json` | 4 | **GLB improvement 3 (offline):** the `--ids-file` brief filter in the generator and bench, `glb_adaptive_ids.py` to list briefs still lacking a valid, assembled candidate, and the assembly-repair report fix | review the imp-3 diff, then run `imp-ops-3.prd.json` locally |
| 13 | `imp-ops-3.prd.json` | 6 | **GLB improvement ops 3 (local only):** fresh seeds 4-6 through `scripts/imp_ops.sh` (`start ad4`/`ad5`/`ad6`, seeds 5 and 6 on the remaining briefs only), the best pick, a blind sheet and RESULTS3 | rate the adaptive sheet blind and record the live numbers (docs/14 section 10) |
| 14 | `imp-4.prd.json` | 4 | **GLB improvement 4 (offline):** the one-command `scripts/glb_generate.py` — sample the frozen prompt until valid and assembled, one repair turn, batch mode with a per-run summary, then the docs and index wiring | review the imp-4 diff, then rate the generated assets blind before claiming better than best-of-3 (docs/14 sections 9 and 11) |
| 15 | `imp-5.prd.json` | 8 | **GLB improvement 5 (offline):** ground each exported GLB, an oriented-box touch check, the generator's triangle-budget stop and assembly-repair fallback, the `imp_ops.sh` real-parser test, 540 new non-eval distillation briefs and `glb_distill_prep.py` | run the overnight self-distillation through `scripts/imp_ops.sh start distill-smoke`/`start distill`, prep with `glb_distill_prep.py`, and approve any training (docs/14 section 12) |

PRDs 5 and 6 are the mesh track (docs/08-mesh-track.md). PRD 6 needs PRD 5 finished first because it edits
`caption_meshes.py` and `build_mesh_dataset.py`. PRDs 1 to 4 are the Three.js-code track and can wait.
Run the mesh track with `ralph/run-all.sh --only 5` and then `--only 6`; plain `run-all.sh` starts at PRD 1.

The GLB benchmark is docs/13-glb-code-track.md and is built from `ralph/glb-1.prd.json` (not one of the numbered
`prd-*` files, so `run-all.sh` does not pick it up). Run it on its own:

```bash
ralph/run-models.sh ralph/glb-1.prd.json
```

Ralph builds the tools and never runs the benchmark, so docs/13 section 10 stays `not run` until the owner records
a result.

Ralph builds and tests tools. It never calls Baseten or Hugging Face, never trains, never rents a GPU, never
touches `data/`, `out/` or `eval/`, and never commits (`autoCommit = false`).

## One-time setup

```bash
cd muse-threejs   # the repository root
python3 ralph/build_prds.py        # builds ralph/prd-*.json from ralph/src and validates them
ralph-tui --version                # tested with 0.12.0
ls ~/.config/ralph-tui/plugins/agents/command-code-go.js   # the Command Code agent plugin
export CMDC_KEY=...                # only needed for the opencode fallback
```

Optional: `git init` here so you can review each PRD with `git diff` (the folder is not a repo yet).

## Run

```bash
ralph/run-all.sh                   # all four PRDs, one after another, headless; stops at the first unfinished one
ralph/run-all.sh --only 1 --tui    # one PRD with the TUI
ralph/run-all.sh --from 3          # start at PRD 3
ralph/run-models.sh ralph/glb-1.prd.json   # the GLB benchmark PRD, several models in turn
python3 ralph/build_prds.py --status   # stories passing per PRD and the next story's notes
```

- A PRD is finished only when every story is `passes: true`; the runner stops otherwise so a half-done PRD never
  feeds the next one. Interrupted runs resume where they stopped.
- "Failed to resume session" means the last run was killed mid-story: delete `.ralph-tui/session.json` and rerun (finished stories stay finished).
- A story Ralph cannot finish gets `notes`. Read them, edit `ralph/src/prd-*.json` if the story was wrong, rebuild
  with `python3 ralph/build_prds.py` (progress already written is kept), and rerun.
- Edit stories in `ralph/src/`, never in the built `ralph/prd-*.json`.

## Fall back to Ollama (Command Code credit gone)

In `.ralph-tui/config.toml` set `agent = "opencode"` and `model = "ollama/qwen3.8:27b"`. Do not run it while the
Glimmer corpus job is running: both want the same GPU.

## Quality gate

Every story ends with `bash scripts/check.sh`: `py_compile` on all scripts, `node --check`, `bash -n`, then
`pytest tests/py` and `node --test tests/js` when those folders exist.
