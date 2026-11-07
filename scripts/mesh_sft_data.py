"""Build the SFT files for the mesh LoRA proof from data/mesh/objects.jsonl.

Prompt = system rules + caption; completion = the real mesh text. Conversational prompt/completion rows, which
TRL's SFTTrainer reads with loss on the completion only. The 30 captions used by the baseline stay out of training
(by source object, and every augmented copy of them), so before and after are measured on the same unseen set.

usage: python scripts/mesh_sft_data.py --objects data/mesh/objects.jsonl --holdout-run eval/mesh_baseline --out data/mesh/sft
Augmentation here is a minimal rotate/mirror; PRD 5's scripts/mesh_augment.py supersedes it once built.
"""
import argparse
import json
import random
import statistics
from pathlib import Path

from mesh_baseline import SYSTEM
from mesh_validate import BINS, validate

TOP = BINS - 1


def transform(text, quarter_turns=0, mirror=False):
    """Rotate about the vertical axis by quarter turns and/or mirror x, staying on the 0..63 integer grid.
    A mirror reverses triangle winding so faces keep pointing outward."""
    out = []
    for ln in text.splitlines():
        p = ln.split()
        if p[0] == "v":
            x, y, z = (int(v) for v in p[1:4])
            for _ in range(quarter_turns % 4):
                x, z = TOP - z, x
            if mirror:
                x = TOP - x
            out.append(f"v {x} {y} {z}")
        elif p[0] == "f" and mirror:
            out.append(f"f {p[1]} {p[3]} {p[2]}")
        else:
            out.append(ln)
    return "\n".join(out)


def variants(text, n, rng):
    """Up to n distinct orientations of one mesh; the original comes first."""
    combos = [(q, m) for m in (False, True) for q in range(4)]
    seen, out = set(), []
    for q, m in [combos[0]] + rng.sample(combos[1:], len(combos) - 1):
        t = transform(text, q, m)
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= n:
            break
    return out


def row(source_id, caption, text, tag):
    return {"id": f"{source_id}_{tag}", "source_id": source_id,
            "prompt": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": caption}],
            "completion": [{"role": "assistant", "content": text}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--objects", default="data/mesh/objects.jsonl")
    ap.add_argument("--holdout-run", default="eval/mesh_baseline", help="folder of baseline answers; their ids are never trained on")
    ap.add_argument("--out", default="data/mesh/sft")
    ap.add_argument("--max-tris", type=int, default=600, help="skip bigger objects: tokens scale with triangles (about 12 per triangle, measured)")
    ap.add_argument("--augment", type=int, default=8, help="max orientations per object (1 = originals only)")
    ap.add_argument("--val-fraction", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    rows = [json.loads(l) for l in Path(a.objects).read_text().splitlines() if l.strip()]
    held = {json.loads(f.read_text())["id"] for f in Path(a.holdout_run).glob("m*.json")} if a.holdout_run else set()
    pool = [r for r in rows if r["id"] not in held and r["tris"] <= a.max_tris]
    rng = random.Random(a.seed)
    ids = sorted(r["id"] for r in pool)
    rng.shuffle(ids)
    n_val = max(1, int(len(ids) * a.val_fraction)) if a.val_fraction > 0 else 0
    val_ids = set(ids[:n_val])

    train, val, dropped = [], [], 0
    for r in pool:
        for i, t in enumerate(variants(r["text"], a.augment, rng)):
            ok, _, _ = validate(t)
            if not ok:
                dropped += 1
                continue
            (val if r["id"] in val_ids else train).append(row(r["id"], r["caption"], t, f"v{i}"))
    rng.shuffle(train)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "train.jsonl").write_text("".join(json.dumps(x) + "\n" for x in train))
    (out / "val.jsonl").write_text("".join(json.dumps(x) + "\n" for x in val))
    (out / "split.json").write_text(json.dumps({"holdout_ids": sorted(held), "val_source_ids": sorted(val_ids),
                                                "train_source_ids": sorted(r["id"] for r in pool if r["id"] not in val_ids)}, indent=1))
    # MLX's trainer reads {"messages": [...]} rows from train.jsonl and valid.jsonl (use with --mask-prompt)
    mlx = out / "mlx"
    mlx.mkdir(exist_ok=True)
    for name, rs in (("train", train), ("valid", val)):
        (mlx / f"{name}.jsonl").write_text("".join(json.dumps({"messages": x["prompt"] + x["completion"]}) + "\n" for x in rs))
    chars = sorted(len(x["completion"][0]["content"]) for x in train)
    print(f"objects {len(rows)}, held out {len(held)}, over {a.max_tris} triangles skipped, trained on {len(pool) - len(val_ids)} + validated on {len(val_ids)} source objects")
    print(f"train rows {len(train)}, val rows {len(val)}, dropped {dropped}")
    if chars:
        print(f"completion chars median {statistics.median(chars):.0f}, p90 {chars[int(len(chars) * .9)]}, max {chars[-1]} (tokens about 0.65-0.75 per char, measured on 3 meshes with Glimmer's tokenizer; longest row about {chars[-1] * 0.75:.0f} tokens)")
    dup = len(pool) - len({r['caption'] for r in pool})
    print(f"{dup} objects share a caption with another object (name-derived captions); this adds label noise")


if __name__ == "__main__":
    main()
