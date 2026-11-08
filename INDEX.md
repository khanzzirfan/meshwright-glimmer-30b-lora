# Index

Map of everything in muse-threejs. Status and the to-do list live in [NEXT-STEPS.md](NEXT-STEPS.md).

## Start here
| File | What it is |
|---|---|
| [NEXT-STEPS.md](NEXT-STEPS.md) | Tracker: where we are, what to do next, decisions, results log |
| [docs/HANDOVER.md](docs/HANDOVER.md) | **Read first if you are taking over:** live paid resources, what is running, next steps in order |
| [README.md](README.md) | What the project is, the pipeline, quickstart |
| [ralph/README.md](ralph/README.md) | How to run the Ralph PRDs one after another (the GLB improvement pairs: `imp-1`+`imp-ops`, then `imp-2`+`imp-ops-2`) |

## Docs
| # | Doc | Read when |
|---|---|---|
| 0 | [docs/00-architecture.md](docs/00-architecture.md) | The whole picture: goal, tracks, stages, models, data, metrics, open questions (diagram: [docs/architecture.svg](docs/architecture.svg)) |
| 1 | [docs/01-licensing.md](docs/01-licensing.md) | Before training or publishing anything built from Spark Open outputs |
| 2 | [docs/02-environment.md](docs/02-environment.md) | Setting up keys, the Mac, a GPU box |
| 3 | [docs/03-pipeline-walkthrough.md](docs/03-pipeline-walkthrough.md) | Changing any pipeline stage |
| 4 | [docs/04-training.md](docs/04-training.md) | Before a training run |
| 5 | [docs/05-export-serve-eval.md](docs/05-export-serve-eval.md) | After training: GGUF, Ollama, evaluation |
| 6 | [docs/06-budget-and-risks.md](docs/06-budget-and-risks.md) | Planning spend, open questions |
| 7 | [docs/07-local-glimmer.md](docs/07-local-glimmer.md) | Running the free local teacher (measured speed) |
| 8 | [docs/08-mesh-track.md](docs/08-mesh-track.md) | The mesh track: CC0 assets as text meshes, format, quality metrics, first baseline |
| 11 | [docs/11-mesh-lora-e2e.md](docs/11-mesh-lora-e2e.md) | The mesh LoRA proof: data, train on the Mac or a GPU box, generate, score; where to run it |
| 13 | [docs/13-glb-code-track.md](docs/13-glb-code-track.md) | The GLB code track: benchmark untuned Muse Glimmer against ccore's 4B by the GLB each exports, then decide on phase 2 |
| 14 | [docs/14-glb-improvement.md](docs/14-glb-improvement.md) | The GLB improvement track: assembly metric, repair retry, best-of-N, phase 2 data and the LoRA spend gate |
| - | [docs/baseten-spark-open.md](docs/baseten-spark-open.md) | Using Spark Open on Baseten (setup, gotchas, measured 30-brief results) |

Planned by Ralph (do not exist yet): `docs/08-train-mlx.md`, `docs/09-train-gpu.md`, `docs/10-results.md`.

## Scripts
| Script | Stage | Notes |
|---|---|---|
| `scripts/gen_briefs.py` | 1. briefs | `--base-url` for Ollama; writes train and eval split |
| `scripts/teacher_generate.py` | 2. teacher answers | OpenAI route (Baseten) or `--ollama-native [--think]`; resumable; `--token-budget` |
| `scripts/baseten_smoke.py` | 2. key check | paid, needs `--yes` |
| `scripts/validate_scenes.mjs` | 3. render check | headless Chromium, local Three.js 0.160.0, import maps resolved; `--mode glb` clicks Export and checks the downloaded file |
| `scripts/glb_check.mjs` | 3. GLB check | dependency-free GLB parser; counts meshes, triangles, animations and bounds |
| `scripts/glb_bench.py` | GLB benchmark | resumable run of every enabled model in `bench/glb/models.json`, then validate |
| `scripts/glb_report.py` | GLB report | docs/13 section 5.3 metrics, Wilson intervals, head-to-head, blind ratings |
| `scripts/glb_sheet.mjs` | GLB rating | renders exported GLBs to contact sheets and a blind `rating.csv` |
| `scripts/glb_assembly.mjs` | GLB improvement | backfills `assembly.jsonl` for a run on disk (docs/14 section 4) |
| `scripts/glb_repair.py` | GLB improvement | one-shot repair retry for failed GLB answers (docs/14 section 5) |
| `scripts/glb_best_of.py` | GLB improvement | picks the best of several sampled candidates per brief (docs/14 section 6) |
| `scripts/ccore_prep.py` | GLB improvement | builds the phase 2 dataset from ccore's parquet, eval-leak guarded (docs/14 section 7) |
| `scripts/glb_phase2_estimate.py` | GLB improvement | reads the phase 2 data and estimates steps, hours and cost (docs/14 section 8) |
| `scripts/imp_ops.sh` | GLB improvement | operator wrapper for the local imp jobs: preflight, start, wait, status |
| `scripts/build_dataset.py` | 4. SFT files | prompt/completion JSONL, `--no-reasoning` |
| `scripts/train_sft.py` | 5. training | TRL, LoRA or full; GPU box |
| `scripts/export_gguf.sh` | 6. export | merge, GGUF, quantise, Modelfile |
| `scripts/check.sh` | gate | syntax checks + tests; every Ralph story must pass it |
| `scripts/common.py` | shared | `.env` loading, OpenAI client, system prompt |
| `prompts/system.txt` | all | the scene rules; do not change (all data was generated against it) |

## Bench: GLB code track
| File | What it is |
|---|---|
| [bench/glb/briefs.jsonl](bench/glb/briefs.jsonl) | 48 asset briefs (12 domains x 4) for the phase 1 benchmark; eval only, never train on them |
| [bench/glb/models.json](bench/glb/models.json) | the six model rows of docs/13 section 4.3 with prompt, sampling and enabled flags |
| [prompts/system_glb.txt](prompts/system_glb.txt) | our pinned Three.js 0.160.0 system prompt for Glimmer and other non-ccore models |
| [prompts/ccore_glb_system.txt](prompts/ccore_glb_system.txt) | the owner pastes ccore's verbatim system prompt here before running the bench |

## Data (gitignored, owner's)
| Folder / file | Contents |
|---|---|
| `data/briefs.jsonl`, `data/briefs.eval.jsonl` | 51 train briefs, 3 held-out eval briefs |
| `data/raw/`, `data/scenes/`, `data/shots/`, `data/validation.jsonl` | Glimmer pilot (in progress) |
| `data/raw_spark/`, `data/scenes_spark/`, `data/shots_spark/`, `data/validation_spark.jsonl` | Spark Open, first 30 briefs (28 pass) |
| `data/raw_spark_truncated16k/` | the 11 Spark answers cut off at 16k tokens, kept for reference |
| `data/briefs_spark_retry.jsonl` | the 11 briefs rerun at 32k |
| `data/baseten_smoke/` | the first Spark lighthouse scene |
| `data/teacher.log` | Glimmer pilot log |

## Config
| File | What |
|---|---|
| `.env` | keys (copied from pixitween-director; gitignored) |
| `.env.example` | variable names, Spark model slug |
| `opencode.json` | Ralph fallback agent: Ollama models + Command Code |
| `.ralph-tui/config.toml` | Ralph agent `command-code-go`, `autoCommit = false` |
| `ralph/src/prd-*.json` | Ralph stories (edit these); `ralph/prd-*.json` are built from them |
