# 06. Budget, risks, open questions

## Rough cost (all **VERIFY**; fill in real prices)

| Item | Quantity | Notes |
|---|---|---|
| Brief generation | ~6k briefs, small output | negligible next to the teacher |
| Teacher answers | ~6k calls x 6-10k output tokens = ~36-60M tokens | the main cost; get Baseten's per-token price for Spark Open and multiply |
| Validation | local CPU | free, about 3-6 s per scene, parallelise 4-6 browsers |
| Training | a few hours to a day on one H100 | rent by the hour |
| Optional Spark image scoring | ~4k image calls | skip unless needed |

Do the pilot first: 200 briefs gives real tokens per answer, pass rate, and cost per kept example. Scale only after that.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Licence: derivatives of Spark Open outputs | cannot publish, or must carry terms | [01-licensing.md](01-licensing.md); fall back to Glimmer |
| Teacher returns no reasoning | no thinking traces | train answer-only (`--no-reasoning`); the student gets shorter outputs |
| Low pass rate | few examples survive | tighten the system prompt; add a repair pass (send the console error back to the teacher once) |
| "Renders but wrong" scenes | model learns poor composition | Stage 3b screenshot scoring |
| Prompt monoculture | student only handles briefs like the training ones | vary domains and phrasing; include terse, vague and non-English briefs if you want them supported |
| SwiftShader too slow | validation takes hours | lower the wait time, parallelise, or validate on a Linux box with a GPU |
| Qwen3.5 tooling is new | converter or trainer bugs | pin the versions from the model card; test on the pilot |
| Overfit to one Three.js version | breaks on newer releases | accepted: pin 0.160.0 and say so |

## Open questions
1. What is Spark Open's per-token price on Baseten? (Slug and reasoning behaviour: see [baseten-spark-open.md](baseten-spark-open.md); it does return reasoning, scene-sized token use is not measured yet.)
2. Is a student trained on Spark Open outputs a derivative, and under what terms?
3. Do you want the student to also export GLB (the other ccore model)? That adds a GLTFExporter dependency and a different system prompt; it is a second dataset, not a flag.
4. Is the goal a general Three.js coder, or a director that emits your engine's timeline JSON (`model3d` layer)? The second is easier to validate with a schema, and fits the product better. The same pipeline works: swap the system prompt, the validator, and the briefs.
5. Where will this run: private only, or published to Hugging Face?
