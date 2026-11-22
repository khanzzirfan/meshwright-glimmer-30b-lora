# Working notes (state on 7 Nov 2026)

> **Archived.** Part of the research history behind Meshwright v1; kept for reference and not current. See [15-release.md](15-release.md) for the release and [README.md](README.md) for all docs.

- ccore released Qwen3.5-4B-GLB-3D-Coder (5 Nov, Apache 2.0, Three.js page + Export GLB, no published scores). Mesh-text v3/v4 plateaued at ~15-20 % recognisable.
- Plan and full spec: [13-glb-code-track.md](13-glb-code-track.md). Phase 1 = free benchmark of untuned Glimmer vs ccore on 48 asset briefs (`bench/glb/briefs.jsonl`), scored by an Export-GLB check and a blind human rating; decision rules A/B/C in section 7 are fixed before the run.
- Tooling to build: Ralph PRD `ralph/glb-1.prd.json` (7 stories, 0 done). Run: `ralph/run-models.sh ralph/glb-1.prd.json`.
- Owner to do: paste ccore's system prompt into `prompts/ccore_glb_system.txt` (placeholder now), `ollama pull hf.co/ccore/Qwen3.5-4B-GLB-3D-Coder:Q8_0`, answer the open decisions in section 9.
- 0 pods. Nothing committed.

# CURRENT STATE, 3 Nov 2026, 09:40 UTC: no paid resources running (read this block, the rest is history)

- 4 Nov 2026 (FINAL RUN v4): Glimmer on ~3,500 CC-BY/CC0 objects (sorted, 1.5 epochs): held-out loss 0.2164 (v3 0.217, flat). 34/45 valid (76%); on the 30 prompts shared with v3: 21 valid vs 24 for v3 (noise-level). Medoid pick: 34/45 prompts valid, first sample alone 20/45. Visual check: many outputs are generic boxes; roughly 7-9 of 34 valid are recognisable (apple-ish blob, tables, purple blob, monitor), so ~15-20% of prompts, NOT better than v3 despite 2.7x data. Conclusion: data scale alone has plateaued at this mesh format; v3 and v4 are equivalent, ship either as a research preview. Adapter in artifacts/glimmer-v4 (419,293,392 bytes, verified). 0 pods, balance $13.84 after top-up. Cost of run ~ $5.

- Paper draft: paper/main.tex (arXiv style, final-run numbers TBD, no LaTeX compiler installed here; verify Cap3D/Objaverse citations; decide adapter licence). Fill after the next Glimmer run.

- 4 Nov 2026 (latest): Glimmer on 1,298 CC-BY/CC0 objects with sorted vertices: held-out loss 0.514->0.217, 24/30 valid (80%), about 1 in 3 valid meshes recognisable. Adapter in artifacts/glimmer-v3. 0 pods, balance $9.69. Next: more objects (CC-BY Objaverse has ~57k under 500 faces), maybe longer meshes, then export (merge/GGUF/Ollama) and attribution file for publishing.

- 4 Nov 2026 (latest): 1,278 CC-BY Objaverse objects + 166 hand-captioned, sorted-vertex format option, dataset built at /tmp/proof-v3 (rebuild with the command in 12-proof-ladder.md). Attribution list: corpus/objaverse_attribution.csv. Glimmer run on it NOT started (about 3 h, $4, balance $17.01, 0 pods). Remove Kenney-sourced objects before publishing.

- 4 Nov 2026 (later): Glimmer re-run on 166 objects: held-out loss 0.696->0.508, 11/30 valid (37%), shapes still wrong. Data x2 barely moved validity. 0 pods, balance $17.01. Next lever is the mesh format / representation, not more of the same data.

- 4 Nov 2026: corpus grown 97 -> 166 objects (69 decimated Quaternius/Kenney meshes, hand-curated, rich captions). No GPU run yet, 0 pods, balance $19.86. Next: a Glimmer re-run on 130 train objects (~$1-2) when approved.

**4 Nov 2026: loop guard + 4 samples took held-out validity from 3 to 6 of 18, but only about 1 in 6 valid meshes looks right (plate good; popsicle/window rough; cone, fence, shelf wrong).** Validity is fixed, shape is not: 73 training objects do not teach geometry. 0 pods, balance $19.86. Next lever is the data and format, not decoding. See docs/12-proof-ladder.md.

**Glimmer on the enriched short corpus (3 Nov 2026): held-out loss improved (0.61 to 0.43) but only 3 of 18 held-out meshes valid; 13 ran into the 4,000-token cap in runaway coordinate loops.** Adapter in artifacts/glimmer-unseen/. Pod deleted, 0 pods, balance $20.80. Training is now healthy; the blocker is generation of unseen shapes (runaway loops). See docs/12-proof-ladder.md. Corpus: corpus/short_objects.jsonl, captions, split.

**Rung unseen_same_category (3 Nov 2026, free, Mac): FAIL, 1/6 valid.** 17 short objects trained, 6 sibling objects held out; held-out loss rose 0.73 to 1.95 while train loss hit 0.02. It memorises, it does not generalise at this data size. Do not spend GPU on Glimmer until the corpus is far larger (hundreds of short objects, richer captions). See docs/12-proof-ladder.md.

RunPod: **0 pods** (H100 and A100 both deleted, deadman timers stopped), balance $21.83. Everything is on the Mac. Nothing is committed.

Result in one line: the pipeline works, but models only reproduce **short** meshes (up to about 270 lines); long ones run away. Confirmed free on the Mac: Qwen 0.5B trained on only the 9 short objects reproduces 9 of 9 exactly.
Full numbers and the ladder: [12-proof-ladder.md](12-proof-ladder.md). Artifacts: `out/mesh-lora` (2-epoch QLoRA), `out/mesh-lora-e6` (6-epoch BF16, overfit; `checkpoint-36` is its epoch 1), `eval/glimmer_e6_seen`, `eval/mesh_lora_hf_t02`, `eval/mesh_lora_hf_seen`.

What was built this session: batched HF generation with a correct decoder in `scripts/mesh_generate.py`; the proof harness `scripts/proof_data.py`, `proof_score.py`, `proof_ladder.py`, `proof_run.sh` (built by Ralph with DeepSeek free, reviewed and one bug fixed by hand); `ralph/proof-1.prd.json` and `ralph/run-models.sh`.
Ralph notes: `ralph-tui run --model X` crashes (`j.split is not a function`), so set the model line in `.ralph-tui/config.toml`. The NVIDIA free endpoint is slow for DeepSeek (75 s per tiny call) and Kimi is not served; `opencode/deepseek-v4.1-flash-free` worked. Always check a "pass" against the story's filenames: Nemotron Lightning invented its own.

Next, in order (all free): (1) rung `unseen_same_category` on short meshes with the small model (new short objects, not seen in training); (2) filter the corpus to meshes of about 150 triangles or fewer and retrain; (3) only then consider another Glimmer run, on an A100 community pod ($1.19/hr, about 50 s per step, 6 epochs took 3.1 hours) and stop at epoch 1 to 2, because eval loss rises after epoch 1.

# EARLIER UPDATE 3 Nov 2026, 05:00 UTC (history; the first pod, now deleted)

Pod `mxk8dcvdacybo9` ran 02:36 to 04:59 UTC (about 2.4 h, about $9.50) and is deleted; the deadman switch is stopped. Everything is on the Mac.

| Run | Where | Result |
|---|---|---|
| 2-epoch QLoRA (72 steps) | `out/mesh-lora/` (adapter, `loss.json`), `out/full.log` | eval loss 0.383 -> 0.296 on 3 unseen objects |
| 30 held-out captions, temp 0.7 | `eval/mesh_lora_hf_t07_rawdecode/` | 1 valid (2 after stripping a decode artifact), 22 cap hits. **Worse than baseline 9** |
| 30 held-out captions, temp 0.2 | `eval/mesh_lora_hf_t02/` | 2 valid, 24 cap hits |
| 15 **training** captions, temp 0.7 | `eval/mesh_lora_hf_seen/` | 3 valid, 9 cap hits: it cannot even redraw objects it trained on |
| 6-epoch BF16 LoRA | `out/e6.log` | stopped at step ~20 by decision; BF16 LoRA fits an H100 at 70.6 GB |

What was checked and is correct: completions end in `<|eot|>` (a generation stop id), no row is truncated (max 8,526 of 9,728 tokens), loss is on the completion only.
Fixed: `mesh_generate.py` now decodes with special tokens and `clean_reply()` (plain `skip_special_tokens` left `to=user` glued to line 1), and has a batched HF path (`--batch`).
Failure mode: the model falls into counting loops (`v 9 63 9`, `v 9 61 9`, ...) and never stops.
Diagnosis: (1) undertrained, since it fails on its own training objects after 2 epochs; (2) the held-out test is mostly categories absent from the 36 training objects, so it cannot pass even when trained well.
Next: train longer on a cheap 48 GB card or the Mac (QLoRA peaked at about 36 GB), first scoring on seen captions, then grow the data and pick test captions from training categories. Use vLLM, not `model.generate` (about 8 to 10 tokens/s per sequence), for generation.
Traps hit: `HF_HOME=/workspace/hf` is not set in ssh shells (it re-downloaded to the 40 GB root disk and crashed); scp fails on this image, so copy with `ssh ... 'tar cf - ...' | tar xf -`; `pkill -f pattern` over ssh kills its own shell.

# Handover to the next agent (written 3 Nov 2026, pod clock about 02:58 UTC)

Read this first, then [00-architecture.md](00-architecture.md) (the whole picture) and [11-mesh-lora-e2e.md](11-mesh-lora-e2e.md) (the run plan).
Working folder: the repository root.

## 1. The goal in one paragraph
Fine-tune **Muse Glimmer 30B** with LoRA so it writes low-poly 3D assets as text meshes from a prompt, trained on real CC0 assets, exported as GLB.
The proof being run now: LoRA on 36 small objects, then re-measure on the same 30 held-out captions as the untrained baseline.
**Baseline to beat (3 Nov): 9 of 30 valid, 0 detailed, 11 answers that never stopped (hit the token cap).**

## 2. LIVE PAID RESOURCES: check these first

| Thing | Detail |
|---|---|
| RunPod pod | id `mxk8dcvdacybo9`, name `mesh-lora-h100`, **H100 SXM 80 GB, AP-JP-1, secure cloud, $3.99/hr**, created 02:36 UTC |
| Budget | the owner approved running up to about 10 hours and will top up. Balance was $15.51 at about 02:58 (spend limit $80). Expected use is 2 to 3 hours, **not** 10 |
| SSH | `ssh -i ~/.runpod/ssh/runpodctl-ssh-key -o StrictHostKeyChecking=accept-new -p 10068 root@157.66.254.13` (IP and port can change if the pod restarts; `runpodctl pod get mxk8dcvdacybo9`) |
| Pod disk | `/workspace` (140 GB volume) holds the weights (56 GB at `/workspace/hf`), the code (`/workspace/mesh`), the venv (`/workspace/venv`) and all outputs. **It is deleted with the pod: copy results back first** |
| Deadman switch | a `sleep 39600; runpodctl pod delete mxk8dcvdacybo9` runs on the Mac (pids visible with `pgrep -fl "sleep 39600"`). It dies if the Mac sleeps long, reboots or the session cleans up. **Do not rely on it; delete the pod yourself when done** |
| Not ours | the 80 GB volume `h3-weights-jp-v1` in AP-JP-1, the volume `grip-blender-cache`, and the many exited pods. Do not touch them |

Finish with:
```bash
runpodctl pod delete mxk8dcvdacybo9 && runpodctl pod list --all | head      # confirm it is gone
pkill -f "sleep 39600"                                                      # stop the deadman switch
runpodctl user                                                              # check the balance
```
The owner wants a paid pod running only as long as needed. Tell them the final cost.
**Owner decision (3 Nov): the next agent, not the owner, deletes the pod once the results are copied back.** The previous agent has stopped working and will not do it.

## 3. What is running right now

- **Smoke run: DONE and successful** (`out/smoke` on the pod). 10 steps, QLoRA 4-bit, 2 rows per step: about **3.9 s per step, so about 1.9 s per row**. Eval loss **0.383 before, 0.326 after** 10 steps (train loss 0.49, 0.60, 0.38, 0.57, 0.36, noisy as expected). So loading through `AutoModelForMultimodalLM`, the regex LoRA targets, TRL and the chat template all work on this stack.
- **Full run: STARTED 02:56 UTC by the pod clock**: `scripts/mesh_lora_hf.py --out out/mesh-lora --epochs 2 --grad-accum 8`, log `/workspace/mesh/full.log`, writes `out/mesh-lora/` (adapter) and `out/mesh-lora/loss.json`. 288 rows x 2 epochs / 8 = 72 steps at about 15 s each, plus evals: **expected 20 to 30 minutes**, not hours. Check it with
  `ssh ... 'tr "\r" "\n" < /workspace/mesh/full.log | grep -vE "Loading weights|^\s*$" | tail -5'` and `ps aux | grep -E "python.*mesh_lora" | grep -v grep`.
  Peak GPU memory in the full run is unmeasured (the smoke run ended before a reading); if it runs out of memory, lower `--max-len` or `--grad-accum`.
- **The pod is billing while idle.** When the full run ends the GPU does nothing until step 4 below; do not let it sit.
- On the Mac: **the MLX conversion FAILED (exit 1)** after downloading the BF16 weights (about 58 GB now in `~/.cache/huggingface`). `mlx_lm convert` of `meta-models/Muse-Glimmer-30B` stops with `ValueError: Received 809 parameters not in model`: the vision tower keys in the official checkpoint are named `model.vision_tower.*`, `model.vision_adapter.*`, `model.vision_projection.*`, while mlx-lm 0.32.2's text-only `muse_glimmer.py` `sanitize()` only drops keys starting `vision_tower`, `vision_adapter`, `vision_projection` (no `model.` prefix). A one-line patch to that prefix check, or stripping those tensors first, would probably fix it; untried. The free local MLX route is therefore **not working yet**; the pod route is the plan. `models/` has only `convert.log`.

## 4. Next steps in order

1. **Let the full run finish** (section 3) and read `out/mesh-lora/loss.json`: eval loss before and after, and the train-loss log. Smoke result for reference: 0.383 to 0.326 after 10 steps.
2. (If it failed) fix, rerun with `setsid nohup ... < /dev/null &`; BF16 is `--quant none` (58 GB weights, tight on 80 GB).
3. **Generate the 30 held-out captions with the adapter:**
   `python scripts/mesh_generate.py --backend hf --hf-model meta-models/Muse-Glimmer-30B --adapter out/mesh-lora --out eval/mesh_lora_hf`
   Plain `model.generate` on a 4-bit or BF16 30B is slow (about 5,000 tokens per mesh, possibly minutes each, 30 in a row). If it is too slow, batch the prompts, or merge the adapter and serve with vLLM. Do not leave the pod idle while deciding.
4. **Score:** `python scripts/mesh_quality.py --run eval/mesh_lora_hf --pairs eval/mesh_lora_hf/pairs.jsonl`, then `node scripts/preview_mesh.mjs --in eval/mesh_lora_hf/pairs.jsonl --n 100 --out eval/mesh_lora_hf/pairs.png` on the Mac.
5. **Copy back** `out/mesh-lora` (the adapter, small), `out/*/loss.json`, `eval/mesh_lora_hf`, the logs. Then delete the pod (section 2).
6. **Write the result** into [00-architecture.md](00-architecture.md) section 7 and [11-mesh-lora-e2e.md](11-mesh-lora-e2e.md), comparing against the baseline table there. Report honestly if it did not improve.

Success looks like: valid clearly above 9 of 30, cap-hits near zero, some answers with fscore at least 0.5 and face ratio at least 0.25.

## 5. Facts learned (they cost time; do not rediscover)

- **Model class:** `AutoModelForCausalLM` does not know Glimmer. Load with `AutoModelForMultimodalLM` (`MuseGlimmerForConditionalGeneration`, 29.78B params). Language linears are all under `model.language_model.*` (52 layers: q, k, v, o, gate, up, down); vision is `model.vision_tower`, `vision_adapter`, `vision_projection`. LoRA targets the text decoder by regex.
- **Versions on the pod:** torch 2.9.1+cu128, transformers 5.22.1, trl 1.17.1, peft 0.21.2, bitsandbytes 0.50.2, Python 3.12 in `/workspace/venv` (created with `--system-site-packages`; system pip is externally managed).
- **Chat template:** assistant turns render as `<|start|>assistant to=user<|message|>CONTENT<|eot|>`. The system block adds `Reasoning strength: high.` by default; the only switch is the `reasoning_strength` template argument (low, medium, high, max). **There is no off value** (a falsy value falls back to high). Training and generation both use the default so they match. The Mac baseline ran Ollama with `think: false`, so before and after differ in that one respect.
- **Tokens:** 0.65 to 0.75 per character, measured with Glimmer's own tokenizer (Ollama `prompt_eval_count`). About 12 tokens per triangle. Longest training row is about 4,950 tokens for 7,062 characters; the proof trains on objects up to 600 triangles.
- **TRL 1.17:** `SFTConfig` has no `warmup_ratio` (use `warmup_steps`, a float is a fraction). Conversational prompt/completion rows are supported; loss is on the completion only.
- **mlx-lm 0.32.2** has `muse_glimmer.py` (text-only port) and `mlx_lm.convert -q`, but converting the official checkpoint fails on the `model.vision_*` key prefix (section 3). A local MLX LoRA is therefore unproven.
- **Shell traps:** `pgrep -f name` over ssh matches its own command line (always "running"); use `ps aux | grep -E "python.*name" | grep -v grep`. An ssh command that starts a background job hangs unless it is started with `(setsid nohup cmd > log 2>&1 < /dev/null &)`. A heredoc `python3` on the pod is the system Python without transformers; call `/workspace/venv/bin/python`. HF downloads were fast (56 GB in about 2 minutes).
- **zsh:** a variable holding `ssh -i ... -p ...` does not word-split; use a wrapper script (the session used one in its scratchpad; recreate it).

## 6. What exists in the repo (all uncommitted: `muse-threejs` has no commits and about 69 changed or new paths)

| Area | Files | State |
|---|---|---|
| Mesh data | `scripts/glb_to_text.py`, `mesh_filter.py`, `mesh_validate.py`, `mesh_quality.py`, `preview_mesh.mjs` | built, tested, run |
| Baseline | `scripts/mesh_baseline.py`, `eval/mesh_baseline/` (30 answers, `summary.json`, `quality.json`) | run: 9 valid, 0 detailed |
| Proof pipeline | `scripts/mesh_sft_data.py`, `mesh_lora_hf.py`, `mesh_lora_mlx.sh`+`.yaml`, `mesh_generate.py`, `data/mesh/sft/` | data built; train script mid-smoke on the pod; generate untested with a real model |
| Docs | `docs/00-architecture.md`, `architecture.svg`, `08-mesh-track.md`, `11-mesh-lora-e2e.md`, this file | current |
| Tests | `tests/py/` | 23 pass (`bash scripts/check.sh`) |
| Ralph PRDs | `ralph/src/prd-05-mesh.json` (6 stories), `prd-06-captions-corpus.json` (9) | built and valid, **never run: 0/6 and 0/9** |
| Other | `scripts/nim_smoke.py` | written, never run (needs the owner's NVIDIA key) |

Ralph was stopped by the owner earlier (it was on the older code-track PRD 1, 1 of 6). It runs offline on free NVIDIA models through opencode; DeepSeek v4.1 Flash struggled with tool calls there. Added to `opencode.json` untested: Nemotron (ultra, super, lightning) and `z-ai/glm-5-3-flash`. Run the mesh PRDs with `ralph/run-all.sh --only 5` then `--only 6`, never plain `run-all.sh`. See [../ralph/README.md](../ralph/README.md).

## 7. Decisions and the owner's preferences

- **Student = Muse Glimmer** (Apache 2.0, dense 30B, public BF16 weights, llama.cpp and mlx-lm support). The goal is a published "Muse" model, so Qwen or others are only for quick proofs.
- **Spark Open is not used**: 816B-A42B and the Muse Model License (derivatives and attribution terms, unread). It could caption later if the licence is read and accepted.
- **DeepSeek (free NVIDIA endpoint) only for tooling and reviews**; keep its text out of `train.jsonl`. Captions come from Glimmer. Do not let an AI judge replace the code metrics.
- **Spending:** ask before any paid action. Explicitly approved so far: the H100 pod above (up to about 10 hours) and the 58 GB download. Not approved and not touched: the AWS `clippydev` profile, Baseten.
- **Naming:** Apache 2.0 allows publishing a fine-tune but does not grant the Muse trademark; use "fine-tuned from Muse Glimmer" and an independent name (my reading, not legal advice).
- Train first, expand data after. The new `data/qurantinus` folder (243 FBX, 36 glTF, no licence file) waits until the pack and licence are confirmed and FBX is converted.

## 8. Open questions (unverified)

- Does the full 2-epoch run keep improving without overfitting 36 objects? (the full run answers this; the 10-step smoke run already trained cleanly)
- How fast is generation, and is `model.generate` usable for 30 meshes of about 5,000 tokens?
- Does `mesh_generate.py --backend hf` work end to end? (class and template calls were adapted but never run)
- GGUF export of a merged Glimmer through llama.cpp (b10353 or later has the architecture) is untested; `scripts/export_gguf.sh` still assumes the old Qwen flow.
- Licence of the 13 non-`q` Prop library that are in the training objects; Spark Open licence; NVIDIA free-endpoint terms.
- Only 36 training objects, 3 repeated captions; this proves format and stopping, not generalisation.

## 9. First 10 minutes for you

```bash
cd muse-threejs   # the repository root
runpodctl pod get mxk8dcvdacybo9 | head -20       # is the pod still running, and what does it cost
bash scripts/check.sh                              # repo is healthy (23 tests)
# then read the smoke log on the pod (section 3) and continue from section 4
```
