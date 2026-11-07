# Running the muse-threejs build with Ralph TUI

Ralph runs one coding agent per **story** against a PRD, marks it `passes: true` when its criteria hold, and
moves on. Each iteration is a fresh agent with no memory, so every story names the files and docs it needs.
Same setup as pixitween-director: Command Code (`command-code-go` agent) first, local Ollama through
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

PRDs 5 and 6 are the mesh track (docs/08-mesh-track.md). PRD 6 needs PRD 5 finished first because it edits
`caption_meshes.py` and `build_mesh_dataset.py`. PRDs 1 to 4 are the Three.js-code track and can wait.
Run the mesh track with `ralph/run-all.sh --only 5` and then `--only 6`; plain `run-all.sh` starts at PRD 1.

Ralph builds and tests tools. It never calls Baseten or Hugging Face, never trains, never rents a GPU, never
touches `data/`, `out/` or `eval/`, and never commits (`autoCommit = false`).

## One-time setup

```bash
cd /Users/irfankhan/Documents/code/trolio/muse-threejs
python3 ralph/build_prds.py        # builds ralph/prd-*.json from ralph/src and validates them
ralph-tui --version                # tested with 0.12.0 in pixitween-director
ls ~/.config/ralph-tui/plugins/agents/command-code-go.js   # the Command Code agent plugin
export CMDC_KEY=...                # only needed for the opencode fallback
```

Optional: `git init` here so you can review each PRD with `git diff` (the folder is not a repo yet).

## Run

```bash
ralph/run-all.sh                   # all four PRDs, one after another, headless; stops at the first unfinished one
ralph/run-all.sh --only 1 --tui    # one PRD with the TUI
ralph/run-all.sh --from 3          # start at PRD 3
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
