# 03. Pipeline walkthrough

> **Archived.** Part of the research history behind Meshwright v1; kept for reference and not current. See [15-release.md](15-release.md) for the release and [README.md](README.md) for all docs.

## Stage 1: briefs (`gen_briefs.py`)
A brief is one short scene request, e.g. "A lantern-lit Japanese tea house at dusk with drifting petals".
Diversity here sets the ceiling of the student.

- Grid: `domain` x `level` (1-10) x `style`.
  - Domains: architecture, nature, vehicles, characters, interiors, props, sci-fi, historical landmarks, abstract/particle, games/voxel, UI-in-3D, data visualisation.
  - Levels: 1 = one primitive with a light; 5 = a small composed scene with animation; 10 = a large scene with several animated systems and camera controls.
  - Styles: low-poly, voxel, stylised, realistic-ish, toon.
- The brief writer is asked for JSON lines with `title`, `brief`, `domain`, `level`, `style`. Duplicates are removed by normalised title and by embedding-free near match (lowercase word-set Jaccard > 0.8).
- Hold out 5-10% as an eval split (`--eval-fraction`). Never train on those.
- Target: 5,000-6,000 briefs if you expect roughly 60-70% to survive validation (**VERIFY** actual yield on a 200-brief pilot).
- Also add ccore's prompts as eval-only if you want a cross-check against their model.

## Stage 2: teacher answers (`teacher_generate.py`)
- Sends `prompts/system.txt` plus the brief to the teacher through an OpenAI-compatible endpoint.
- Saves `data/raw/<id>.json` with `brief`, `content`, `reasoning` (if the endpoint returns it), `usage`, `model`, timestamp.
- Resumable: skips ids that already have a file. Retries 429/5xx with backoff.
- `--concurrency` defaults to 8. Watch Baseten rate limits and your spend as you raise it.
- Reasoning text: some providers return it in `reasoning_content`, others inline in `<think>` tags, others hide it. The script stores whichever it finds. Spark Open on Baseten returns `reasoning_content` (per an earlier smoke test); run `scripts/baseten_smoke.py` to confirm for scenes before the big run. If there is no reasoning, train on the answer only (see Stage 4 options).
- Settings to start from: temperature 0.7, top_p 0.95, `max_tokens` 12000. Scenes at level 8-10 can be long; truncated outputs are rejected in Stage 3.

## Stage 3: validate (`validate_scenes.mjs`)
For each raw answer:
1. Extract the HTML: the first fenced ```html block, else the first `<!DOCTYPE html>`...`</html>` span. No HTML found: reject (`no_html`).
2. Static rules: only the allowed Three.js import; no `examples/jsm` or `OrbitControls` import; no other external `src`/`import` URL; no `eval`; must contain `requestAnimationFrame` or `setAnimationLoop`. Failure: `bad_import`, `external_dep`, `no_loop`.
3. Load in headless Chromium with the CDN URL intercepted to the local `three@0.160.0`. Collect `pageerror` and console `error`. Any error: reject (`js_error`).
4. Wait 2.5 s, screenshot twice 600 ms apart.
5. Pixel checks (PNG decoded with `pngjs`): reject if almost one colour (`blank`) or if the two frames are identical and the brief asked for animation (`static`). Both thresholds are in the script header; tune them after looking at real screenshots.
6. Write `data/scenes/<id>.html`, `data/shots/<id>.png`, and one line to `data/validation.jsonl` with `{id, ok, reasons, stats}`.

Optional Stage 3b (not scripted yet): ask Spark to look at the screenshot and the brief and score 1-5 for match. Keep only 4+. It costs one image call per example and filters "renders but is wrong" cases. Do it only if the pilot shows many such cases.

## Stage 4: dataset (`build_dataset.py`)
Joins briefs, raw answers and validation, keeps `ok` rows, and writes prompt/completion JSONL:

```json
{"prompt":[{"role":"system","content":"..."},{"role":"user","content":"..."}],
 "completion":[{"role":"assistant","content":"<think>\n...\n</think>\n\n```html\n...\n```"}]}
```

- Loss is computed on the completion only (TRL does this for prompt/completion data).
- `--no-reasoning` drops the `<think>` part. Use it if the teacher gave no reasoning or you want shorter outputs.
- Split: validation 5% of kept rows, stratified by level.
- Check the Qwen3.5 chat template on the GPU box (`tokenizer.apply_chat_template`) to confirm how thinking is wrapped. **VERIFY**; the script writes the `<think>` form into the content on the assumption that matches the template.
- Prints counts by level and domain so you can spot holes.

## Stages 5-7
See [04-training.md](04-training.md) and [05-export-serve-eval.md](05-export-serve-eval.md).
