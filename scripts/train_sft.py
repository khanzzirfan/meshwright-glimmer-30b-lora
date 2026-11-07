"""SFT of Qwen3.5-4B on the validated scenes. LoRA by default, full fine-tune with --mode full."""
import argparse

import torch
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/sft")
    ap.add_argument("--out", default="out/lora")
    ap.add_argument("--base", default="Qwen/Qwen3.5-4B")
    ap.add_argument("--mode", choices=["lora", "full"], default="lora")
    ap.add_argument("--lr", type=float, default=None)
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--max-len", type=int, default=12288)
    ap.add_argument("--rank", type=int, default=64)
    ap.add_argument("--grad-accum", type=int, default=16)
    a = ap.parse_args()
    lr = a.lr or (1e-4 if a.mode == "lora" else 1e-5)

    ds = load_dataset("json", data_files={"train": f"{a.data}/train.jsonl", "validation": f"{a.data}/val.jsonl"})
    ds = ds.remove_columns([c for c in ("id", "level", "domain") if c in ds["train"].column_names])

    tok = AutoTokenizer.from_pretrained(a.base)
    # VERIFY: Qwen3.5 ships a vision tower; if this class refuses the checkpoint, load the text model class the card names
    model = AutoModelForCausalLM.from_pretrained(a.base, dtype=torch.bfloat16)

    cfg = SFTConfig(
        output_dir=a.out, learning_rate=lr, num_train_epochs=a.epochs, bf16=True,
        per_device_train_batch_size=1, per_device_eval_batch_size=1,
        gradient_accumulation_steps=a.grad_accum, gradient_checkpointing=True,
        lr_scheduler_type="cosine", warmup_ratio=0.03, max_length=a.max_len,
        logging_steps=5, eval_strategy="epoch", save_strategy="epoch", report_to="none",
    )  # prompt/completion data: loss is on the completion only
    peft = LoraConfig(r=a.rank, lora_alpha=a.rank * 2, target_modules="all-linear", task_type="CAUSAL_LM") if a.mode == "lora" else None
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds["train"], eval_dataset=ds["validation"],
                         processing_class=tok, peft_config=peft)
    trainer.train()
    # final weights at the root of --out (export_gguf.sh reads them there); per-epoch
    # checkpoints stay in checkpoint-*: keep the best by render pass rate, not loss
    trainer.save_model(a.out)
    tok.save_pretrained(a.out)


if __name__ == "__main__":
    main()
