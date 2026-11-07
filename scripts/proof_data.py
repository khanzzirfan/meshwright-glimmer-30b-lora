"""Pick training meshes and write an MLX chat dataset for the memorisation test.

The rows come from the mesh SFT file (``data/mesh/sft/train.jsonl``): each row has
``id``, ``source_id``, ``prompt`` = [system, user] and ``completion`` = [assistant].
``pick`` chooses rows by completion length; ``write_mlx`` writes the chat files MLX's
trainer reads (``train.jsonl`` repeated, ``valid.jsonl`` once) plus ``targets.json``
so the generated meshes can be scored against the exact training text.

usage: python scripts/proof_data.py --sft data/mesh/sft/train.jsonl --pick median --n 1 --repeat 1 --out-dir /tmp/proof-one
"""
import argparse
import json
import sys
from pathlib import Path

MODES = ("median", "smallest", "spread")
PROTECTED = ("data", "eval", "out")


def completion_text(row):
    """The assistant mesh text, which is the target for the memorisation test."""
    for message in row["completion"]:
        if message["role"] == "assistant":
            return message["content"]
    raise ValueError(f"row {row.get('id')!r} has no assistant completion")


def caption_text(row):
    """The user caption that the model is asked to reproduce."""
    for message in row["prompt"]:
        if message["role"] == "user":
            return message["content"]
    raise ValueError(f"row {row.get('id')!r} has no user prompt")


def load_rows(path):
    """Read an SFT JSONL file into a list of row dictionaries."""
    text = Path(path).read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _by_length(rows):
    return sorted(rows, key=lambda row: (len(completion_text(row)), row.get("id", "")))


def _even_indices(total, n):
    """n distinct indices spread evenly over 0..total-1, inclusive."""
    if n >= total:
        return list(range(total))
    if n == 1:
        return [(total - 1) // 2]
    picked = []
    for i in range(n):
        index = round(i * (total - 1) / (n - 1))
        if index not in picked:
            picked.append(index)
    candidate = 0
    while len(picked) < n:
        if candidate not in picked:
            picked.append(candidate)
        candidate += 1
    return sorted(picked)


def pick(rows, mode, n):
    """Pick n rows from rows.

    median: the n rows around the median completion length.
    smallest: the n shortest completions.
    spread: n rows, at most one per source_id, evenly spread by completion length.
    """
    if mode not in MODES:
        raise ValueError(f"unknown pick mode {mode!r}; choose one of {', '.join(MODES)}")
    if n < 1:
        raise ValueError("n must be at least 1")
    ordered = _by_length(rows)
    if not ordered:
        return []
    if mode == "smallest":
        return ordered[:n]
    if mode == "median":
        if n >= len(ordered):
            return ordered
        start = max(0, min((len(ordered) - 1) // 2 - (n // 2), len(ordered) - n))
        return ordered[start:start + n]

    groups = {}
    for row in ordered:
        groups.setdefault(row["source_id"], []).append(row)
    candidates = []
    for group in groups.values():
        candidates.append(group[(len(group) - 1) // 2])
    candidates = _by_length(candidates)
    return [candidates[i] for i in _even_indices(len(candidates), n)]


def write_mlx(rows, out_dir, repeat=1):
    """Write train.jsonl, valid.jsonl and targets.json for MLX.

    Both chat files contain the same rows (this is a memorisation test), with train
    repeated ``repeat`` times and valid once.
    """
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    def chat_lines(source):
        lines = []
        for _ in range(repeat if source == "train" else 1):
            for row in rows:
                messages = list(row["prompt"]) + list(row["completion"])
                lines.append(json.dumps({"messages": messages}) + "\n")
        return "".join(lines)

    (out / "train.jsonl").write_text(chat_lines("train"))
    (out / "valid.jsonl").write_text(chat_lines("valid"))

    targets = [{"id": row["id"], "caption": caption_text(row), "mesh": completion_text(row)}
               for row in rows]
    (out / "targets.json").write_text(json.dumps(targets, indent=1) + "\n")
    return {"rows": len(rows), "train": len(rows) * repeat, "valid": len(rows)}


def _protected_folder(out_dir):
    """Name of the protected repo folder containing out_dir, or None."""
    root = Path(__file__).resolve().parent.parent
    target = Path(out_dir).resolve()
    for name in PROTECTED:
        base = (root / name).resolve()
        if target == base or base in target.parents:
            return name
    return None


def main():
    ap = argparse.ArgumentParser(description="Pick mesh rows and write an MLX memorisation dataset.")
    ap.add_argument("--sft", required=True, help="SFT JSONL with prompt/completion rows (read only)")
    ap.add_argument("--pick", choices=MODES, default="median")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--repeat", type=int, default=1, help="how many times to repeat each row in train.jsonl")
    ap.add_argument("--out-dir", required=True, help="folder for train.jsonl, valid.jsonl and targets.json")
    a = ap.parse_args()

    blocked = _protected_folder(a.out_dir)
    if blocked:
        print(f"refusing to write inside {blocked}/: choose a work folder such as /tmp/proof", file=sys.stderr)
        raise SystemExit(2)

    rows = load_rows(a.sft)
    chosen = pick(rows, a.pick, a.n)
    if not chosen:
        print(f"no rows in {a.sft}", file=sys.stderr)
        raise SystemExit(1)
    counts = write_mlx(chosen, a.out_dir, a.repeat)
    print(f"picked {counts['rows']} row(s) with {a.pick}; wrote {counts['train']} train and {counts['valid']} valid to {a.out_dir}")


if __name__ == "__main__":
    main()
