"""List the briefs that still lack a valid, assembled candidate across runs (docs/14 section 6, imp-3 US-003).

For every brief id in --briefs, keep it when no --runs directory holds a row that is both valid (`ok`)
and assembled (the kind-aware `assembled` boolean in assembly.jsonl). Candidates come from
glb_best_of.candidates_for, whose rank key vector starts [ok, assembled, ...] and which skips ids a run
lacks, so the check reuses the same helper the picker uses and is never a copy.

A run without assembly.jsonl gets one from glb_assembly.mjs unless --no-compute; with --no-compute the run
warns and its rows count as not assembled. Writes one id per line to --out and prints 'remaining X of Y'.
"""
import argparse
import sys
from pathlib import Path

import glb_best_of


class AdaptiveIdsError(Exception):
    pass


def load_runs(paths, briefs_path, compute):
    """Load --runs into glb_best_of's run shape {name, dir, rows, assembly}.

    A run without assembly.jsonl is computed with glb_assembly.mjs when `compute`; when not, it warns and
    its rows count as not assembled. A run without validation.jsonl is an error.
    """
    runs = []
    for path in paths:
        path = Path(path)
        if not (path / "validation.jsonl").exists():
            raise AdaptiveIdsError(f"--runs has no validation.jsonl: {path}")
        if compute:
            assembly = glb_best_of.ensure_assembly(path, briefs_path, True)
        else:
            assembly = glb_best_of.load_assembly(path)
            if assembly is None:
                print(
                    f"warning: {path.name} has no assembly.jsonl; its rows count as not assembled",
                    file=sys.stderr,
                )
                assembly = {}
        runs.append({
            "name": path.name,
            "dir": path,
            "rows": {row["id"]: row for row in glb_best_of.read_jsonl(path / "validation.jsonl")},
            "assembly": assembly,
        })
    return runs


def has_good_candidate(brief_id, runs):
    """True when some run holds a row that is both valid and assembled (rank key 0 and 1)."""
    for candidate in glb_best_of.candidates_for(brief_id, runs):
        keys = candidate["rank_keys"]
        if keys[0] and keys[1]:
            return True
    return False


def remaining_ids(briefs, runs):
    """The brief ids no run holds a valid, assembled candidate for, in --briefs order."""
    return [brief["id"] for brief in briefs if not has_good_candidate(brief["id"], runs)]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="List briefs with no valid, assembled candidate across runs (docs/14 section 6)."
    )
    ap.add_argument("--runs", nargs="+", required=True, help="run directories in sampling order, each with validation.jsonl")
    ap.add_argument("--briefs", required=True, help="briefs JSONL naming every candidate id")
    ap.add_argument("--out", required=True, help="write the remaining ids here, one per line")
    ap.add_argument("--no-compute", action="store_true",
                    help="do not run glb_assembly.mjs; a run without assembly.jsonl warns and counts as not assembled")
    a = ap.parse_args(argv)

    try:
        runs = load_runs(a.runs, a.briefs, not a.no_compute)
    except (AdaptiveIdsError, glb_best_of.BestOfError) as e:
        ap.error(str(e))

    briefs = glb_best_of.read_jsonl(a.briefs)
    remaining = remaining_ids(briefs, runs)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(brief_id + "\n" for brief_id in remaining))
    print(f"remaining {len(remaining)} of {len(briefs)}")


if __name__ == "__main__":
    main()
