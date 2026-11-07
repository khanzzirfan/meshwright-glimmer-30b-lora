"""Build the unseen_same_category dataset: train on short meshes, hold out short meshes of the same categories.

Reads corpus/short_objects.jsonl (97 short objects with rich captions) and corpus/short_split.json (train and holdout ids;
each held-out object has a sibling in train). Meshes longer than --max-lines are dropped (Glimmer reproduced up to about 270
lines exactly and failed past about 750). Train rows are a few orientations of each train object; valid.jsonl and targets.json
hold the held-out objects in their original orientation, so the loss on valid.jsonl is the loss on objects the model never
saw and proof_score.py scores what it generates for their captions. Also writes hf/train.jsonl and hf/val.jsonl in the
prompt/completion format that scripts/mesh_lora_hf.py reads.

usage: python scripts/proof_unseen.py --out-dir /tmp/proof-unseen
"""
import argparse
import json
import random
from pathlib import Path

from glb_to_text import sort_text
from mesh_baseline import SYSTEM
from mesh_sft_data import variants
from proof_data import _protected_folder



def chat(caption, text):
    return {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": caption},
                         {"role": "assistant", "content": text}]}


def load_split(path):
    split = json.loads(Path(path).read_text())
    return split["train"], split["holdout"]


def build(objects, train_ids, holdout_ids, orientations, seed=1, max_lines=None, sort=False):
    """(train_rows, valid_rows, targets) from the objects list; raises if an id is missing or in both sets."""
    by_id = {o["id"]: o for o in objects}
    if max_lines:
        keep = {i for i, o in by_id.items() if o["text"].count("\n") + 1 <= max_lines}
        train_ids = [i for i in train_ids if i in keep or i not in by_id]
        holdout_ids = [i for i in holdout_ids if i in keep or i not in by_id]
    missing = [i for i in list(train_ids) + list(holdout_ids) if i not in by_id]
    if missing:
        raise ValueError(f"unknown object ids: {', '.join(missing)}")
    overlap = set(train_ids) & set(holdout_ids)
    if overlap:
        raise ValueError(f"ids in both train and holdout: {', '.join(sorted(overlap))}")
    rng = random.Random(seed)
    canon = sort_text if sort else (lambda t: t)  # sorted vertices/faces, re-applied after each rotation
    train = [chat(by_id[i]["caption"], canon(t)) for i in train_ids for t in variants(by_id[i]["text"], orientations, rng)]
    valid = [chat(by_id[i]["caption"], canon(by_id[i]["text"])) for i in holdout_ids]
    targets = [{"id": i, "caption": by_id[i]["caption"], "mesh": canon(by_id[i]["text"])} for i in holdout_ids]
    return train, valid, targets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--objects", default="corpus/short_objects.jsonl")
    ap.add_argument("--split", default="corpus/short_split.json")
    ap.add_argument("--max-lines", type=int, default=300)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--sort", action="store_true", help="canonical order: vertices by z,y,x, faces by lowest index (applied after rotations)")
    ap.add_argument("--orientations", type=int, default=4, help="rotated/mirrored copies per training object")
    a = ap.parse_args()
    blocked = _protected_folder(a.out_dir)
    if blocked:
        raise SystemExit(f"refusing to write inside {blocked}/: choose a work folder such as /tmp/proof-unseen")
    objects = [json.loads(l) for l in Path(a.objects).read_text().splitlines() if l.strip()]
    train_ids, holdout_ids = load_split(a.split)
    train, valid, targets = build(objects, train_ids, holdout_ids, a.orientations, max_lines=a.max_lines, sort=a.sort)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "train.jsonl").write_text("".join(json.dumps(r) + "\n" for r in train))
    (out / "valid.jsonl").write_text("".join(json.dumps(r) + "\n" for r in valid))
    (out / "targets.json").write_text(json.dumps(targets, indent=1) + "\n")
    hf = out / "hf"
    hf.mkdir(exist_ok=True)
    for name, rows in (("train", train), ("val", valid)):
        lines = []
        for r in rows:
            m = r["messages"]
            lines.append(json.dumps({"prompt": m[:2], "completion": m[2:]}) + "\n")
        (hf / f"{name}.jsonl").write_text("".join(lines))
    print(f"{len(train)} train rows; {len(valid)} held-out objects in {out}")


if __name__ == "__main__":
    main()
