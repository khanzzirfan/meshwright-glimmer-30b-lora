# Documentation

Meshwright v1 turns one sentence into a low-poly, game-ready GLB. Start with the project
[README](../README.md); the documents below go deeper.

## Current

| Doc | What it covers |
|---|---|
| [15-release.md](15-release.md) | **Start here.** What v1 is, names and links, known issues, the promo kit, the plan for a cross-platform tag and for v2 (the first trained weights) |
| [14-glb-improvement.md](14-glb-improvement.md) | How v1 reached its numbers: assembly metric, repair, best-of-N, the adaptive generator, self-distillation data |
| [13-glb-code-track.md](13-glb-code-track.md) | The GLB benchmark: briefs, validator, models compared, prompt versions v1 to v3 |
| [developer-guide.md](developer-guide.md) | Every script and its flags |
| [architecture.svg](architecture.svg) | One-page diagram |

## Research history (archived)

Kept for reference. These describe earlier plans and experiments that led to the GLB code track; some steps were
never run, and items marked **VERIFY** were not confirmed.

| Doc | What it covers |
|---|---|
| [00-architecture.md](00-architecture.md) | The original overview: teacher-student distillation and the mesh-as-text track |
| [01-licensing.md](01-licensing.md) | Licence notes for the candidate teachers and bases (Spark Open was never used for v1) |
| [02-environment.md](02-environment.md) to [06-budget-and-risks.md](06-budget-and-risks.md) | The original distillation pipeline: environment, stages, training, export, budget |
| [07-local-glimmer.md](07-local-glimmer.md) | Running Muse Glimmer locally through Ollama |
| [08-mesh-track.md](08-mesh-track.md), [11-mesh-lora-e2e.md](11-mesh-lora-e2e.md), [12-proof-ladder.md](12-proof-ladder.md) | The mesh-as-text research track and its LoRA (the adapter in the Hugging Face repo) |
| [baseten-spark-open.md](baseten-spark-open.md) | Notes on the hosted Spark Open endpoint (not used for v1) |
| [HANDOVER.md](HANDOVER.md) | Working notes handed between sessions |
