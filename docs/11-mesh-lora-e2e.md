# 11. Mesh LoRA proof, end to end

> **Archived.** Part of the research history behind Meshwright v1; kept for reference and not current. See [15-release.md](15-release.md) for the release and [README.md](README.md) for all docs.

Goal: show that a LoRA on Muse Glimmer measurably improves 3D asset generation, using one repeatable path from
data to scored output. Baseline to beat (untrained Glimmer, 30 held-out captions, 3 Nov 2026): **9 valid, 0 detailed, 11 runaway
answers that hit the token cap**. See [08-mesh-track.md](08-mesh-track.md) and [00-architecture.md](00-architecture.md).

## What was built and what has actually run

| Piece | File | Status |
|---|---|---|
| Training data (prompt = system rules + caption, completion = real mesh) | `scripts/mesh_sft_data.py` | **run**: 288 train and 24 val rows from 39 objects, 30 held out, 3 tests |
| Chat-format copy for MLX | `data/mesh/sft/mlx/` | **run** |
| Generate and score held-out captions with any backend | `scripts/mesh_generate.py` | tested with a fake model (3 tests); no real model run yet |
| Local training, free | `scripts/mesh_lora_mlx.sh` + `mesh_lora_mlx.yaml` | **blocked**: `mlx_lm convert` of the official checkpoint fails (`809 parameters not in model`, the `model.vision_*` key prefix); see HANDOVER.md |
| GPU-box training (RunPod, AWS) | `scripts/mesh_lora_hf.py` | dry run of the data check only; model loading is **unverified** |
| Quality score | `scripts/mesh_quality.py` | run on the baseline |

## Facts found on the way (they shaped the design)

- **Tokens are 0.65 to 0.75 per character**, measured with Glimmer's own tokenizer through Ollama: a 136-triangle plate is 1,650 tokens, a
  783-triangle rock 9,560, a 1,922-triangle van 23,170. Roughly 12 tokens per triangle. So a 380-triangle test mesh needs about
  5,000 tokens, and the baseline's 9,000-token cap was close to the real need for bigger ones.
- The proof therefore trains on objects up to 600 triangles (longest row about 9,500 tokens). Bigger ones need a more compact text encoding, which is the next lever.
- **`mlx-lm` 0.32.2 has a Glimmer port** (`muse_glimmer.py`, text-only, with the layer hooks LoRA needs), but converting the official checkpoint failed on the vision-weight key prefix, so the free local run is **not working yet**. The RunPod path (Path B, now the main one) trained successfully.
- The 30 test captions were chosen before training and are excluded, with all their rotated copies, from the training files.
- Honest limit: only 36 training objects (31 Prop library, 7 nature pieces), and 3 captions repeat across objects. This proves format, stopping and detail level can be learned; it does not prove generalisation to categories like traffic lights. More kits and real captions come after.

## Run it

```bash
cd muse-threejs   # the repository root
python scripts/mesh_sft_data.py            # already run; rebuilds data/mesh/sft
```

### Path A: this Mac, free (try first)
```bash
CONFIRM_DOWNLOAD=yes bash scripts/mesh_lora_mlx.sh convert   # one time, about 58 GB down, about 18 GB written
bash scripts/mesh_lora_mlx.sh smoke                          # 20 iterations and 2 captions: does it train and generate?
bash scripts/mesh_lora_mlx.sh full                           # 600 iterations, then all 30 captions, then scoring
```
The smoke run prints seconds per iteration; multiply to know how long `full` takes before starting it. Memory is not the
worry on 96 GB with a 4-bit copy; speed is unmeasured.

### Path B: rented GPU, only if A fails or is too slow
Needs your approval before any pod is created. One card with 48 GB (QLoRA, `--quant 4bit`) or 80 GB (BF16 LoRA, `--quant none`).
```bash
python scripts/mesh_lora_hf.py --max-steps 20      # smoke
python scripts/mesh_lora_hf.py                     # full; prints eval loss before and after
python scripts/mesh_generate.py --backend hf --hf-model meta-models/Muse-Glimmer-30B --adapter out/mesh-lora-hf --out eval/mesh_lora_hf
python scripts/mesh_quality.py --run eval/mesh_lora_hf --pairs eval/mesh_lora_hf/pairs.jsonl
```
Copy `out/mesh-lora-hf` (the adapter, small) and `eval/mesh_lora_hf` back, then stop the pod.

## Where to run it: options

| Option | Good for | Cost and catches | Status |
|---|---|---|---|
| **This Mac (MLX)** | the proof: free, 96 GB memory, 279 GB disk free | speed unmeasured; mlx-lm trainer on Glimmer unproven | try first |
| **RunPod** | fast training on an A100 or H100 for an hour or two; pull the adapter back and stop | hourly billing; **prices not checked**; pods cost money until stopped | fallback; ask before creating a pod |
| **AWS clippydev profile** | if you want it on an account you already have | single-GPU options such as `g6e` (L40S 48 GB, fits QLoRA) or `p4`/`p5` (80 GB, expensive); new or dev accounts often have **zero GPU quota** until a quota request is approved; bills that account; **not checked, not touched** | possible; needs your go-ahead and the account owner's |
| **Baseten** | hosting the finished model as an endpoint for a demo (Truss with vLLM, adapter attached) | not needed for the proof; deployment details **unverified**; Spark Open is already there but we are not using it | after the proof |
| **Ollama on the Mac** | serving the final GGUF for a demo app | needs the merge and llama.cpp conversion step, **untested** | after the proof |

Recommendation: prove it on the Mac, fall back to a rented 48 to 80 GB card if it is too slow, and host on Baseten or locally only once the numbers justify a demo endpoint.

## What counts as proof

Same 30 held-out captions, same validator and fscore, zero-shot (no examples in the prompt):

| Metric | Baseline (before) | Pass this to call the LoRA a success |
|---|---|---|
| valid | 9 of 30 | clearly higher (for example 20 or more) |
| answers hitting the token cap | 11 of 30 | near zero |
| detailed (fscore >= 0.5 and face ratio >= 0.25) | 0 of 30 | more than a handful |
| median face ratio of valid answers | 0.20 | toward 1.0 |
| eval loss (HF path) | measured before training | falls |

If valid and cap-hit numbers do not move, the data or settings are wrong, not the idea; look at `pairs.png` first.
Note the baseline was few-shot with thinking off; the trained runs are zero-shot, which is the harder setting. Glimmer's default thinking level is high, so
set the matching switch through `--chat-template-kwargs` (**VERIFY the argument name** in the model's template).

## After the proof
Real captions (PRD 6), more kits including the new `data/qurantinus` folder once its licence is confirmed and FBX is converted, a compact mesh encoding,
GGUF export and Ollama (`scripts/export_gguf.sh` needs adapting), and GLB output through `mesh_to_glb` (PRD 5).
