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
is sent as `0.0`, while leaving it out keeps the old request unchanged). `--seed N` is sent as `options.seed` on
that route and recorded in each saved raw row; without it the request body and every row are unchanged. Every saved
raw row records `system_file` (the path used) and `system_sha256` (the SHA-256 of the exact system text sent).

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
- `--seed N` is forwarded to `teacher_generate.py` (`options.seed`) and `--run-suffix S` appends `S` to every run
  directory (`<out-root>/<name><S>`, e.g. `--run-suffix=-s2` for a second sample). Both are omitted by default, so
  the commands for a plain run are byte-identical to before.
- `--allow-paid` is required for rows marked `paid`, and `--dry-run` prints every command without running it.
- The script refuses to run a model whose system file is missing or still contains the ccore placeholder, and a
  real run checks `ollama list` once and names the `ollama pull` command for any missing model.

`scripts/glb_report.py` turns that output into the docs/13 section 5.3 metrics: pass rate with a 95 % Wilson
interval, export rate, animated pass (pass **and** `stats.glb.animations > 0`), triangle median/max and the share of
passes at or under 5,000 triangles, failures per reason, cost, passes by domain, head-to-head counts and, when
ratings exist, the recognisable rate. Every brief in `--briefs` counts: one a model never validated is a failure
with the reason `missing`. Four columns are appended for docs/14: `Assembled (of valid)`, `Assembled (of all
briefs)` and `Median parts` (from `assembly.jsonl`, else `stats.glb.assembly`; `not computed` when a model has
neither) and `Good (rated 2), secondary`, the share of briefs rated exactly 2. `Assembled (of valid)` divides by
the measured rows and `Assembled (of all briefs)` by every brief, so a model cannot look better by failing more.
The docs/14 section 3 product rows stay separate from the frozen single-shot row.

```bash
.venv/bin/python scripts/glb_report.py --root eval/glb_bench --briefs bench/glb/briefs.jsonl
.venv/bin/python scripts/glb_report.py --root eval/glb_bench --briefs bench/glb/briefs.jsonl \
  --ratings eval/glb_bench/sheet/rating.csv [--key-map eval/glb_bench/sheet/key_map.json]
.venv/bin/python scripts/glb_report.py --root runs/glb_v3 --briefs bench/glb/briefs.jsonl \
  --extra-runs best-of-3=runs/imp/best3/glimmer-v3-best3
```

- `--root DIR` (required) holds one folder per model, each with a `validation.jsonl` and its `raw/` answers.
- `--briefs FILE` (required) is the scored brief list; absent rows count as `missing`.
- `--ratings FILE` is the blind `rating.csv` from `glb_sheet.mjs`; `--key-map` defaults to `key_map.json` beside it.
  Without `--ratings` the recognisable and good columns say `not rated`.
- `--extra-runs NAME=DIR` (repeatable) adds a derived run as an extra row; `NAME` is the label. A repair directory
  (a `repair/` folder under the model run, docs/14 section 5) is labelled `<model> after 1 repair` and its pass
  count is the original ok ids plus the repaired ids. A `repair-asm/` folder (section 5) is labelled `<model> after
  assembly repair`: the ids in its `summary.json` `ids_repaired` take the repaired ok and assembled values, every
  other brief keeps the original run's.
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

## Assembly metric in glb_check.mjs

`scripts/glb_check.mjs` measures how well an exported GLB's parts fit together (docs/14 section 4). It exports
`assembly(json, {kind = 'static', tolFrac = 0.02} = {})`, which walks the node tree, transforms each POSITION box
into world space and returns `{parts, components, largest_share, floaters, min_y, ground_gap, tol, assembled}` —
or `{parts: 0, assembled: false, error}` for malformed input, never throwing. `kind` is `static`, `animated` or
`set`. `parseGlb` adds this as `assembly` to every ok result, without changing any of its other fields.

`tests/js/glb_util.mjs` `makeGlb` gained optional `boxes` (`[{min, max}]` per mesh), `nodes`
(`{mesh, translation, rotation, scale, matrix, children}`) and `scene` (root node indices) so tests can place unit
boxes anywhere and build hierarchies; without those options its output is byte-for-byte unchanged.

The validator records the kind-aware result as `stats.glb.assembly` in GLB mode, taking the kind from the raw
row's brief (`raw.brief.kind`) or the optional `validate_scenes.mjs --briefs FILE` flag. `glb_check.mjs` also
exports `glbJson(buf)` (the glTF JSON of a GLB, or `null`). `scripts/glb_assembly.mjs --run RUN_DIR --briefs FILE
[--tol-frac 0.02]` backfills `RUN_DIR/assembly.jsonl` (`{id, kind, assembly}`, `null` for a non-ok row) for a run
already on disk, printing `assembled X of Y valid` and leaving `validation.jsonl` untouched.

## Repair retry (glb_repair.py)

`scripts/glb_repair.py` feeds each failing page back to the model once with its error
(docs/14 section 5), because many failures are one-line bugs:

```bash
.venv/bin/python scripts/glb_repair.py --run runs/glb_v3/glimmer-v3 --model-row glimmer-v3
```

- `--run DIR` (required) is a model run directory with a `validation.jsonl` and its `raw/` answers;
  it must be outside `data/`, `out/` and `eval/`, and a model row marked `paid` is refused unless
  `--allow-paid` is given.
- It selects the ids that failed with `js_error`, `load_fail`, `no_download`, `export_error`,
  `bad_glb`, `empty_glb` or `no_export_button`. It never selects `truncated`, `no_html` or
  `external_dep`: those are not one-line bugs. `--limit N` caps how many are processed.
- Each id gets one Ollama `/api/chat` call with messages `[system, user (the brief), assistant (the
  original answer), user (the fix message)]`; sampling comes from the `--model-row` entry in
  `--models` (default `bench/glb/models.json`) and `--ollama-url` defaults to the local server.
- The fix message lists the reasons and the first error (`stats.error`, or `none recorded`) and asks
  for the complete corrected HTML in one block.
- Output goes under `DIR/repair/`: one `<id>.json` per answer in `repair/raw/` (the teacher row shape
  plus `repair_of` and `fix_message`), then `repair/validation.jsonl` from `validate_scenes.mjs
  --mode glb --allow-addons` with the bench's directory layout. `--no-validate` generates without
  validating.
- It prints `repaired X of Y` and writes `repair/summary.json`
  (`{mode, selected, attempted, repaired, ids_repaired, model, system_file, system_sha256}`). An existing
  `repair/raw/<id>.json` is skipped, so a rerun makes no new requests for ids already written.

`--mode assembly` (imp-2) targets the other failure the validator measures: a valid page whose exported
asset has floating or disconnected parts (docs/14 section 2). It selects the ok rows whose `assembly.jsonl`
entry has `assembled: false` and at least 3 parts, and the fix message quotes the assembly numbers — the
separate groups of parts, the largest group's share as a percent, the floating parts and the ground gap in
metres, both rounded to 2 decimals — asking the model to move or resize parts so they touch, sit on the
ground (lowest y = 0) and stay in one `THREE.Group` named `"asset"`. Output goes under `DIR/repair-asm/`,
and `repair-asm/summary.json` adds `mode` and `assembled_after` (the repaired rows that are ok and assembled).
Error mode stays the default and is unchanged.

```bash
.venv/bin/python scripts/glb_repair.py --run runs/glb_v3/glimmer-v3 --model-row glimmer-v3 --mode assembly
```

## Best-of-N picker (glb_best_of.py)

`scripts/glb_best_of.py` samples each brief several times (via `glb_bench.py --seed`/`--run-suffix`) and keeps the
best candidate automatically (docs/14 section 6), using only automatic signals:

```bash
.venv/bin/python scripts/glb_best_of.py \
  --runs runs/glb_v3/glimmer-v3 runs/glb_v3/glimmer-v3-s2 runs/glb_v3/glimmer-v3-s3 \
  --briefs bench/glb/briefs.jsonl --out runs/imp/best3/glimmer-v3-best3
```

- `--runs DIR [DIR ...]` (required) are the run directories to choose from, in tie-break order. Each needs a
  `validation.jsonl`; a run without `assembly.jsonl` gets one from `glb_assembly.mjs` (`--no-compute` refuses
  instead of computing it).
- `--briefs FILE` (required) names every picked id; `--out DIR` (required) is the output run directory and must be
  outside `data/`, `out/` and `eval/` and different from every `--runs` input.
- Per brief it ranks the candidates by `ok`, then `assembled`, then parts within 8-60, then triangles <= 5000, then
  higher `largest_share`, then run order (the earlier run wins a tie). It never uses the eval ratings.
- The winner's `raw/<id>.json` (with `picked_from` added), `glb/<id>.glb`, `shots/<id>.png` and validation row go
  into `--out`, so the result is a normal run: `glb_sheet.mjs --root <out>/..` renders it and
  `glb_report.py ... --extra-runs best-of-3=<out>` reports it. `--out/assembly.jsonl` and
  `--out/picks.json` (`{id: {picked_from, rank_keys}}`, `null` for a brief with no candidate) are written too, and
  it prints `picked X of Y briefs`.

## Adaptive best-of-N cost (glb_best_of_cost.py)

`scripts/glb_best_of_cost.py` replays samples a set of runs already holds and reports what an adaptive
best-of-N rule would have spent, so best-of-3's 3x time can be sized against an early-exit rule
(docs/14 section 6):

```bash
.venv/bin/python scripts/glb_best_of_cost.py \
  --runs runs/glb_v3/glimmer-v3 runs/glb_v3/glimmer-v3-s2 runs/glb_v3/glimmer-v3-s3 \
  --briefs bench/glb/briefs.jsonl --out runs/imp/best3/glimmer-v3-cost.json
```

- For each brief it walks the runs in the given order and stops at the first candidate that is both `ok` and
  assembled (the kind-aware `assembled` boolean in `assembly.jsonl`), spending only the samples up to that point.
  A brief with no such candidate falls through to the whole list and is picked with `glb_best_of.py`'s ranking
  (imported, not copied).
- It prints a short table and, with `--out FILE.json`, writes the report: the adaptive rule's mean samples used
  per brief, mean and median seconds per brief, and the `ok`/`assembled` shares of the picks, next to the always-N
  baseline (every run, all samples spent). Seconds come from the same field `glb_report.py` reads for `Median
  seconds` (`raw/<id>.json` `usage.seconds`, `0.0` when absent).
- A run without `assembly.jsonl` prints `warning: <run> has no assembly.jsonl; its rows count as not assembled`
  and its rows never stop the walk. `--out` must be outside `data/`, `out/` and `eval/`.

## Phase 2 data (ccore_prep.py)

`scripts/ccore_prep.py` turns ccore's downloaded parquet shards into the conversational prompt/completion set that
`scripts/mesh_lora_hf.py` trains on (docs/14 section 7), dropping eval subjects so phase 2 is never trained on the
48 eval briefs:

```bash
.venv/bin/python scripts/ccore_prep.py --parquet-dir runs/ccore_data/raw --out runs/imp/phase2_data \
  --max-chars 22000 --system ccore --leak-file bench/glb/eval_subjects.json
.venv/bin/python scripts/mesh_lora_hf.py --data runs/imp/phase2_data --dry-run
```

- `--parquet-dir DIR` reads its `train-*.parquet` into `DIR/train.jsonl` and `validation-*.parquet` into `DIR/val.jsonl`
  (ccore's own split is kept). `--out DIR` must be outside `data/`, `out/` and `eval/`.
- Each row is `{id, domain, title, prompt: [system, user], completion: [assistant content]}`; `reasoning_content` is
  dropped. The `--system` text (`ccore` means `prompts/ccore_glb_system.txt`, or give a file) is written verbatim into
  every prompt.
- Four drop rules are applied in order and counted per split in `--out/stats.json`: no ```html block or no "Export GLB"
  text (`no_html`), an answer longer than `--max-chars` (`too_long`), a title matching an eval subject (`eval_subject`,
  whole-word and case-insensitive, title only — `--leak-file` defaults to `bench/glb/eval_subjects.json`), and a repeat
  of an already-kept answer (`duplicate`).
- `--extra-run DIR` (repeatable) adds the rows of a Glimmer run that are both ok and assembled, using `--extra-system
  FILE` (required with it); it refuses — and writes nothing — when any id is one of the eval briefs. `--seed N`
  (default 7) shuffles the train split.
- `stats.json` also holds the kept counts by domain, the completion-length median and max, the system and leak-file
  sha256, and the sha256 of each input parquet.

## Phase 2 cost estimate (glb_phase2_estimate.py)

`scripts/glb_phase2_estimate.py` projects the phase 2 LoRA steps, hours and cost from the built dataset
(docs/14 section 8), from a measured input rather than a guess:

```bash
.venv/bin/python scripts/glb_phase2_estimate.py --data runs/imp/phase2_data   # no sec-per-step: prints 'not measured'
.venv/bin/python scripts/glb_phase2_estimate.py --data runs/imp/phase2_data --sec-per-step S --price-per-hour P
```

- `--data DIR` reads `DIR/train.jsonl` and `DIR/val.jsonl` (writers of the ccore_prep.py / mesh_lora_hf.py format).
- It prints the rows, total completion characters, an estimated token count labelled `estimate, chars/token = X`
  (`--chars-per-token`, default 3.3), steps per epoch (`--batch` x `--grad-accum`, default 1 x 8), total steps
  (`--epochs`, default 2), then hours and cost.
- Without `--sec-per-step` it prints `sec-per-step not measured: run the 20-step smoke first` and no cost; `S` comes
  from timing the 20-step smoke run (`mesh_lora_hf.py --max-steps 20`). `--sec-per-step` and `--price-per-hour` are
  given together. The script reads only and writes nothing.

## Operator wrapper (imp_ops.sh)

`scripts/imp_ops.sh` is the only way the imp-ops PRD starts the long local jobs (docs/14), so an operator agent never
runs a raw bench or repair command. Jobs run detached and are resumable, and one job runs at a time:

```bash
bash scripts/imp_ops.sh preflight        # Ollama up/down, running job, v3 hash check, imp-1 status
bash scripts/imp_ops.sh start v3s2       # or v3s3, repair-v3, repair-asm-v3, repair-asm-v3s3
bash scripts/imp_ops.sh wait v3s2        # wait up to 540 s; exit 0 finished, 2 still running, 1 failed
bash scripts/imp_ops.sh status
```

- `v3s2` / `v3s3` run `.venv/bin/python scripts/glb_bench.py --out-root runs/glb_v3 --only glimmer-v3 --seed 2|3
  --run-suffix=-s2|-s3`; `repair-v3` runs `.venv/bin/python scripts/glb_repair.py --run runs/glb_v3/glimmer-v3
  --model-row glimmer-v3`. `repair-asm-v3` adds `--mode assembly` (docs/14 section 5) to the same run, and
  `repair-asm-v3s3` is the same on `runs/glb_v3/glimmer-v3-s3` (same `--model-row glimmer-v3`).
- `start` refuses unless `runs/glb_v3/PROMPT_FROZEN.json` exists and its `sha256` equals the SHA-256 of
  `prompts/system_glb_v3.txt`, and it refuses a second job while one is alive. Jobs have pid/exit/log/started files
  under `runs/imp/jobs/`.
- `wait JOB [SECONDS]` caps at 540 s and reports the job's exit code from its `.exit` file.
- `IMP_OPS_DRY=1 start JOB` prints the command instead of running it.
- Overrides for tests: `IMP_OPS_RUNS` (run root, default `runs/glb_v3`), `IMP_OPS_JOBS` (job state, default
  `runs/imp/jobs`), `IMP_OPS_BENCH` (bench command), `IMP_OPS_PROMPT` (default `prompts/system_glb_v3.txt`),
  `IMP_OPS_POLL` (default 10 s) and `IMP_OPS_SKIP_CHECKS` (skip the Ollama check in preflight).

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
