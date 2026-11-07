"""LoRA on Muse Glimmer with TRL + peft, for a rented GPU box (RunPod, AWS). The Mac path is scripts/mesh_lora_mlx.sh.

Reads data/mesh/sft/train.jsonl and val.jsonl (conversational prompt/completion, loss on the completion only).
Checked on the pod (transformers 5.22): Glimmer is NOT in the causal-LM auto mapping, so it loads with AutoModelForMultimodalLM
(MuseGlimmerForConditionalGeneration); its language linears all live under `model.language_model`, which the LoRA targets by regex.
`--dry-run` checks the data offline and exits before any heavy import.
"""
import argparse
import json
from pathlib import Path


def check_data(d):
    for name in ("train", "val"):
        rows = [json.loads(l) for l in (Path(d) / f"{name}.jsonl").read_text().splitlines() if l.strip()]
        assert rows and all(set(r) >= {"prompt", "completion"} for r in rows), f"{name}.jsonl has bad rows"
        chars = sorted(len(r["completion"][0]["content"]) for r in rows)
        print(f"{name}: {len(rows)} rows, completion chars median {chars[len(chars) // 2]}, max {chars[-1]} (tokens about 0.7 per char)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/mesh/sft")
    ap.add_argument("--out", default="out/mesh-lora-hf")
    ap.add_argument("--base", default="meta-models/Muse-Glimmer-30B")
    ap.add_argument("--quant", choices=["none", "4bit"], default="4bit", help="4bit = QLoRA, fits a 24-48 GB card; none = BF16 LoRA, needs 80 GB")
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--max-steps", type=int, default=-1, help="set about 20 for a smoke run")
    ap.add_argument("--max-len", type=int, default=9728)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--eval-steps", type=int, default=20)
    ap.add_argument("--save-epochs", action="store_true", help="save an adapter checkpoint after every epoch, to score mid-run and stop early")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    check_data(a.data)
    if a.dry_run:
        return

    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from transformers import AutoModelForMultimodalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    ds = load_dataset("json", data_files={"train": f"{a.data}/train.jsonl", "validation": f"{a.data}/val.jsonl"})
    ds = ds.remove_columns([c for c in ("id", "source_id") if c in ds["train"].column_names])
    tok = AutoTokenizer.from_pretrained(a.base)
    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16) if a.quant == "4bit" else None
    model = AutoModelForMultimodalLM.from_pretrained(a.base, dtype=torch.bfloat16, quantization_config=q, device_map="auto")
    # regex: only the text decoder's attention and MLP linears; the 1.8B vision tower stays frozen and untouched
    peft = LoraConfig(r=a.rank, lora_alpha=a.rank * 2, task_type="CAUSAL_LM",
                      target_modules=r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)")
    cfg = SFTConfig(output_dir=a.out, learning_rate=a.lr, num_train_epochs=a.epochs, max_steps=a.max_steps, bf16=True,
                    per_device_train_batch_size=1, per_device_eval_batch_size=1, gradient_accumulation_steps=a.grad_accum,
                    gradient_checkpointing=True, lr_scheduler_type="cosine", warmup_steps=0.05, max_length=a.max_len,
                    logging_steps=2, eval_strategy="steps", eval_steps=a.eval_steps,
                    save_strategy="epoch" if a.save_epochs else "no", save_only_model=True, report_to="none")
    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds["train"], eval_dataset=ds["validation"], processing_class=tok, peft_config=peft)
    before = trainer.evaluate()["eval_loss"]
    trainer.train()
    after = trainer.evaluate()["eval_loss"]
    trainer.save_model(a.out)
    tok.save_pretrained(a.out)
    Path(a.out, "loss.json").write_text(json.dumps({"eval_loss_before": before, "eval_loss_after": after,
                                                    "log": trainer.state.log_history}, indent=1))
    print(f"eval loss {before:.3f} -> {after:.3f}")


if __name__ == "__main__":
    main()
