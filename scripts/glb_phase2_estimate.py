"""Estimate the phase 2 LoRA cost from the built dataset (docs/14 section 8).

Reads the train/val JSONL that ccore_prep.py writes, counts rows and completion characters, and
projects steps, hours and cost from the training shape. The seconds-per-step number is not guessed:
run the 20-step smoke first (`mesh_lora_hf.py --max-steps 20`), time it and pass --sec-per-step.
Without --sec-per-step the script prints 'sec-per-step not measured: run the 20-step smoke first'
and no cost, so no unmeasured figure is ever reported. It only reads --data and writes nothing.
"""
import argparse
import json
import math
from pathlib import Path

NOT_MEASURED = "sec-per-step not measured: run the 20-step smoke first"


def read_jsonl(path):
    """Parse a JSONL file into a list, or [] when it does not exist."""
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_split(data_dir, name):
    return read_jsonl(Path(data_dir) / f"{name}.jsonl")


def completion_chars(rows):
    """Sum of the completion content lengths over the rows."""
    total = 0
    for row in rows:
        completion = row.get("completion") or []
        total += len(completion[0].get("content") or "") if completion else 0
    return total


def steps_per_epoch(train_rows, batch, grad_accum):
    """Optimiser steps in one epoch at this effective batch size (0 for an empty train split)."""
    per_step = max(1, batch) * max(1, grad_accum)
    return math.ceil(train_rows / per_step) if train_rows else 0


def estimate(data_dir, epochs=2, grad_accum=8, batch=1, chars_per_token=3.3,
             sec_per_step=None, price_per_hour=None):
    """The dataset and training-shape numbers behind the printed estimate.

    hours and cost are None until both --sec-per-step and --price-per-hour are given.
    """
    train = load_split(data_dir, "train")
    val = load_split(data_dir, "val")
    chars = completion_chars(train) + completion_chars(val)
    per_epoch = steps_per_epoch(len(train), batch, grad_accum)
    total_steps = round(per_epoch * epochs)
    hours = total_steps * sec_per_step / 3600 if sec_per_step is not None else None
    cost = hours * price_per_hour if (hours is not None and price_per_hour is not None) else None
    return {
        "data": str(data_dir),
        "train_rows": len(train),
        "val_rows": len(val),
        "chars": chars,
        "tokens": round(chars / chars_per_token) if chars_per_token else 0,
        "chars_per_token": chars_per_token,
        "epochs": epochs,
        "batch": batch,
        "grad_accum": grad_accum,
        "steps_per_epoch": per_epoch,
        "total_steps": total_steps,
        "hours": hours,
        "cost": cost,
    }


def render(info):
    """The printable lines: measurements always, cost only once seconds per step is known."""
    lines = [
        f"data: {info['data']}",
        f"rows: {info['train_rows']} train, {info['val_rows']} val",
        f"completion chars: {info['chars']}",
        f"estimated tokens: {info['tokens']} (estimate, chars/token = {info['chars_per_token']:g})",
        f"epochs: {info['epochs']:g}, batch {info['batch']} x grad-accum {info['grad_accum']}",
        f"steps per epoch: {info['steps_per_epoch']}",
        f"total steps: {info['total_steps']}",
    ]
    if info["hours"] is None:
        lines.append(NOT_MEASURED)
    else:
        lines.append(f"hours: {info['hours']:.2f}")
        lines.append(f"cost: ${info['cost']:.2f}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="Estimate the phase 2 LoRA cost from the dataset (docs/14 section 8).")
    ap.add_argument("--data", required=True, help="phase 2 directory with train.jsonl and val.jsonl")
    ap.add_argument("--sec-per-step", type=float, default=None, help="measured seconds per optimiser step (from the 20-step smoke)")
    ap.add_argument("--price-per-hour", type=float, default=None, help="rented-GPU price per hour")
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--chars-per-token", type=float, default=3.3)
    a = ap.parse_args(argv)

    if (a.sec_per_step is None) != (a.price_per_hour is None):
        ap.error("--sec-per-step and --price-per-hour are given together (the smoke run measures seconds per step)")

    info = estimate(a.data, epochs=a.epochs, grad_accum=a.grad_accum, batch=a.batch,
                    chars_per_token=a.chars_per_token, sec_per_step=a.sec_per_step,
                    price_per_hour=a.price_per_hour)
    print("\n".join(render(info)))


if __name__ == "__main__":
    main()
