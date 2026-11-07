# muse-threejs

Teach a small open model (Qwen3.5-4B) to write interactive Three.js scenes by using
**Muse Spark Open (on Baseten)** as the teacher, then filter every teacher answer by
actually running it in a headless browser. Same idea as ccore's
[Qwen3.5-4B-3D-Coder](https://huggingface.co/ccore/Qwen3.5-4B-3D-Coder), with Muse as the
teacher and a real render check as the quality gate.

This is plain supervised fine-tuning on teacher outputs ("distillation" in the loose sense).
It does not use the teacher's logits; an API never gives you those.

## Pipeline

```
 briefs  ->  teacher  ->  validate  ->  dataset  ->  train  ->  export  ->  eval
 (Spark)    (Spark Open)  (Playwright)  (JSONL)     (TRL)      (GGUF)     (same validator)
```

| Stage | Script | Output |
|---|---|---|
| 1. Scene briefs | `scripts/gen_briefs.py` | `data/briefs.jsonl` |
| 2. Teacher answers | `scripts/teacher_generate.py` (Baseten check: `scripts/baseten_smoke.py`, see [docs/baseten-spark-open.md](docs/baseten-spark-open.md)) | `data/raw/<id>.json` |
| 3. Render check | `scripts/validate_scenes.mjs` | `data/scenes/<id>.html`, `data/validation.jsonl`, `data/shots/<id>.png` |
| 4. SFT dataset | `scripts/build_dataset.py` | `data/sft/train.jsonl`, `data/sft/val.jsonl` |
| 5. Train | `scripts/train_sft.py` | `out/lora/` or `out/full/` |
| 6. Export | `scripts/export_gguf.sh` | `out/gguf/*.gguf`, `Modelfile` |
| 7. Eval | `scripts/teacher_generate.py` (pointed at the student) + `validate_scenes.mjs` | pass rate |

**Tracking:** [NEXT-STEPS.md](NEXT-STEPS.md) (status, decisions, to-do, results log) and [INDEX.md](INDEX.md) (map of every file).

## Read first (in order)

**Taking over?** Start with [docs/HANDOVER.md](docs/HANDOVER.md): a paid GPU pod may be running.

[docs/00-architecture.md](docs/00-architecture.md) is the one-page overview with the diagram ([docs/architecture.svg](docs/architecture.svg)); the mesh track is in [docs/08-mesh-track.md](docs/08-mesh-track.md).

0. [docs/07-local-glimmer.md](docs/07-local-glimmer.md): **start here.** Run the pilot free on this Mac with Muse Glimmer (Apache 2.0), measured at about 40 tok/s.
1. [docs/01-licensing.md](docs/01-licensing.md): can you train on Spark Open outputs and publish the result? Do this before spending money.
2. [docs/02-environment.md](docs/02-environment.md): accounts, keys, machine setup.
3. [docs/03-pipeline-walkthrough.md](docs/03-pipeline-walkthrough.md): each stage in detail.
4. [docs/04-training.md](docs/04-training.md): GPU, hyperparameters, what to watch.
5. [docs/05-export-serve-eval.md](docs/05-export-serve-eval.md): GGUF, Ollama, measuring the result.
6. [docs/06-budget-and-risks.md](docs/06-budget-and-risks.md): cost estimate, what can go wrong, open questions.

## Quickstart (smoke test, about 20 teacher calls)

```bash
cd /Users/irfankhan/Documents/code/trolio/muse-threejs
cp .env.example .env            # fill in BASETEN_API_KEY and TEACHER_MODEL
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm install && npx playwright install chromium

python scripts/gen_briefs.py --count 20 --out data/briefs.jsonl
python scripts/teacher_generate.py --briefs data/briefs.jsonl --out data/raw --concurrency 4
node scripts/validate_scenes.mjs --raw data/raw --scenes data/scenes --shots data/shots --report data/validation.jsonl
python scripts/build_dataset.py --briefs data/briefs.jsonl --raw data/raw --report data/validation.jsonl --out data/sft
```

Look at `data/shots/*.png` and the pass rate in `data/validation.jsonl` before scaling to thousands.

`teacher_generate.py` reads `prompts/system.txt` unless `--system FILE` is given. The Ollama-native backend also
accepts `--top-k`, `--min-p` and `--repeat-penalty`; each is sent in `options` only when you pass it (so `--min-p 0`
is sent as `0.0`, while leaving it out keeps the old request unchanged). Every saved raw row records `system_file`
(the path used) and `system_sha256` (the SHA-256 of the exact system text sent).

## GLB benchmark (code track)

`scripts/glb_bench.py` reads `bench/glb/models.json` and, for each enabled model, runs `teacher_generate.py` and
then `validate_scenes.mjs --mode glb` over the briefs, writing everything under `<out-root>/<model>/`. Output is
resumable: saved raw answers are skipped, so rerunning the same command continues where it stopped.

```bash
.venv/bin/python scripts/glb_bench.py --out-root eval/glb_bench --dry-run   # print the commands, write nothing
.venv/bin/python scripts/glb_bench.py --out-root eval/glb_bench             # generate + validate
.venv/bin/python scripts/glb_bench.py --out-root eval/glb_bench --only glimmer --limit 2
```

- `--out-root DIR` (required) must be outside `data/` and `out/`.
- `--models`, `--briefs`, `--num-ctx` (default 49152) and `--max-tokens` (default 40000) override the defaults.
- `--only NAME` (repeatable) selects rows by name, including disabled ones; `--limit N` stops after N briefs.
- `--allow-paid` is required for rows marked `paid`, and `--dry-run` prints every command without running it.
- The script refuses to run a model whose system file is missing or still contains the ccore placeholder, and a
  real run checks `ollama list` once and names the `ollama pull` command for any missing model.

`scripts/glb_report.py` turns that output into the docs/13 section 5.3 metrics: pass rate with a 95 % Wilson
interval, export rate, animated pass (pass **and** `stats.glb.animations > 0`), triangle median/max and the share of
passes at or under 5,000 triangles, failures per reason, cost, passes by domain, head-to-head counts and, when
ratings exist, the recognisable rate. Every brief in `--briefs` counts: one a model never validated is a failure
with the reason `missing`.

```bash
.venv/bin/python scripts/glb_report.py --root eval/glb_bench --briefs bench/glb/briefs.jsonl
.venv/bin/python scripts/glb_report.py --root eval/glb_bench --briefs bench/glb/briefs.jsonl \
  --ratings eval/glb_bench/sheet/rating.csv [--key-map eval/glb_bench/sheet/key_map.json]
```

- `--root DIR` (required) holds one folder per model, each with a `validation.jsonl` and its `raw/` answers.
- `--briefs FILE` (required) is the scored brief list; absent rows count as `missing`.
- `--ratings FILE` is the blind `rating.csv` from `glb_sheet.mjs`; `--key-map` defaults to `key_map.json` beside it.
  Without `--ratings` the recognisable column says `not rated`.
- It writes `<root>/report.json` and `<root>/report.md`; the markdown has one row per model plus failures, domain and
  head-to-head tables.

`scripts/glb_sheet.mjs` renders every exported GLB to a contact sheet so the owner can rate the assets blind: each
model is shuffled into shared keys, so the sheet never shows which model produced an asset.

```bash
node scripts/glb_sheet.mjs --root eval/glb_bench --out eval/glb_bench/sheet
node scripts/glb_sheet.mjs --root eval/glb_bench --out eval/glb_bench/sheet --seed 3 --size 512
```

- `--root DIR` (required) is the benchmark output; every `<root>/<model>/glb/<id>.glb` is rendered locally with the
  pinned Three.js 0.160.0 `GLTFLoader`, a 3/4 view and a top view side by side on light grey.
- `--out DIR` (required) receives `<out>/<model>/<id>.png` and a `<out>/<model>/sheet.png` grid. `--size N`
  (default 256) is the per-view pixel size and `--seed N` (default 1) seeds the shuffle.
- `--briefs FILE` (default `bench/glb/briefs.jsonl`) is the brief list. `rating.csv` gets one row per model x brief
  (`key, brief, image, rating`, rating left empty) in seeded-shuffled order; a brief with no GLB keeps an empty
  `image` so the miss is visible. Images are copied to key-named files under `<out>/images/`.
- `key_map.json` maps every key to `{model, id}`; join it after rating to unblind. A GLB that fails to load is listed
  in `<out>/skipped.json` and never stops the run, and a rerun skips PNGs that already exist.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q tests/py   # unit tests (offline, temp dirs)
bash scripts/check.sh                    # syntax checks + pytest + node tests
```

Recent Node (22 and later) does not expand a bare directory passed to `node --test`, so `node --test tests/js`
would try to load the directory as a file. `tests/js/index.js` re-exports `render_views.test.mjs` so the exact
command works; passing the test file directly, or running `node --test` with no path (default discovery), is unaffected.

`scripts/build_dataset.py` keeps its logic in `build(briefs, raw_dir, report, out_dir, no_reasoning=False, val_fraction=0.05, seed=1)`,
which returns the counts and split ids; `main()` only parses args and calls it. `tests/py/test_build_dataset.py` exercises
the join, the reasoning wrap, the stratified/deterministic split and the unchanged `main()` output.

## Proof data (memorisation set)

`scripts/proof_data.py` picks rows from an SFT file and writes the MLX chat files for the memorisation proof:

```bash
python scripts/proof_data.py --sft data/mesh/sft/train.jsonl --pick median --n 1 --repeat 1 --out-dir /tmp/proof-one
```

- `--pick median` takes the row at the median completion length; `--pick smallest` takes the shortest; `--pick spread --n N`
  takes N rows, at most one per `source_id`, evenly spread by completion length.
- `--out-dir` is required. It writes `train.jsonl` (`--repeat` copies, default 1), `valid.jsonl` (once) and `targets.json`
  (`id`, `caption`, `mesh`). Both chat files have the same rows because this is a memorisation test.
- The script reads only the `--sft` file and refuses an `--out-dir` inside `data/`, `eval/` or `out/`.

## Proof score (did the model reproduce the mesh?)

`scripts/proof_score.py` generates one answer per target and reports, independently, whether the text matched
the target exactly, whether it is a valid mesh, and whether the model stopped before the token cap:

```bash
python scripts/proof_score.py --targets /tmp/proof-one/targets.json \
  --sft-system-from /tmp/proof-one/train.jsonl --model Qwen/Qwen2.5-0.5B-Instruct \
  --adapter /tmp/proof-one/adapter --max-tokens 8000 --temperature 0.0 \
  --out /tmp/proof-one/report.json
```

- `--targets` is the `targets.json` written by `proof_data.py`; `--sft-system-from` supplies the system prompt from
  the first row of its `train.jsonl`.
- `--model` and `--adapter` are the MLX checkpoint and optional LoRA adapter; `--max-tokens` and `--temperature`
  control generation (default 8000 and 0.0).
- The report has `n`, `exact`, `valid`, `stopped`, `lines_identical_share` and one `items` entry per target. `stopped`
  is true only when the generated token count is below `--max-tokens`, so a runaway that reaches the cap is false.
- `mlx_lm` is imported only when generation starts, so importing the module for tests works without MLX. The report
  is written only outside `data/`, `eval/` and `out/`.

## Proof ladder (keep paying or stop?)

`scripts/proof_ladder.py` judges each rung of the confidence ladder and prints the spending recommendation:

```bash
python scripts/proof_ladder.py --report one=/tmp/proof-one/report.json \
  --report seen=/tmp/proof-seen/report.json
```

- `--report RUNG=PATH` is repeatable. Rungs are `one`, `seen`, `unseen_same_category` and `unseen_new_category`;
  `one` needs an exact and stopped share of 1.0, `seen` needs valid and stopped shares of at least 0.8, and the
  two unseen rungs need valid shares of at least 0.6 and 0.4 (placeholders to revise).
- The command prints all four rungs as `PASS`, `FAIL` or `NOT RUN` with the reason, then one recommendation. It
  exits 0 for all three outcomes, and a missing report is never treated as a pass.
- `judge(rung, report)` returns `(passed, reason)`; `decide(reports)` takes the reports found so far and returns
  the recommendation string. See [docs/12-proof-ladder.md](docs/12-proof-ladder.md) for the rung-one result.

## Proof run (dataset to verdict in one command)

`scripts/proof_run.sh` runs the whole proof for one rung: dataset, MLX LoRA training, generation and scoring,
then the ladder verdict:

```bash
bash scripts/proof_run.sh one                # about 10 minutes on this Mac, free
bash scripts/proof_run.sh seen               # longer; time not measured
```

- `one` picks the median row with `proof_data.py --pick median --n 1`; `seen` picks 15 spread rows with
  `--pick spread --n 15`. Iterations default to 200 for `one` and 600 for `seen`.
- `--model` (default `Qwen/Qwen2.5-0.5B-Instruct`), `--iters`, `--lr` (default `3e-5`), `--max-seq` (default
  9728) and `--workdir` (default a new folder under `/tmp`) are optional.
- A learning rate above `1e-4` is refused with the 3 Nov 2026 divergence note (2e-4 went from loss 0.78 to 11)
  unless `--force-lr` is given.
- `--dry-run` echoes the five commands in order (prepare folder, dataset, train, score, verdict) and runs none
  of them. Before training it prints a time estimate: roughly 10 minutes for `one`, `not measured` for `seen`.

## Render mesh views (four angles)

`scripts/render_views.mjs` renders each text mesh in a JSONL file to a few small PNGs so an image-text model
can score how well a mesh matches its caption:

```bash
node scripts/render_views.mjs --in FILE.jsonl --out-dir DIR [--views 4] [--size 224]
```

- `--in FILE.jsonl` rows are `{name, text}`; `--out-dir DIR` receives `DIR/<name>/view0.png .. view{N-1}.png`.
- `--views N` (default 4) are evenly spaced azimuths starting at 45 degrees, at about 25 degrees elevation;
  `--size N` (default 224) is the square pixel size, asserted from the PNG IHDR in the test.
- A row whose text does not parse (no `v`/`f` lines, or a face index out of range) is listed in
  `DIR/skipped.json` and never stops the other rows. A row whose views all exist is skipped, so reruns resume.
  One summary line is printed: `rendered N, skipped N, already done N`.

## Caption-image similarity (CLIP)

`scripts/clip_score.py` turns those rendered views into one automatic number per mesh: how well the images match
the caption. It has no CLI; the rerank and eval tools import it.

- Pure helpers: `cosine(a, b)`; `mesh_score(view_vecs, text_vec)` is the mean cosine over the views times 100;
  `retrieval_ranks(score_matrix)` returns the 1-based rank of each mesh's true caption among all captions
  (`score_matrix[i][j]` = score of mesh `i` against caption `j`, true caption of mesh `i` is caption `i`; a tie
  ranks the true caption below the tied one); `recall_at(ranks, k)` is the share of ranks at or above `k`.
- `score_folder(views_dir, items, embedder, views=4)` with `items = [{name, caption}]` returns `{name: score}`
  for every name whose `views_dir/<name>/view0.png .. view{N-1}.png` all exist and skips the rest. It works with
  any object that has `images(paths)` and `text(captions)`, so tests (and callers) pass a fake embedder.
- `ClipEmbedder(model_id="openai/clip-vit-base-patch32")` implements `images()` and `text()` with CLIP,
  L2-normalised. It imports `torch`, `Pillow` and `transformers` lazily inside its methods and loads the
  checkpoint with `local_files_only=True`, so importing the module never imports them. If `torch` is missing it
  raises a `RuntimeError` naming the manual install: `.venv/bin/pip install torch pillow` (then download the
  model to the Hugging Face cache once).

## Rerank samples (first vs medoid vs CLIP picks)

`scripts/rerank_samples.py` re-judges an existing `gen_*.samples.jsonl` for free: does the medoid rule throw
away recognisable meshes that Glimmer already produced? Two subcommands, both refusing an `--out-dir` inside
`data/`, `out/` or `eval/` (exit 2):

```bash
python scripts/rerank_samples.py prepare --samples artifacts/glimmer-v4/gen_v4.samples.jsonl --out-dir /tmp/rerank
node scripts/render_views.mjs --in /tmp/rerank/candidates.jsonl --out-dir /tmp/rerank/views
python scripts/rerank_samples.py score --out-dir /tmp/rerank --views-dir /tmp/rerank/views
```

- `prepare` validates every answer with `mesh_validate.validate` and writes the valid ones to
  `candidates.jsonl` (`{name: '<id>_<k>', id, k, caption, text}`), `prompts.json` (`[{id, caption, n_valid}]`)
  and `samples.jsonl` (the input rows plus the `p000`, `p001` ... ids given to rows without one).
- `score` scores every candidate's rendered views against its caption with `clip_score.score_folder` and picks,
  per prompt: **first** (lowest `k`), **medoid** (`mesh_generate.pick_best` on the original answers) and **clip**
  (highest CLIP score, ties to the lowest `k`). A prompt with no valid candidate is a miss for every rule.
- It writes `rerank_report.json` and `rerank_report.md` with `valid`, `mean_clip`, `r_at_1` and `r_at_5` for each
  of `first`, `medoid` and `clip`, plus `sheet_medoid.jsonl` and `sheet_clip.jsonl` (`{name, text}` rows for
  `scripts/preview_mesh.mjs`). Retrieval ranks the picked meshes against every prompt caption, and a miss keeps
  the denominator at all prompts (worst rank).
- There is no separate `oracle` rule: with a single scorer its pick is identical to the CLIP pick, so `clip` is
  reported as the ceiling.

## Building it with Ralph

The remaining tooling is planned as 21 Ralph stories in four PRDs run one after another: see [ralph/README.md](ralph/README.md) (`ralph/run-all.sh`).

## Status

The pipeline has run on a 51-brief local Glimmer pilot (see [docs/07-local-glimmer.md](docs/07-local-glimmer.md)); results are in `data/` once it finishes. Training, export and evaluation have not been run. Items marked **VERIFY** in the docs are facts I could not confirm from public sources (Baseten model slug, whether the endpoint returns reasoning text, the exact license wording).
