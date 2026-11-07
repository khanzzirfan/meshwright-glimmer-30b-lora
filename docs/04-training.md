# 04. Training

## Base model
`Qwen/Qwen3.5-4B` (Apache 2.0). ccore used this same base, with a full fine-tune followed by a short LoRA stage over about 60 hours; their hyperparameters are not published.

## Recommended path: LoRA first, full fine-tune only if needed
LoRA is cheaper, safer, and enough to teach format and library habits. Try it first on a 500-1,000 example pilot.

| Setting | LoRA start | Full fine-tune start |
|---|---|---|
| Precision | bf16 | bf16 |
| Learning rate | 1e-4 | 1e-5 |
| LoRA rank / alpha | 64 / 128, all linear layers | n/a |
| Epochs | 2-3 | 2 |
| Max sequence length | 12,288 (raise if many examples truncate) | same |
| Per-device batch | 1, grad-accum 16 | 1, grad-accum 16 |
| Scheduler | cosine, 3% warmup | same |
| Gradient checkpointing | on | on |

These are common defaults, not tuned values. Treat the first run as a measurement.

## Hardware and time (**VERIFY** on a pilot)
- 1x H100 80 GB: LoRA on ~4k examples of ~8k tokens each is plausibly a few hours per epoch. Full fine-tune is heavier on memory (optimizer state for 4B parameters in bf16 plus fp32 Adam is about 50-60 GB with checkpointing) but fits on 80 GB.
- Measure tokens/second in the first 20 steps and extrapolate before committing to a long run.

## Run

```bash
python scripts/train_sft.py --data data/sft --out out/lora --mode lora
python scripts/train_sft.py --data data/sft --out out/full --mode full --lr 1e-5
```

The script uses TRL `SFTTrainer` with `peft`. It logs to `out/<name>/trainer_log` and saves a checkpoint each epoch.

## What to watch
- **Truncation:** if more than ~5% of examples exceed `--max-len`, raise it or filter long ones; truncated code teaches the model to stop mid-file.
- **Loss on completion only:** confirm in the first batch that prompt tokens are masked (TRL prints no warning; check `labels` yourself once).
- **Overfitting:** val loss rising while train loss falls after epoch 1-2 on 4k examples is normal to watch for. Pick the checkpoint with the best **render pass rate** (Stage 7), not the lowest loss.
- **Duplicate-variable bug:** ccore reports duplicate `const` names as the main failure. Your validator rejects those examples from training (a redeclaration is a JS error), which should help.

## Optional second stage
After SFT, run rejection sampling: generate 4 answers per training brief with the student, keep the ones that pass validation, and fine-tune again on them. This is cheap because validation is automatic. Do it only after the first eval shows where the student fails.
