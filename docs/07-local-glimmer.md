# 07. Start locally with Muse Glimmer (no paid calls)

> **Archived.** Part of the research history behind Meshwright v1; kept for reference and not current. See [15-release.md](15-release.md) for the release and [README.md](README.md) for all docs.

Recommended first step. Glimmer is Apache 2.0, so the licence question in
[01-licensing.md](01-licensing.md) goes away for this phase, and it costs nothing but time.

## Measured on this Mac (3 Nov 2026)
Machine: M3 Max, 96 GB. Model: `muse-glimmer:30b-mlx` in Ollama (already installed).
One level-5 brief ("low-poly lighthouse on a rocky island at dusk, rotating beam, gentle waves"):

| Mode | Output tokens | Speed | Wall time | Result |
|---|---|---|---|---|
| `think: false` | 2,300 | 40.6 tok/s | 66 s | one html block, only the pinned Three.js import, rAF loop, JS parses |
| `think: true` | 6,354 (18k chars of thinking) | 37.9 tok/s | 168 s | same checks pass |

Both answers followed the system prompt. Neither has been rendered yet (Playwright not installed),
so "renders correctly" is still unmeasured. One brief is not a pass rate; the 50-brief pilot below is.

## What that means for time
| Run | Calls | No thinking (~1.1 min each) | With thinking (~2.8 min each) |
|---|---|---|---|
| Pilot | 50 | ~1 h | ~2.5 h |
| Small dataset | 1,000 | ~18 h | ~47 h |
| ccore-sized (≈6k calls for ≈4k kept) | 6,000 | ~110 h | ~280 h |

Ollama serves one request at a time by default; parallel requests on one Mac mostly split the same
throughput, so `--concurrency 1` is right. Higher-level briefs produce longer scenes, so these are lower bounds.

**Plan:** use Glimmer locally for the pilot and a 500-1,000 example first dataset. That is enough
to prove the pipeline, tune the validator and train a first LoRA. Move to Spark Open on Baseten
only if the student is clearly limited by teacher quality, and only after the licence check.

## Commands

```bash
cd muse-threejs   # the repository root
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm install && npx playwright install chromium

# 1. briefs, written by Glimmer through Ollama's OpenAI-compatible route
python scripts/gen_briefs.py --count 50 --out data/briefs.jsonl \
  --base-url http://localhost:11434/v1 --api-key ollama --model muse-glimmer:30b-mlx

# 2. scenes, via the native Ollama API (the route where `think` is a real switch)
python scripts/teacher_generate.py --briefs data/briefs.jsonl --out data/raw \
  --ollama-native --model muse-glimmer:30b-mlx --concurrency 1          # add --think for traces

# 3-4. same as the Baseten path
node scripts/validate_scenes.mjs --raw data/raw --scenes data/scenes --shots data/shots --report data/validation.jsonl
python scripts/build_dataset.py --briefs data/briefs.jsonl --raw data/raw --report data/validation.jsonl --out data/sft
```

Leave it running overnight with `caffeinate -i` in front of step 2. The script is resumable: stop
and restart and it skips scenes already saved.

## Thinking or not?
- **Without thinking:** 2.5x faster, and the student learns to answer directly (short outputs, fast on a 4B model).
- **With thinking:** traces are about 3x the size of the code. They may help the student on hard scenes but triple generation time and training length.
- Suggestion: pilot both on the same 50 briefs, compare pass rates, then pick. `build_dataset.py --no-reasoning` lets you drop traces later even if you collected them.

## Training locally too (optional)
A 4B LoRA can train on this Mac with MLX instead of a rented GPU:

```bash
pip install mlx-lm
mlx_lm.lora --model Qwen/Qwen3.5-4B --train --data data/sft --iters 1000 --batch-size 1 --max-seq-length 12288
```

**VERIFY** before relying on it: that `mlx-lm` supports the Qwen3.5 architecture, and that it reads
the prompt/completion JSONL as written by `build_dataset.py` (MLX expects `train.jsonl` and `valid.jsonl`,
so rename `val.jsonl`). Expect it to be several times slower than an H100, but free. For the
full-size run, the GPU path in [04-training.md](04-training.md) is still the better choice.

## Other local teachers you already have
`qwen3-coder:30b` and `qwen3.8:27b` are installed. They are not Muse, but running the same 50 briefs
through them gives a cheap baseline: if Glimmer's pass rate is far lower, mixing in another
Apache-licensed teacher is an option (check each model's licence first).
