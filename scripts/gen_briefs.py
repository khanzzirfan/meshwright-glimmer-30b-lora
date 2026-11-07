"""Generate diverse scene briefs with the brief model. Writes briefs.jsonl and briefs.eval.jsonl."""
import argparse
import itertools
import json
import os
import random
import re
from pathlib import Path

from common import client

DOMAINS = [
    "architecture", "nature and landscapes", "vehicles", "characters and creatures", "interiors and furniture",
    "small props and objects", "sci-fi", "historical landmarks", "abstract and particle effects",
    "voxel games", "UI panels in 3D", "data visualisation",
]
STYLES = ["low-poly", "voxel", "stylised", "realistic-ish", "toon"]
LEVEL_HINT = {
    1: "one simple object with a light",
    3: "a few objects with a simple animation",
    5: "a small composed scene with animation",
    7: "a detailed scene with several animated parts",
    10: "a large scene with several animated systems and orbit controls",
}


def words(s):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def near_dup(a, seen):
    wa = words(a)
    return any(len(wa & wb) / max(1, len(wa | wb)) > 0.8 for wb in seen)


def ask(c, model, domain, level, style, n):
    hint = LEVEL_HINT[min(LEVEL_HINT, key=lambda k: abs(k - level))]
    prompt = (
        f"Write {n} different requests a user might type to get an interactive Three.js scene.\n"
        f"Domain: {domain}. Style: {style}. Complexity {level}/10 ({hint}).\n"
        "Vary length and phrasing: some terse, some detailed. No two about the same subject.\n"
        'Return only JSON lines, each {"title": "...", "brief": "..."}.'
    )
    r = c.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], temperature=1.0, max_tokens=2000)
    out = []
    for line in (r.choices[0].message.content or "").splitlines():
        line = line.strip().strip(",")
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
            out.append({"title": d["title"], "brief": d["brief"], "domain": domain, "level": level, "style": style})
        except (json.JSONDecodeError, KeyError):
            continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--out", default="data/briefs.jsonl")
    ap.add_argument("--eval-fraction", type=float, default=0.07)
    ap.add_argument("--per-call", type=int, default=5)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--model", default=None)
    ap.add_argument("--base-url", default=None, help="e.g. http://localhost:11434/v1 for Ollama")
    ap.add_argument("--api-key", default=None)
    a = ap.parse_args()

    model = a.model or os.environ.get("BRIEF_MODEL") or os.environ["TEACHER_MODEL"]
    c = client(a.base_url, a.api_key)
    rng = random.Random(a.seed)
    grid = list(itertools.product(DOMAINS, range(1, 11), STYLES))
    rng.shuffle(grid)

    rows, seen, empty = [], [], 0
    for domain, level, style in itertools.cycle(grid):
        if len(rows) >= a.count:
            break
        got = ask(c, model, domain, level, style, a.per_call)
        empty = 0 if got else empty + 1
        if empty >= 10:
            raise SystemExit("10 calls in a row returned no parsable JSON lines; check BRIEF_MODEL output")
        for r in got:
            if not near_dup(r["title"] + " " + r["brief"], seen):
                seen.append(words(r["title"] + " " + r["brief"]))
                r["id"] = f"b{len(rows):05d}"
                rows.append(r)
        print(f"{len(rows)}/{a.count}", end="\r")

    rows = rows[: a.count]
    rng.shuffle(rows)
    n_eval = max(1, int(len(rows) * a.eval_fraction)) if a.eval_fraction > 0 else 0
    ev, tr = rows[:n_eval], rows[n_eval:]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in tr))
    out.with_name(out.stem + ".eval.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ev))
    print(f"\ntrain briefs {len(tr)}, eval briefs {len(ev)}")


if __name__ == "__main__":
    main()
