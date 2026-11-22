# 02. Environment setup

> **Archived.** Part of the research history behind Meshwright v1; kept for reference and not current. See [15-release.md](15-release.md) for the release and [README.md](README.md) for all docs.

## Machines
- **Data generation and validation:** your Mac is fine. The teacher runs on Baseten; validation runs Chromium locally (software WebGL).
- **Training:** one rented GPU. A single 80 GB H100 (or A100 80 GB) is comfortable for a 4B model. Options: RunPod (you already have the `runpodctl` skill), Lambda, or Baseten training. A 4B LoRA also fits on a 24 GB card with 4-bit loading, but full fine-tuning does not.
- **Serving the result:** your Mac via Ollama or llama.cpp (Q4_K_M is roughly 2.5-3 GB).

## Accounts and keys
| Need | Where | Goes in |
|---|---|---|
| Baseten API key | Baseten dashboard | `.env` `BASETEN_API_KEY` |
| Spark Open model slug on Baseten | `meta-models/muse-spark-open-1026` (the hackathon key only works with this name) | `.env` `TEACHER_MODEL` |
| Brief writer (can be the same endpoint) | same | `.env` `BRIEF_MODEL` |
| Hugging Face token (download Qwen, optionally push) | huggingface.co/settings/tokens | `.env` `HF_TOKEN` |
| GPU host | RunPod or similar | not stored here |

Baseten's hosted model APIs are OpenAI-compatible, so the scripts use the `openai` Python client with
`BASETEN_BASE_URL` (default `https://inference.baseten.co/v1`). Setup and smoke test: [baseten-spark-open.md](baseten-spark-open.md).

Never commit `.env`. `.gitignore` already excludes it, plus `data/`, `out/`, `.venv/`, `node_modules/`.

## Local install

```bash
cd muse-threejs   # the repository root
cp .env.example .env
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm install
npx playwright install chromium
```

`npm install` pulls `three@0.160.0`. The validator serves that file in place of the CDN URL
(`https://cdnjs.cloudflare.com/ajax/libs/three.js/0.160.0/three.module.min.js`), so validation is
offline, fast and deterministic. The pinned version matters: it is the one ccore trains against.

## GPU box install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-train.txt
huggingface-cli login            # token with read access
```

The Qwen3.5 model card says it was verified with Transformers 5.20.2. `requirements-train.txt` pins a floor of 5.x; if the model fails to load, install the exact version from the card.

## Headless WebGL note
Chromium headless uses SwiftShader (CPU WebGL). It is slow but correct. The validator launches with
`--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader`. If scenes render blank on your Mac for every example, check `data/shots/` first; it is more likely a launch flag problem than a data problem.
