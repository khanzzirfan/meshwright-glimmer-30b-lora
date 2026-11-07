# 13. GLB code track: benchmark first, then a Muse student

Written 7 Nov 2026. Status: **spec, nothing run.** Anything marked *not measured* or *unverified* has not been checked.
Tooling for phase 1 is the Ralph PRD `ralph/src/glb-1.prd.json`. Read [00-architecture.md](00-architecture.md) and
[12-proof-ladder.md](12-proof-ladder.md) first.

## 1. Why this track, why now

- The mesh-text track plateaued: v3 and v4 give 76-80 % valid meshes but only about 15-20 % of prompts are
  recognisable, and 2.7x more data changed nothing ([12-proof-ladder.md](12-proof-ladder.md), final result).
- On 5 Nov 2026 ccore released **Qwen3.5-4B-GLB-3D-Coder** (Apache 2.0; GGUF Q4_K_M, Q8_0, safetensors). It writes
  one Three.js HTML page per request with an "Export GLB" button, aimed at Godot. Its dataset
  `ccore/ThreeJS-3D-GLB-Assets` is MIT, about 3,918 examples (3.5k train, 417 validation), schema `id, title, domain,
  messages` with `reasoning_content`. Responses average about 20K tokens, training sequences up to 72K. **The card
  publishes no scores**, and does not say which model generated the data. All of this is self-reported.
- Writing code lets a model use primitives it already knows (boxes, cylinders, lathes) instead of raw coordinates.
  That is the likely reason code output looks recognisable where our mesh text does not. **Not measured** for us yet.

## 2. The question phase 1 answers

> On the same 48 asset briefs, how does untuned **Muse Glimmer** compare with **ccore's 4B**, scored by the same
> render + GLB checks and one blind human rating?

Phase 1 is free (Mac, Ollama) and decides whether phase 2 (training a Glimmer LoRA) is worth money. It does not
train anything.

## 3. What we keep from the project's pitch

| Promise in 00-architecture | Kept? |
|---|---|
| The student is a Muse model (Glimmer 30B, Apache 2.0) | yes |
| Every output is measured by a validator and a render | yes, extended to the exported GLB |
| Training data is real assets, not another model's output | **no** for this track: data is Glimmer's own validated output (self-distillation). Say so plainly in any write-up. ccore's dataset is used only for evaluation unless the owner decides otherwise (section 9) |

## 4. Phase 1 inputs

### 4.1 Briefs: `bench/glb/briefs.jsonl`
48 hand-written briefs, 12 domains x 4 (props_and_tools, furniture, food, vehicles, nature, buildings, characters,
creatures, weapons_and_armour, sci_fi, fantasy_medieval, modular_kits). Fields: `id` (g001-g048), `title`, `brief`,
`domain`, `level` (1-5), `style`, `kind` (`static` 29, `animated` 11, `set` 8). Eval only: never train on them.
The 3 old briefs in `data/briefs.eval.jsonl` are scenes, not assets, and are not used here.

### 4.2 Prompts
| File | Used by | Note |
|---|---|---|
| `prompts/system_glb.txt` | Glimmer and any non-ccore model | ours: pinned Three.js 0.160.0 via jsDelivr import map, GLTFExporter only, one `asset` group, real scale, `Export GLB` button, AnimationClip exported when motion is asked |
| `prompts/ccore_glb_system.txt` | ccore's model | **owner pastes it verbatim** from the card's "System prompt" section (https://huggingface.co/ccore/Qwen3.5-4B-GLB-3D-Coder#system-prompt). Each model gets the prompt it was trained with, so the comparison is fair. The bench refuses to run ccore while this file is missing or still holds the placeholder line |
| `prompts/system.txt` | scene track | unchanged |

### 4.3 Models: `bench/glb/models.json`
| name | Ollama model | prompt | sampling | think | enabled |
|---|---|---|---|---|---|
| `ccore-q8` | `hf.co/ccore/Qwen3.5-4B-GLB-3D-Coder:Q8_0` | ccore | temp 0.8, top_k 40, top_p 0.95, min_p 0 (card) | on (card says keep it on) | yes |
| `glimmer` | `muse-glimmer:30b-mlx` | ours | temp 0.7, top_p 0.95 | off (as in the 51-scene pilot) | yes |
| `glimmer-think` | `muse-glimmer:30b-mlx` | ours | temp 0.7, top_p 0.95 | on | no (run if `glimmer` is close) |
| `qwen35-4b-base` | `qwen3.5:4b` (owner checks the tag) | ours | temp 0.8, top_k 40, top_p 0.95 | on | no (shows what ccore's fine-tune added) |
| `ccore-ourprompt` | as ccore-q8 | ours | as ccore-q8 | on | no (does ccore follow our stricter rules?) |
| `spark-open` | Baseten | ours | temp 0.7 | provider default | no: **paid**, owner approval first |

Context: `num_ctx 49152`, `num_predict 40000` for every model. The card says an 8K cap cuts answers off and that
averages are about 20K tokens. A truncated answer counts as a failure (`truncated`), which is the truth.

## 5. Scoring

### 5.1 Validator GLB mode (`node scripts/validate_scenes.mjs --mode glb ...`)
Flags: `--mode scene|glb` (default `scene`) and `--glb-dir DIR` (default `data/glb`; used only in GLB mode).
The default mode stays byte-for-byte the same in behaviour. GLB mode changes four things:

1. **Imports.** Allowed: Three.js core and `examples/jsm/exporters/GLTFExporter.js`, from cdnjs, jsDelivr or unpkg,
   directly or through an import map, at any version. Every such URL is served from the local `node_modules/three`
   (0.160.0); `GLTFExporter.js`'s own relative import of `examples/jsm/utils/TextureUtils.js` is served the same way,
   but importing either addon directly from an answer is still `bad_import`. If the answer asked for another version,
   it is still served 0.160.0 and `stats.three_requested` records what was asked (with a `version_rewritten` flag, not
   a failure). Any other addon or host is `bad_import` / `external_dep`.
2. **Motion is not required.** `static` and `no_loop` are not reasons in GLB mode (assets are static by default).
   For `kind: animated` briefs, motion shows up as `animations > 0` in the GLB instead (5.3).
3. **Export.** After the page loads and the screenshot is taken, find the first visible button, `a` or
   `[role=button]` element whose text matches `/export|download|glb/i`, click it, and wait up to 20 s for a browser
   download. Save it as `<glb-dir>/<id>.glb` and record `stats.export_ms`. Reasons: `no_export_button`,
   `no_download`, `export_error` (page error after the click).
4. **GLB check** with `scripts/glb_check.mjs` (5.2). Reasons: `bad_glb`, `empty_glb`.

`ok` is true when there are no reasons. The report row gains `stats.glb` (5.2) and `stats.export_ms`. Set
`VALIDATE_REQUEST_LOG=FILE` to have the validator write the URLs of every request that was not served locally (the
offline test asserts that list is empty in both modes).

### 5.2 `scripts/glb_check.mjs` (pure Node, no new dependency)
`parseGlb(buffer)` returns `{ok, reason, bytes, version, meshes, primitives, triangles, vertices, materials, nodes,
animations, bbox:{min,max,size}}`.
- Header: magic `glTF`, version 2, declared length equals the buffer length; first chunk JSON, optional BIN chunk.
- Triangles per primitive: mode 4 (or absent) counts `indices.count / 3`, else `POSITION.count / 3`; modes 5 and 6
  count `count - 2`; points and lines count 0.
- `bbox` is the union of the POSITION accessors' `min`/`max` **with node transforms ignored** (approximate; say so).
- `empty_glb`: zero meshes or zero triangles. `bad_glb`: anything that fails to parse.

CLI: `node scripts/glb_check.mjs FILE.glb` prints the result as one JSON line and exits 0 when `ok` is true,
1 otherwise. Importing the module has no side effects.

### 5.3 Metrics per model (`scripts/glb_report.py`)
| Metric | Definition |
|---|---|
| **pass rate** | share of the 48 briefs with `ok: true` (renders, no JS error, not blank, exports a non-empty GLB). Reported with a 95 % Wilson interval: at n = 48 a gap under about 15 points is noise |
| export rate | share with a parsed GLB, whatever else failed |
| animated pass | among `kind: animated`, share that pass **and** have `animations > 0` |
| low-poly | median and max triangles of passing GLBs; share of passes at or under 5,000 triangles |
| failures | count per reason |
| cost | median completion tokens, median seconds, total wall time |
| by domain | pass count per domain |
| head to head | for each pair of models: briefs both pass, only A, only B |

### 5.4 Human rating (the check the mesh track taught us we need)
`node scripts/glb_sheet.mjs` renders every exported GLB from a fixed 3/4 view (and one top view) into a contact
sheet per model, and writes `rating.csv` with **shuffled, model-blind** rows: `key, brief, rating`. The owner rates
each 0-2: 0 = wrong or unrecognisable, 1 = recognisable but crude, 2 = good game asset. A small `--unblind` step joins
the ratings back to models. **Recognisable rate** = share of the 48 briefs rated 1 or 2 (a failed export counts as 0).

## 6. Phase 1 run (owner, after the PRD passes)

```bash
ollama pull hf.co/ccore/Qwen3.5-4B-GLB-3D-Coder:Q8_0      # about 4-5 GB (size not on the card)
# paste the card's system prompt into prompts/ccore_glb_system.txt
.venv/bin/python scripts/glb_bench.py --out-root eval/glb_bench --dry-run   # read the commands
.venv/bin/python scripts/glb_bench.py --out-root eval/glb_bench             # generate + validate, resumable
.venv/bin/python scripts/glb_report.py --root eval/glb_bench --briefs bench/glb/briefs.jsonl
node scripts/glb_sheet.mjs --root eval/glb_bench --out eval/glb_bench/sheet     # then rate rating.csv
.venv/bin/python scripts/glb_report.py --root eval/glb_bench --briefs bench/glb/briefs.jsonl --ratings eval/glb_bench/sheet/rating.csv
```

Time, estimated not measured: Glimmer about 2-6K tokens per answer at about 40 tok/s, so 1-2 h for 48. ccore about
20K tokens per answer; a 4B on this Mac is probably 60-100 tok/s, so about 3-5 h. Run overnight, one model at a time
(both want the GPU). Do not run Ralph on Ollama at the same time.

## 7. Decision after phase 1

Let P = pass rate and R = recognisable rate, Glimmer (best of `glimmer`, `glimmer-think`) against `ccore-q8`.

| Outcome | Rule | Next |
|---|---|---|
| A. Glimmer already competitive | R_glimmer >= R_ccore - 10 points | Phase 2 light: small LoRA only for format reliability (button, asset group, export), then publish |
| B. Gap, but Glimmer can produce good ones | R_glimmer >= 25 % | **Phase 2**: self-distillation corpus and LoRA (section 8) |
| C. Glimmer rarely produces usable assets | R_glimmer < 25 % and P_glimmer < 30 % | Stop the code track. Ship mesh v3 or v4 as a labelled research preview. Revisit only with a stronger Muse base |

The thresholds are judgement calls set before the run so the result cannot move them. Write the numbers and the
outcome into section 10, whatever they are.

## 8. Phase 2 spec (only after outcome A or B; separate PRD `glb-2`, not written yet)

1. **Briefs.** 1,500 asset briefs from `gen_briefs.py` run against local Glimmer (`--base-url
   http://localhost:11434/v1`), with the 12 domains above, de-duplicated against each other and against
   `bench/glb/briefs.jsonl` (word-overlap 0.8 rule already in `gen_briefs.py`). Needs a `--kind asset` brief prompt.
2. **Generate.** Glimmer with `prompts/system_glb.txt`, 4 samples per brief (temperature 0.8), `--system` flag from
   glb-1. About 1,500 x 4 x 4K tokens = 24M tokens, about 7 days at 40 tok/s on the Mac. **Too slow**: either 2
   samples per brief (about 3.5 days), or a vLLM pod (A100, about $1.2/h; throughput not measured, estimate 1-2 days
   less). Owner chooses; ask before renting.
3. **Filter.** Validator GLB mode; keep `ok`, at most 5,000 triangles, and for animated briefs `animations > 0`.
   Keep the best sample per brief by a simple score (fewer triangles over a floor, no warnings). Optional: CLIP score
   of the render against the brief (`scripts/clip_score.py` exists) to drop off-topic passes. Target 1,000+ kept.
4. **SFT data.** `build_dataset.py` gains `--system prompts/system_glb.txt`, answer only, no reasoning (Glimmer's
   template has no "off", so train and generate both use the default as in the mesh runs). Run `token_stats` first.
5. **Train.** `scripts/mesh_lora_hf.py` path (BF16 LoRA, lr 1e-4, 2 epochs, stop at the epoch where held-out loss
   turns up). Rows of 4-8K tokens; BF16 LoRA at 9,728 tokens fit an H100 at 70.6 GB, so an A100 80 GB should fit up
   to about 8K. Estimate: 1,000 rows x 5K tokens x 2 epochs = 10M tokens; v3 moved about 1.8M tokens/h, so **about
   5-6 h, $7-8 on an A100** (estimate, not measured). Balance on 4 Nov was $13.84: top up before starting.
6. **Re-run phase 1** with the adapter as a new model row. Success = outcome A against ccore.
7. **Export.** Merge, GGUF (llama.cpp with Glimmer support, untested), Ollama Modelfile with `system_glb.txt`.
   Name it independently ("fine-tuned from Muse Glimmer"), Apache 2.0, model card with the phase 1 table.

## 9. Open decisions for the owner

1. Approve phase 1 (free) and paste ccore's system prompt.
2. Use ccore's MIT dataset for training too? It would add 3,918 strong examples, but the generator is not stated
   (an earlier ccore set was MiniMax output; MiniMax's output terms unchecked) and it breaks "Muse all the way".
   Default here: evaluation only.
3. Phase 2 generation: Mac (days, free) or a vLLM pod (paid).
4. Publish target: Hugging Face public, or private.
5. Is the product an asset generator (this doc) or the PixiTween timeline director (06-budget-and-risks, question 4)?

## 10. Results

| Date | Model | Pass | Export | Animated pass | Median tris | Recognisable | Median tokens | Notes |
|---|---|---|---|---|---|---|---|---|
| | not run | | | | | | | |

## 11. Method changes and findings during phase 1 (7 Nov 2026)

Nothing here changes the decision rules in section 7. It records what was learned while running, so the results in section 10 can be read honestly.

**Prompt fix, with a leak.** The first 2-brief Glimmer smoke run produced two 15-byte "GLB" files containing the text `[object Object]`.
Cause: Glimmer called `GLTFExporter.parse(asset, onDone, {binary:true})`. In Three.js r160 the signature is `parse(input, onDone, onError, options)`, so the options object landed in the error slot and the exporter returned JSON. The validator caught it (`bad_glb`); "the page renders" would not have.
Fix: `prompts/system_glb.txt` now shows the exact call. g001 and g002 are two of the 48 eval briefs, so the prompt was tuned after seeing them (a small leak, disclosed here). Any further prompt tuning must use a separate dev set of new briefs, and the prompt is frozen before any rating.

**Add-ons (`--allow-addons`).** ccore's pages import `OrbitControls`, `RoundedBoxGeometry` and `RoomEnvironment`; its own prompt allows add-ons. The strict rule scored all 4 smoke answers `bad_import`, which would have failed ccore for following its card. `glb_bench.py` now passes `--allow-addons` to every model's validation, add-ons are served from the local copy, and each row records `stats.addons`. Glimmer's prompt still forbids them; the flag is about scoring the exported GLB, not about house rules.

**Three.js versions.** ccore asks for versions from 0.160.0 to 0.170.0. Serving all of them 0.160.0 could fail pages for API changes, not for bad code. `scripts/fetch_three.mjs` downloads the requested releases into `.cache/three/` (gitignored; `npm pack`, the only network use), and the validator serves each page the version it asked for (`--three-versions-dir`, default `.cache/three`), with `stats.three_requested` and `stats.three_served`. A version that is not cached falls back to 0.160.0 and is flagged `version_rewritten`. Re-validate ccore after fetching: `node scripts/fetch_three.mjs --from-raw eval/glb_bench/ccore-q8/raw`.

**Where each model ran.** Glimmer: local Ollama on the Mac (`muse-glimmer:30b-mlx`, a 4-bit build of about 19 GB, the build people would run; BF16 would need an 80 GB card and is a different model). ccore (`hf.co/ccore/Qwen3.5-4B-GLB-3D-Coder:Q8_0`, digest `271ca3eddf16` on both machines): on a rented RTX 4090 community pod (about $0.34/h, Ollama with 8 parallel slots), reached through an SSH tunnel with `glb_bench.py --ollama-url http://localhost:11435 --concurrency 8`. Generation only; validation and rendering ran on the Mac. The first 4 ccore answers (g001 to g004) come from a smoke run with identical model, prompt and sampling and were reused. Pod cost is recorded in section 10 once it is deleted.

**Interim Glimmer result (plain run, thinking off, add-ons allowed, 48 briefs).** 43 of 48 valid GLBs (89.6%): 4 real code bugs (`js_error`: two invalid animation track names, two undefined variables) and 1 page that never finishes loading (g044: an animation keyframe track with 2 times for 5 values makes the Three.js mixer loop forever; reproduced with a 60 s timeout, so `load_fail` is correct). Median 1,798 tokens per answer, about 40 tok/s locally. Validity alone does not separate the models; section 5.4 (recognisable) decides.

**Added to the decision.** Median seconds per asset on the Mac (ccore's median answer is about 14,000 tokens, Glimmer's about 1,800), median triangles per model (ccore's smoke GLBs had 4,000 to 18,000 triangles; "low-poly" is judged by the share at or under 5,000), and an automatic render-to-brief score (`scripts/clip_score.py`) alongside the human rating, because the human rating cannot be fully blind when one model's answers are about 8 times longer and more detailed. If the two models are within about 15 points on recognisable, add 2 to 3 samples per brief before concluding, and check the 4-bit build against BF16 on a rented A100 before blaming the model.

**Phase 2 note (owner decision, 7 Nov 2026).** The owner is comfortable training on ccore's MIT dataset. Open items before publishing: the dataset card does not name the generating model, so that model's output terms are unchecked; keep ccore's validation split and our 48 briefs out of training; train on answer-only rows (no reasoning) and a shorter subset, estimated 1,000 rows of about 6 to 7K tokens, about 3 to 4 hours on an A100 (estimate from v3's speed, not measured).

**Dev set.** `bench/glb/dev_briefs.jsonl` holds 12 new briefs (ids d001 to d012, no overlap with the 48 eval briefs) for prompt tuning and smoke tests. Never rate or report them as results, and never train on the 48 eval briefs.
