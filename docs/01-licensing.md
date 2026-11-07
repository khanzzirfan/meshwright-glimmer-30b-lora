# 01. Licensing: do this before you generate anything

## Why it matters
You are training a student model on a teacher's outputs. Whether you may do that, and what
terms the student inherits, depends on the teacher's license. The cheap answer now is better
than finding out after a 60-hour training run.

## What I found (secondary sources only, not the license text)

| Model | License | What the articles say |
|---|---|---|
| Muse Spark Open | Muse Model License | Models trained or distilled on its outputs count as **derivatives**; attribution credit required; clause for hosted-API businesses above a revenue threshold (reported as $20M, sources disagree on how it is measured). Meta claims no ownership of outputs. |
| Muse Glimmer 30B | Apache 2.0 | Fine-tuning and derivatives allowed with the normal notice terms. Weaker teacher, but the cleanest license. |
| Muse Spark via the Meta API | Meta API terms | The "contributor" tier is cheaper in exchange for Meta training on your inputs and outputs. I found nothing that clearly allows distilling API outputs. **Do not use it as the teacher.** |
| Qwen3.5-4B (student base) | Apache 2.0 | No restriction on fine-tuning. |
| ccore dataset | MIT | Usable as extra data or as an eval reference. |

Sources: [buildmvpfast](https://www.buildmvpfast.com/blog/meta-muse-spark-open-license-self-host-2026),
[The New Stack](https://thenewstack.io/meta-muse-spark-open/),
[Vercel contributor tier](https://vercel.com/ai-gateway/models/muse-spark-1.2-contributor).

## Checklist (all **VERIFY**)

- [ ] Read the license file on the Spark Open model card: https://huggingface.co/meta-models/Muse-Spark-Open-816B-A42B
- [ ] Is a model trained on its outputs a "derivative"? If yes, what must the derivative's license say?
- [ ] Exact attribution wording (for the README and model card of the student).
- [ ] Does the revenue clause apply to you? (You would be hosting a student model, not Spark.)
- [ ] Baseten's own terms for the hosted Spark Open endpoint: any extra limits on using outputs for training?
- [ ] Is the hackathon dataset or model public? If you only use the student privately, the risk is smaller, but the license still applies.

## Decision rule
- All boxes clean: use Spark Open as teacher, publish with the required attribution.
- Derivative terms are acceptable but unclear: use Spark Open, keep the student private, and ask Meta.
- Blocked: use Muse Glimmer (Apache 2.0) as the teacher and accept weaker data, or use an Apache/MIT teacher.

## If you publish the student
Put in the model card: base model (Qwen3.5-4B, Apache 2.0), teacher (Muse Spark Open, with whatever credit line the license requires), dataset license, and that it is an independent fine-tune.
