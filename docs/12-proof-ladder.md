# 12. Proof ladder: keep paying for Glimmer training or stop

The ladder answers one question for the owner: does a small open model actually learn the mesh format well
enough to justify more Glimmer data and GPU spend? Each rung is a separate, scored run. A rung passes or fails
on the report `scripts/proof_score.py` writes; a rung with no report is **not run** and is never counted as a pass.

`scripts/proof_ladder.py` holds the thresholds in one `THRESHOLDS` dict at the top of the file. `judge(rung, report)`
returns `(passed, reason)` with the measured counts in the reason, `decide(reports)` returns the plain
recommendation, and the CLI prints one line per rung followed by the recommendation.

## The four rungs and their thresholds

| Rung | What it asks | Pass rule |
|---|---|---|
| `one` | Can the model memorise one training mesh exactly? | exact share `1.0` (1 of 1) **and** stopped share `1.0` (1 of 1) |
| `seen` | Does it reproduce the training objects more generally? | valid share `>= 0.8` **and** stopped share `>= 0.8` |
| `unseen_same_category` | Does it work on held-out objects in a seen category? | valid share `>= 0.6` **(placeholder to revise)** |
| `unseen_new_category` | Does it work on a category it never saw? | valid share `>= 0.4` **(placeholder to revise)** |

The last two thresholds are **placeholders to revise** once those runs exist. They are guesses, not measured
results. `one` uses the exact-text and stopped measures from the scorer; the other rungs use valid and stopped.

## Rung one result, 3 Nov 2026

**Passed.** Qwen2.5-0.5B-Instruct with MLX LoRA (rank 8, 24 layers), one 6,051-character object of 340 faces,
200 iterations at learning rate 3e-5: **519 of 519 lines identical, valid, and stopped at 6,048 tokens**. That
is exact 1 of 1 and stopped 1 of 1.

The same setup at learning rate 2e-4 diverged from loss 0.78 to 11 and produced gibberish. This is why
`decide` names the learning rate first when rung one fails.

Qwen's tokenizer needs about **6,200 tokens** for that object, against about **4,300 tokens** with Glimmer, so
`--max-seq` (and the scorer's `--max-tokens`) must exceed it or the answer is cut off instead of stopping.

## Rung one, through the harness (3 Nov 2026)

`bash scripts/proof_run.sh one` (Qwen2.5-0.5B-Instruct, rank 16, loss on the completion only, lr 3e-5, 200 iterations, about 15 minutes with scoring):
"drawer" came back **495 of 495 lines identical**, valid, stopped at 5,726 tokens. Rung one: PASS.

## Rung seen, measured (3 Nov 2026)

15 different training objects, same settings, 600 iterations, lr 3e-5, max 8,000 tokens.

| Model | exact | valid | stopped | train loss at the end |
|---|---|---|---|---|
| Qwen2.5-0.5B (local, free) | 1 of 15 | 2 of 15 | 3 of 15 | 0.42 (FAIL) |
| Glimmer 30B, BF16 LoRA, 6 epochs on an A100, temp 0.2, 9,000-token cap | 3 of 15 | 4 of 15 | 5 of 15 | 0.043 |

Glimmer's result is **bimodal by mesh length**. Every mesh of 129 to 270 lines was reproduced almost exactly (bookshelf 129 of 129 lines,
icecream 234 of 234, nightstand 270 of 270, cupcake 187 of 266). Every mesh of 750 to 1,100 lines failed: it ran to the cap
and matched 0 to 16 lines. So the limit is the length of the number sequence, not the caption or the amount of training.

Eval loss on the 3 unseen validation objects rose with every epoch (0.29, 0.33, 0.39, 0.42; 0.467 at the end of 6 epochs against 0.368 before
training), against 0.296 after the earlier 2-epoch QLoRA run. More epochs on 36 objects overfit; they did not generalise.

Unseen-caption results for the earlier 2-epoch Glimmer run (30 held-out captions): 2 valid with the fixed decoder at temperature 0.2
(1 valid at 0.7), 22 to 24 hit the cap. The untrained baseline was 9 of 30 valid, but it was given 3 example meshes in the prompt and the trained model was not.

### Rung seen on short meshes only (3 Nov 2026)

Same settings, same Qwen2.5-0.5B, but only the 9 training objects of at most 280 lines (about 140 triangles; 72 of the 288 rows), 600 iterations,
4,000-token cap: **9 of 9 exact, 9 of 9 valid, 9 of 9 stopped**, final train loss 0.038. Rung seen: PASS (about 20 minutes on the Mac, free).
Mixed with long meshes the same model reached only 0.42. So the length of the number sequence is the limit, and the format itself works.
Caveat: 9 objects, all seen in training; this says nothing yet about new objects.

## Rungs three and four

| Rung | Status |
|---|---|
| `unseen_same_category` | measured 3 Nov 2026: **FAIL**, 1 of 6 valid (below) |
| `unseen_new_category` | not measured |

### Rung unseen_same_category, short meshes (3 Nov 2026)

Qwen2.5-0.5B, lr 3e-5, 800 iterations, 4,096 max sequence. Train: 17 short objects x 4 orientations (68 rows; `scripts/proof_unseen.py`).
Held out (never trained): Plant_7, Plant_7_Big, light-square, construction-cone, construction-fence, construction-light, each with a
sibling in training (Plant_1, light-curved, construction-barrier). Result: **0 of 6 exact, 1 of 6 valid, 5 of 6 stopped**; the one valid mesh
(fence, 1,038 tokens) matched 0 lines of the reference. Loss on the held-out objects went 0.73 (step 1), 0.76 (200), 1.02 (300), 1.95 (800)
while train loss fell to 0.02: pure memorisation. 17 objects teach the format, not shape. Captions like "plant" and "light square" are also too
thin to pick a shape. Next: far more short objects and richer captions before this rung can pass.

### Corpus enrichment for the Glimmer run (3 Nov 2026)

Read `data/qurantinus` (Quaternius, CC0; read only). Blender converted 270 FBX/glTF files to GLB in `/tmp/qglb`, `scripts/glb_to_text.py` made text meshes,
and 74 new short objects (at most 200 triangles, not duplicates of the existing `q-` props) were kept. With the 23 earlier short objects that is 97 objects in
`corpus/short_objects.jsonl`, each with a hand-written rich caption in `corpus/captions_short.json` (category, parts, proportions, colours; written from rendered
contact sheets; q20072 and q20073 were not seen and have generic captions). `corpus/short_split.json` holds 19 held-out objects that each have a sibling in train
(cooked patty vs burned/raw, fried egg vs burned egg, strawberry popsicle, window variants, shelf, lamp, plant rosettes, cone). `scripts/proof_unseen.py` drops
meshes over 300 lines (Glimmer's reliable range was up to about 270) and builds 292 train rows (73 objects x 4 orientations) and 18 held-out objects, in MLX chat format
and in `hf/` prompt/completion format for `scripts/mesh_lora_hf.py`.

### Glimmer on the enriched short corpus (3 Nov 2026)

A100 SXM 80GB community pod ($1.39/hr, about 45 minutes, about $1). Glimmer 30B BF16 LoRA, 2 epochs, lr 1e-4, 292 train rows (73 objects x 4 orientations,
rich captions), 18 held-out objects. Held-out loss **fell at every check: 0.607 before, 0.487, 0.453, 0.437, 0.431 after** (the Qwen run's rose 0.73 to 1.95),
so the richer captions and larger set stopped the overfit. Generation at temperature 0.2, 4,000-token cap: **3 of 18 valid** (cone, street light, arched window),
13 of 18 ran to the cap. The failures are the old runaway: for example plant rosette `v 31 63 32, v 31 63 31, v 31 63 30, ...` counting down a coordinate with no faces.
Rung `unseen_same_category` on Glimmer: **FAIL (17% valid against the 60% placeholder)**. Adapter and outputs saved in `artifacts/glimmer-unseen/`. Pod deleted.

### Option 2: loop guard plus 4 samples per caption (4 Nov 2026)

Same adapter, A100 SXM pod (about $0.77, 25 minutes of generation), `mesh_generate.py --samples 4 --loop-guard --temperature 0.6 --max-tokens 4000`.
The guard ends a sample when its last six vertex lines step by the same amount (`runaway()`); the first valid sample per caption is kept.
Result: **6 of 18 captions got a valid mesh (33%)**, up from 3 of 18; 5 hit the cap (was 13); 12 of the 72 samples were valid in total. Rung FAIL (placeholder 60%).
Rendered the 6 against their targets: **valid is not the same as right.** The plate is a good flat octagonal disc; the popsicle (pink column) and the arched window (slab with
cross lines) are crude but the right colour and size; the cone (a shard), the fence (three specks) and the shelf (a tall box, not a low unit) are wrong. So the loop guard fixes
validity, but 73 training objects do not teach the model shape. Colour and rough size are learned; geometry is not. Pod deleted, balance $19.86.

Cost of the Glimmer runs: one H100 pod (about 2.4 hours at $3.99/hr) and one A100 pod (about 3.7 hours at $1.19/hr), both deleted.

## Run it

```bash
bash scripts/proof_run.sh one     # about 10 minutes on this Mac, free
bash scripts/proof_run.sh seen    # about 40 minutes on this Mac including scoring (measured 3 Nov 2026)
```

`proof_run.sh` builds the dataset, trains with MLX LoRA, generates, scores and prints the ladder verdict in
one command. The default learning rate is 3e-5; a rate above 1e-4 is refused with the divergence note below
unless you add `--force-lr`. `--dry-run` echoes the five commands and runs none of them, and `--workdir DIR`
chooses the output folder (default a new folder under `/tmp`).

```bash
bash scripts/proof_run.sh one --dry-run            # show the dataset -> train -> score -> verdict commands
bash scripts/proof_run.sh one --lr 2e-4 --force-lr # only when you mean to reproduce the divergence
```

## Commands

| Step | Command |
|---|---|
| Build the one-row memorisation set | `python scripts/proof_data.py --sft data/mesh/sft/train.jsonl --pick median --n 1 --repeat 1 --out-dir /tmp/proof-one` |
| Train with MLX LoRA (rung one settings) | see [11-mesh-lora-e2e.md](11-mesh-lora-e2e.md); learning rate 3e-5, 200 iterations |
| Score the run | `python scripts/proof_score.py --targets /tmp/proof-one/targets.json --sft-system-from /tmp/proof-one/train.jsonl --model Qwen/Qwen2.5-0.5B-Instruct --adapter /tmp/proof-one/adapter --max-tokens 8000 --temperature 0.0 --out /tmp/proof-one/report.json` |
| Judge rung one | `python scripts/proof_ladder.py --report one=/tmp/proof-one/report.json` |
| Judge rung one and seen | `python scripts/proof_ladder.py --report one=/tmp/proof-one/report.json --report seen=/tmp/proof-seen/report.json` |

## CLI behaviour

`--report RUNG=PATH` is repeatable; valid rung names are `one`, `seen`, `unseen_same_category` and
`unseen_new_category`. The command always prints all four rungs, each as `PASS`, `FAIL` or `NOT RUN` with its
reason, then a `recommendation:` line. It exits 0 for PASS, FAIL and NOT RUN alike, so a missing report does not
look like a crash. There is no output file and no folder is written.

## Corpus growth to 166 objects (4 Nov 2026)

Decimated the 121 Quaternius/Kenney meshes above 400 triangles with Blender (target 150, then 90 triangles when the 300-line cap dropped too many), kept the ones under 300 lines (118), rendered them and hand-curated: 69 kept with rich captions, the rest dropped as triangle soup (burgers, bacon, donuts, maple trees, bushes). Corpus is now 166 objects (97 + 69), `corpus/short_objects.jsonl`, `corpus/captions_short.json`, `corpus/short_split.json`: 31 held out, 135 train (130 under the 300-line cap, 520 rows at 4 orientations). New held-out items have near-duplicates in train (other dead trees, doors, drawers), so that part measures "similar but unseen". No GPU run yet. Dataset builds to /tmp/proof-unseen3, `bash scripts/check.sh` passes.

## Glimmer re-run on 166 objects (4 Nov 2026)

A100 SXM community pod, about $2.85 in total (setup + download + 2 epochs LoRA lr 1e-4 on 520 rows + generation, one OOM retry at batch 30). Held-out loss 0.696 -> 0.508 (73-object run: 0.607 -> 0.431; different held-out set, so not directly comparable). Generation: 30 held-out captions, 4 samples each, loop guard, temp 0.6: 11/30 valid (37%), 9 hit the token cap. The 73-object run was 6/18 (33%). Renders (G vs T pairs): colour and rough size are right, shape is not (couch -> a box, ice cream -> loose fragments, ceiling light -> a blob, window and plate are the only reasonable ones). Rung unseen_same_category stays FAIL (37% vs 60%). Doubling the data raised validity only slightly and did not fix shape. Artifacts: artifacts/glimmer-v2 (adapter, loss.json, gen_v2). Pod deleted, balance $17.01.

## Objaverse CC-BY corpus and sorted meshes (4 Nov 2026, no GPU yet)

User approved CC-BY with attribution. `scripts/fetch_objaverse.py` selects from the 798k Objaverse annotations: licence cc0 or by (CC0 turned out to be only high-detail scans, so everything used is CC-BY), 40-300 faces, no animation, useful categories. 3,000 GLBs downloaded (to ~/.objaverse), Cap3D captions matched for all, 2,828 converted by `glb_to_text.py --sort`. Kept 1,278 after: lines <= 250 (drops 1,088) and caption names a colour while the mesh is grey (drops 462; Objaverse colours live in textures we do not read). 887 distinct authors; `corpus/objaverse_attribution.csv` lists uid, name, author, licence, url for every object and must ship with any model trained on them. Corpus files: `corpus/objaverse_objects.jsonl`, `corpus/combined_objects.jsonl` (166 hand-captioned + 1,278 Objaverse), `corpus/combined_split.json` (1,313 train, 131 held out: the 31 earlier ones + 100 random Objaverse).
New format option: `--sort` (glb_to_text, proof_unseen) orders vertices by z,y,x and faces by lowest index, re-applied after each rotation, as LLaMA-Mesh does. `sort_text()` converts existing text meshes. Dataset: `proof_unseen.py --objects corpus/combined_objects.jsonl --split corpus/combined_split.json --max-lines 300 --orientations 2 --sort` gives 2,616 train rows, average 1.6k characters. Estimated Glimmer run: about 3 hours, $4.
Kenney not scraped (its pages carry a noai / tdm-reservation opt-out; some Kenney objects from earlier work, ids m0xxxx from car-kit and city-kits, should be removed before publishing). Quaternius downloads go through itch.io; user can click Download per pack and drop zips into data/qurantinus.

## Glimmer on 1,298 train objects, sorted format (4 Nov 2026) - RESULT

A100 PCIe pod, 648 steps (2 epochs, 2,586 rows, lr 1e-4, BF16 LoRA, about 3.3 h) plus generation. Cost about $7.3 in total (balance $17.01 -> $9.69; the first generation was lost when I killed the deadman timer and the process died, so generation ran twice). Held-out loss 0.514 -> 0.217 (126 held-out objects, mostly Objaverse). Generation on 30 held-out captions (15 hand-captioned originals, 15 Objaverse), 4 samples each, loop guard, temp 0.6: **24/30 valid (80%)**, 3 hit the token cap. Earlier runs: 3/18 (17%), 6/18 (33%), 11/30 (37%). Validity rung passes the 60% placeholder threshold for the first time.
Shape check (rendered G vs T pairs): about 1 in 3 valid meshes is recognisably the right thing (door slab, stone pedestal, purple sphere, brick wall, rubbish bin, yellow block); the rest have right colour and bounding box but wrong detail (apple -> flat green disc, houseplant -> cone, wireframe prism -> solid box, Celtic ring -> wedge). Better than the earlier ~1 in 6. What changed together: 8x more objects, shorter meshes (<= 250 lines), sorted vertices/faces. Not separated, so which one mattered is unknown.
Artifacts: artifacts/glimmer-v3 (adapter 419,293,392 bytes, loss.json, gen_v3, samples log). Training data: 126 original/hand-captioned (Kenney and unverified PixiTween props removed) + 1,178 CC-BY Objaverse objects; attribution list corpus/objaverse_attribution.csv.
Quaternius Downtown and Medieval MegaKits (CC0, licence files read) converted: 316 meshes, but modular building parts, mostly grey, many near-duplicates; only about 40 worth adding. Bestiary kit uses the Quaternius Asset License v1.0 (no resale or redistribution of assets), so excluded.

## Glimmer on ~3,500 train objects, sorted (4 Nov 2026) - FINAL RESULT

Held-out loss 0.2164 (v3 0.217). 34/45 valid (76%); on the 30 prompts shared with v3, 21 valid vs v3 24. Pick rule: medoid gives a valid pick on 34/45 prompts; first sample alone 20/45. Visual: many valid outputs are generic boxes, about 15-20% of prompts recognisable, no better than v3. More of the same data has plateaued at this format; next levers are representation (e.g. vertex quantisation/part tokens), a better base for captions, or accepting a research preview. Artifacts: artifacts/glimmer-v4.
