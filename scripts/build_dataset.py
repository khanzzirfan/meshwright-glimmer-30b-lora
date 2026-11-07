"""Join briefs + raw answers + validation into prompt/completion JSONL for SFT."""
import argparse
import collections
import json
import random
from pathlib import Path

from tags import THINK_CLOSE, THINK_OPEN


def load(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def system_prompt():
    # Imported lazily so `import build_dataset` stays free of openai/dotenv side effects.
    from common import system_prompt as _system_prompt

    return _system_prompt()


def build(briefs, raw_dir, report, out_dir, no_reasoning=False, val_fraction=0.05, seed=1):
    briefs_map = {b["id"]: b for b in load(briefs)}
    ok = {r["id"] for r in load(report) if r["ok"]}
    system = system_prompt()
    rows = []
    for i in sorted(ok & briefs_map.keys()):
        raw = json.loads((Path(raw_dir) / f"{i}.json").read_text())
        answer = raw["content"]
        if raw.get("reasoning") and not no_reasoning:
            answer = f"{THINK_OPEN}\n{raw['reasoning'].strip()}\n{THINK_CLOSE}\n\n{answer}"
        rows.append({
            "id": i, "level": briefs_map[i]["level"], "domain": briefs_map[i]["domain"],
            "prompt": [{"role": "system", "content": system}, {"role": "user", "content": briefs_map[i]["brief"]}],
            "completion": [{"role": "assistant", "content": answer}],
        })

    rng = random.Random(seed)
    by_level = collections.defaultdict(list)
    for r in rows:
        by_level[r["level"]].append(r)
    train, val = [], []
    for level_rows in by_level.values():  # stratified by level
        rng.shuffle(level_rows)
        k = max(1, int(len(level_rows) * val_fraction)) if len(level_rows) > 1 else 0
        val += level_rows[:k]
        train += level_rows[k:]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (("train", train), ("val", val)):
        (out / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in data))

    return {
        "kept": len(rows),
        "total": len(briefs_map),
        "train": len(train),
        "val": len(val),
        "by_level": dict(sorted(collections.Counter(r["level"] for r in rows).items())),
        "by_domain": dict(collections.Counter(r["domain"] for r in rows)),
        "train_ids": [r["id"] for r in train],
        "val_ids": [r["id"] for r in val],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--briefs", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-reasoning", action="store_true")
    ap.add_argument("--val-fraction", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    c = build(a.briefs, a.raw, a.report, a.out, a.no_reasoning, a.val_fraction, a.seed)
    print(f"kept {c['kept']} of {c['total']} briefs; train {c['train']}, val {c['val']}")
    print("by level ", c["by_level"])
    print("by domain", c["by_domain"])


if __name__ == "__main__":
    main()
