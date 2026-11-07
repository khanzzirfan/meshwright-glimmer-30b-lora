# Muse Spark Open on Baseten (teacher setup)

Facts below come from pixitween-director's `docs/baseten-spark-open.md` and its smoke test (last run 29 Oct 2026: a plain call took 1.7 s and a tool call 2.7 s). They were **not** re-measured for scene generation yet; `scripts/baseten_smoke.py` does that.

## Setup
1. Copy your `.env` into this folder (it is gitignored). It needs `BASETEN_API_KEY`. Compare with `.env.example`: the other names are `BASETEN_BASE_URL`, `TEACHER_MODEL`, `BRIEF_MODEL`.
2. Never paste the key into chat, an issue or a commit. If it leaks, revoke it in the Baseten dashboard.
3. Smoke test (dry run by default, spends credit only with `--yes`):

```bash
cd /Users/irfankhan/Documents/code/trolio/muse-threejs
.venv/bin/python scripts/baseten_smoke.py          # prints the plan and estimate, calls nothing
.venv/bin/python scripts/baseten_smoke.py --yes    # a tiny call, then one lighthouse scene
```

It prints seconds, token counts, tokens per second, whether reasoning came back, and whether the answer has the html fence, and saves the scene to `data/baseten_smoke/scene.json`.

## The facts that are easy to get wrong
- **Base URL:** `https://inference.baseten.co/v1` (OpenAI-compatible, path `/chat/completions`).
- **Model name:** exactly `meta-models/muse-spark-open-1026`. The Baseten docs say `meta-models/muse-spark-open`; the hackathon key does not work with that.
- **It always reasons.** The reply carries `reasoning_content` and the answer in `content`. `teacher_generate.py` already stores both (`reasoning` and `content`). Reasoning tokens count as output tokens: a one-word answer used 68 and a simple tool call 587. A full scene could use several times its visible length, so `--max-tokens 12000` may truncate hard scenes (the validator rejects those as `truncated`). Raise it if the smoke test shows reasoning eating the budget.
- **Limits and price:** the hackathon key has $100 of credit and up to 2M tokens per minute. No per-token price is published for the key, so spend is only known after a run. Measure tokens per scene with the smoke test, then multiply.

## Using it as the teacher

```bash
.venv/bin/python scripts/teacher_generate.py --briefs data/briefs.jsonl --out data/raw_spark \
  --concurrency 4 --max-tokens 16000 --token-budget 500000          # about 30-50 scenes, a capped first run
node scripts/validate_scenes.mjs --raw data/raw_spark --scenes data/scenes_spark --shots data/shots_spark --report data/validation_spark.jsonl
```

`--token-budget N` stops starting new calls once N prompt+completion tokens are used (calls already in flight finish). Use a separate output folder from the Glimmer run so the two teachers can be compared on the same briefs.

## Before a large run
- **Credits are shared with the hackathon app.** The same key serves the live demo (submission is due 4 Nov 21:00 ET). A corpus run of thousands of scenes could use up the credit the demo needs. Use a separate key or keep the cap small until the submission is in.
- **Licence:** whether a model trained on Spark Open outputs is a derivative, and on what terms, is still unchecked. See [01-licensing.md](01-licensing.md). Local Glimmer (Apache 2.0) avoids the question.
- **Glimmer vs Spark Open:** run the same 30-50 briefs through both and compare validator pass rate and screenshots before deciding the teacher for the full dataset.

## Measured: 30 briefs, 3 Nov 2026
Same first 30 briefs as the Glimmer pilot; Spark Open `meta-models/muse-spark-open-1026`, concurrency 4, `--max-tokens 16000`, no retries needed (0 failed calls).

| | Spark Open | Glimmer (local, no thinking) |
|---|---|---|
| Scenes compared (briefs both finished) | 21 | 21 |
| Passed the validator | 16 (76%) | 14 (67%) |
| Failures | 5 truncated | 6 static, 1 blank |
| Median completion tokens | 13,684 (p90 and max 16,000) | 2,149 |
| Time | 5 min 47 s for 30 scenes, about 11.6 s each at concurrency 4 | median 76 s each, one at a time |
| Tokens used | 393,772 for the 30 (prompt + completion) | not applicable |

- **All 30 Spark scenes:** 19 passed, 11 hit the 16,000-token cap (`truncated`, no html finished). They are spread over levels 1-9, so it is reasoning length, not scene size: the passing scenes' median content is about 21k characters (roughly 6-7k tokens) and reasoning takes about as much again. Raise `--max-tokens` to 24000 or more, or accept about a third lost.
- **Quality:** Spark's scenes are much richer (e.g. brief b00026, a reading nook: Spark has bookshelf, window, plant, cat, captions and interaction; Glimmer has an armchair, table and lamp). Screenshots: `data/shots_spark/` vs `data/shots/`.
- **Validator caveat:** several Glimmer "static" rejections have tiny but non-zero frame differences (for example b00026, diff 0.0018, whose lamp sways gently), so `STATIC_MIN_DIFF` (0.002) is probably rejecting subtle animation. Look at those shots before trusting the Glimmer pass rate; the real gap may be smaller or larger.
- **Cost:** not priced. 394k tokens is the only measured spend; multiply by Baseten's rate once it is known.

### Rerun of the 11 truncated briefs at `--max-tokens 32000`
- 0 failed calls, 183,916 tokens, 2 min 49 s. Median 14,328 completion tokens (so most truncated scenes needed 14-30k, just over the old cap).
- Result: 8 of 11 passed, 1 `js_error` (also static), 1 still `truncated` at 32,000 (b00045: reasoning ran away).
- **All 30 briefs now: 28 passed (93.3%)**, 1 js_error + static, 1 truncated. Total measured spend for both runs: 577,688 tokens (the first 30-brief run plus this rerun). The first-run truncated files are kept in `data/raw_spark_truncated16k/`.
- Use `--max-tokens 32000` for Spark Open. A one-in-30 runaway is cheap to drop: it is rejected as `truncated`.
