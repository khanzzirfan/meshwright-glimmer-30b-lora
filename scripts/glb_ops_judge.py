"""Judge or summarise a benchmark run folder (<root>/glimmer/validation.jsonl plus raw answers).

    python3 scripts/glb_ops_judge.py dev runs/glb_v2/dev1      verdict PASS or FAIL, written to <root>/judge.json
    python3 scripts/glb_ops_judge.py summary runs/glb_v2/glimmer-think   numbers only, no verdict

The dev rule (fixed before the run, docs/13 section 12): at least 10 of 12 valid GLBs, and at least 2 of the 3 animated
dev briefs (d004, d009, d012) export with an animation in the GLB.
"""
import json
import sys
from collections import Counter
from pathlib import Path

DEV_ANIMATED = ("d004", "d009", "d012")
MIN_VALID, MIN_ANIMATED = 10, 2


def load(folder):
    folder = Path(folder)
    vfile = next(folder.glob("*/validation.jsonl"), None) or (folder / "validation.jsonl")
    rows = [json.loads(line) for line in vfile.read_text().splitlines() if line.strip()]
    raws = {}
    for r in rows:
        raw = vfile.parent / "raw" / f"{r['id']}.json"
        raws[r["id"]] = json.loads(raw.read_text()) if raw.exists() else {}
    return rows, raws


def animated_ok(row):
    return bool(row["ok"] and ((row.get("stats") or {}).get("glb") or {}).get("animations", 0) > 0)


def summary(rows, raws):
    valid = sum(1 for r in rows if r["ok"])
    anim = [r for r in rows if (raws.get(r["id"]).get("brief") or {}).get("kind") == "animated"]
    reasons = Counter(x for r in rows for x in (r["reasons"] or ["ok"]))
    return {"n": len(rows), "valid": valid, "animated": len(anim), "animated_with_animation": sum(animated_ok(r) for r in anim),
            "reasons": dict(reasons)}


def judge_dev(rows, raws):
    s = summary(rows, raws)
    dev_anim = [r for r in rows if r["id"] in DEV_ANIMATED]
    s["dev_animated_with_animation"] = sum(animated_ok(r) for r in dev_anim)
    ok = s["n"] == 12 and s["valid"] >= MIN_VALID and s["dev_animated_with_animation"] >= MIN_ANIMATED
    s["verdict"] = "PASS" if ok else "FAIL"
    s["rule"] = f"n == 12, valid >= {MIN_VALID}, animated dev briefs with an animation >= {MIN_ANIMATED} of {len(DEV_ANIMATED)}"
    return s


def main(argv):
    if len(argv) != 3 or argv[1] not in ("dev", "summary"):
        print(__doc__)
        return 2
    rows, raws = load(argv[2])
    if argv[1] == "summary":
        print(json.dumps(summary(rows, raws), indent=2))
        return 0
    result = judge_dev(rows, raws)
    (Path(argv[2]) / "judge.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
