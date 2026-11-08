"""Sequential best-of-N cost simulator (docs/14 section 6, imp-2 US-002).

Replays samples a set of --runs already holds and reports what an adaptive best-of-N rule would
have spent. For each brief it walks the runs in the given order and stops at the first candidate
that is both valid (`ok`) and assembled (the kind-aware `assembled` boolean in assembly.jsonl),
spending only the samples up to that point. A brief with no such candidate falls through to the
whole list and is picked with glb_best_of.py's ranking, so the picker is imported, never copied.

Seconds come from the same field glb_report.py reads for 'Median seconds', `raw/<id>.json`
`usage.seconds`; a candidate without that field counts as 0.0. A run without assembly.jsonl warns
and its rows count as not assembled. Prints a short table and, with --out, writes the JSON.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

import glb_best_of

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_ROOTS = (ROOT / "data", ROOT / "out", ROOT / "eval")


class CostError(Exception):
    pass


def check_out_path(out):
    """Refuse --out under data/, out/ or eval/ (never write the owner's data)."""
    out = Path(out).resolve()
    for base in FORBIDDEN_ROOTS:
        base = base.resolve()
        if out == base or base in out.parents:
            raise CostError(f"--out must not be inside {base.relative_to(ROOT)}/ ({out})")


def load_runs(paths):
    """Load --runs into glb_best_of's run shape plus `raws`. A run with no assembly.jsonl warns."""
    runs = []
    for path in paths:
        path = Path(path)
        assembly = glb_best_of.load_assembly(path)
        if assembly is None:
            print(
                f"warning: {path.name} has no assembly.jsonl; its rows count as not assembled",
                file=sys.stderr,
            )
            assembly = {}
        raws = {}
        raw_dir = path / "raw"
        if raw_dir.is_dir():
            for raw_path in sorted(raw_dir.glob("*.json")):
                raw = json.loads(raw_path.read_text())
                raws[raw.get("id") or raw_path.stem] = raw
        runs.append({
            "name": path.name,
            "dir": path,
            "rows": {row["id"]: row for row in glb_best_of.read_jsonl(path / "validation.jsonl")},
            "assembly": assembly,
            "raws": raws,
        })
    return runs


def seconds_for(run, brief_id):
    """The sample's `usage.seconds` (the field glb_report.py reads), 0.0 when absent."""
    raw = run["raws"].get(brief_id) or {}
    value = (raw.get("usage") or {}).get("seconds")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _mean(values):
    return statistics.mean(values) if values else None


def _median(values):
    return statistics.median(values) if values else None


def _share(count, n):
    return count / n if n else None


def simulate_cost(runs, briefs):
    """Per brief: adaptive samples spent and picked candidate, next to the always-N baseline.

    `runs` is the list from load_runs; `briefs` is the list read from the briefs file. Uses
    glb_best_of.candidates_for (ranking key vector) and glb_best_of.pick for the fallback, never a
    copy of the ranking.
    """
    per_brief = {}
    samples = []
    adaptive_seconds, always_seconds = [], []
    adaptive_ok = adaptive_assembled = 0
    always_ok = always_assembled = 0
    by_run = {run["name"]: run for run in runs}

    for brief in briefs:
        brief_id = brief["id"]
        candidates = glb_best_of.candidates_for(brief_id, runs)

        inserted = 0
        picked = None
        for candidate in candidates:
            inserted += 1
            # rank_keys is [ok, assembled, ...]; stop at the first valid, assembled candidate.
            if candidate["rank_keys"][0] and candidate["rank_keys"][1]:
                picked = candidate
                break

        # The always-N baseline is the ranking winner over every sample; a brief that never stops
        # early falls through to exactly that pick, so it is computed once and reused.
        always_pick = glb_best_of.pick(candidates) if candidates else None
        if picked is None:
            picked = always_pick

        spent = sum(seconds_for(by_run[c["run_name"]], brief_id) for c in candidates[:inserted])
        all_seconds = sum(seconds_for(by_run[c["run_name"]], brief_id) for c in candidates)

        if picked is not None:
            adaptive_ok += picked["rank_keys"][0]
            adaptive_assembled += picked["rank_keys"][1]
        if always_pick is not None:
            always_ok += always_pick["rank_keys"][0]
            always_assembled += always_pick["rank_keys"][1]

        samples.append(inserted)
        adaptive_seconds.append(spent)
        always_seconds.append(all_seconds)
        per_brief[brief_id] = {
            "samples": inserted,
            "seconds": spent,
            "ok": bool(picked and picked["rank_keys"][0]),
            "assembled": bool(picked and picked["rank_keys"][1]),
            "picked_from": picked["run_name"] if picked else None,
        }

    n = len(briefs)
    return {
        "briefs": n,
        "runs": [run["name"] for run in runs],
        "adaptive": {
            "mean_samples": _mean(samples),
            "mean_seconds": _mean(adaptive_seconds),
            "median_seconds": _median(adaptive_seconds),
            "share_ok": _share(adaptive_ok, n),
            "share_assembled": _share(adaptive_assembled, n),
        },
        "always_n": {
            "samples": float(len(runs)),
            "mean_seconds": _mean(always_seconds),
            "median_seconds": _median(always_seconds),
            "share_ok": _share(always_ok, n),
            "share_assembled": _share(always_assembled, n),
        },
        "per_brief": per_brief,
    }


def _format(value, digits=2):
    return "n/a" if value is None else f"{value:.{digits}f}"


def _percent(value):
    return "n/a" if value is None else f"{value:.1%}"


def render_table(report):
    """A short adaptive-vs-always-N table."""
    lines = [f"briefs: {report['briefs']}   runs: {', '.join(report['runs'])}"]
    lines.append(
        f"{'rule':<10} {'samples':>8} {'mean s':>8} {'median s':>9} {'ok':>8} {'assembled':>10}"
    )
    rows = [
        ("adaptive", report["adaptive"]["mean_samples"], report["adaptive"]),
        (f"always-{report['always_n']['samples']:.0f}",
         report["always_n"]["samples"], report["always_n"]),
    ]
    for label, used, row in rows:
        lines.append(
            f"{label:<10} {_format(used):>8} {_format(row['mean_seconds']):>8} "
            f"{_format(row['median_seconds']):>9} {_percent(row['share_ok']):>8} "
            f"{_percent(row['share_assembled']):>10}"
        )
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Simulate an adaptive best-of-N cost against the always-N baseline (docs/14 section 6)."
    )
    ap.add_argument("--runs", nargs="+", required=True, help="run directories in sampling order, each with validation.jsonl")
    ap.add_argument("--briefs", required=True, help="briefs JSONL naming every scored id")
    ap.add_argument("--out", default=None, help="write the report JSON here (outside data/, out/ and eval/)")
    a = ap.parse_args(argv)

    try:
        if a.out:
            check_out_path(a.out)
    except CostError as e:
        ap.error(str(e))

    briefs = glb_best_of.read_jsonl(a.briefs)
    runs = load_runs(a.runs)
    report = simulate_cost(runs, briefs)
    print(render_table(report))
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
