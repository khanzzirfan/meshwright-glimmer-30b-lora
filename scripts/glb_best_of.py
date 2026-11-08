"""Pick the best of several sampled candidates per brief (docs/14 section 6).

For every brief, rank its candidates from each --runs directory by automatic signals only
(never the eval ratings) and copy the winner's raw JSON, GLB, screenshot and validation row
into --out, tagged with picked_from. It also writes --out/assembly.jsonl and --out/picks.json.
--out is a normal model run directory, so glb_report.py (--extra-runs) and glb_sheet.mjs
(--root <out>/..) read it like any other run.

Ranking keys, in order: ok, assembled, parts within 8-60, triangles <= 5000, higher
largest_share, then the run order given on the command line (the earlier run wins a tie).
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_ROOTS = (ROOT / "data", ROOT / "out", ROOT / "eval")
ASSEMBLY_SCRIPT = ROOT / "scripts" / "glb_assembly.mjs"
PARTS_MIN, PARTS_MAX = 8, 60
TRIANGLES_MAX = 5000


class BestOfError(Exception):
    pass


def read_jsonl(path):
    """Parse a JSONL file into a list, or [] when it does not exist."""
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def check_out_dir(out_dir, runs):
    """Refuse --out under data/, out/ or eval/, or equal to one of the --runs inputs."""
    out = Path(out_dir).resolve()
    for base in FORBIDDEN_ROOTS:
        base = base.resolve()
        if out == base or base in out.parents:
            raise BestOfError(f"--out must not be inside {base.relative_to(ROOT)}/ ({out})")
    for run in runs:
        if out == Path(run).resolve():
            raise BestOfError(f"--out must not be one of the --runs directories ({out})")


def load_assembly(run_dir):
    """id -> assembly line from RUN_DIR/assembly.jsonl, or None when the file is missing."""
    path = Path(run_dir) / "assembly.jsonl"
    if not path.exists():
        return None
    return {line["id"]: line for line in read_jsonl(path)}


def ensure_assembly(run_dir, briefs_path, compute):
    """The run's id -> assembly line map; computes RUN_DIR/assembly.jsonl when missing and allowed."""
    assembly = load_assembly(run_dir)
    if assembly is not None:
        return assembly
    if not compute:
        raise BestOfError(
            f"{run_dir} has no assembly.jsonl; rerun without --no-compute "
            f"(node scripts/glb_assembly.mjs --run {run_dir} --briefs {briefs_path})"
        )
    rc = subprocess.run(
        ["node", str(ASSEMBLY_SCRIPT), "--run", str(run_dir), "--briefs", str(briefs_path)]
    ).returncode
    if rc:
        raise BestOfError(f"glb_assembly.mjs failed for {run_dir} (exit {rc})")
    return load_assembly(run_dir) or {}


def rank_keys(row, assembly_line, run_index):
    """The docs/14 section 6 key vector: [ok, assembled, parts 8-60, tris <= 5000, largest_share, run]."""
    result = (assembly_line or {}).get("assembly") or {}
    parts = result.get("parts")
    share = result.get("largest_share")
    triangles = ((row or {}).get("stats") or {}).get("glb") or {}
    triangles = triangles.get("triangles")
    return [
        1 if (row or {}).get("ok") else 0,
        1 if result.get("assembled") else 0,
        1 if isinstance(parts, (int, float)) and PARTS_MIN <= parts <= PARTS_MAX else 0,
        1 if isinstance(triangles, (int, float)) and triangles <= TRIANGLES_MAX else 0,
        float(share) if isinstance(share, (int, float)) else -1.0,
        run_index,
    ]


def _order(candidate):
    """Sort key: the first five keys descending, the run index ascending (earlier run wins)."""
    keys = candidate["rank_keys"]
    return (keys[0], keys[1], keys[2], keys[3], keys[4], -keys[5])


def pick(candidates):
    """The winner of a non-empty candidate list."""
    return max(candidates, key=_order)


def candidates_for(brief_id, runs):
    """Every run's candidate for one brief, in run order. `runs` items are
    {name, dir, rows, assembly} with rows/assembly keyed by id."""
    found = []
    for index, run in enumerate(runs):
        row = run["rows"].get(brief_id)
        if row is None:
            continue
        line = run["assembly"].get(brief_id)
        found.append({
            "run_name": run["name"],
            "run_dir": run["dir"],
            "row": row,
            "assembly_line": line,
            "rank_keys": rank_keys(row, line, index),
        })
    return found


def copy_winner(out_dir, brief_id, winner):
    """Copy the winner's raw JSON (with picked_from), GLB and screenshot into --out when present."""
    out_dir = Path(out_dir)
    raw_src = Path(winner["run_dir"]) / "raw" / f"{brief_id}.json"
    if raw_src.exists():
        raw = json.loads(raw_src.read_text())
        raw["picked_from"] = winner["run_name"]
        (out_dir / "raw" / f"{brief_id}.json").write_text(json.dumps(raw))
    for sub, name in (("glb", f"{brief_id}.glb"), ("shots", f"{brief_id}.png")):
        src = Path(winner["run_dir"]) / sub / name
        if src.exists():
            shutil.copyfile(src, out_dir / sub / name)


def assembly_line_for(brief_id, winner):
    """One --out/assembly.jsonl line {id, kind, assembly}, null when the winner has no result."""
    line = winner["assembly_line"]
    if line is None:
        return {"id": brief_id, "kind": "static", "assembly": None}
    return {"id": brief_id, "kind": line.get("kind", "static"), "assembly": line.get("assembly")}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pick the best candidate per brief (docs/14 section 6).")
    ap.add_argument("--runs", nargs="+", required=True, help="two or more model run directories, in tie-break order")
    ap.add_argument("--briefs", required=True, help="briefs JSONL that names every picked id")
    ap.add_argument("--out", required=True, help="output run directory (outside data/, out/ and eval/)")
    ap.add_argument("--no-compute", action="store_true", help="do not run glb_assembly.mjs; require every run's assembly.jsonl")
    a = ap.parse_args(argv)

    runs = [Path(r) for r in a.runs]
    try:
        check_out_dir(a.out, runs)
        for run in runs:
            if not (run / "validation.jsonl").exists():
                raise BestOfError(f"--runs has no validation.jsonl: {run}")
        for run in runs:
            ensure_assembly(run, a.briefs, not a.no_compute)
    except BestOfError as e:
        ap.error(str(e))

    briefs = read_jsonl(a.briefs)
    loaded = []
    for run in runs:
        loaded.append({
            "name": run.name,
            "dir": run,
            "rows": {row["id"]: row for row in read_jsonl(run / "validation.jsonl")},
            "assembly": load_assembly(run) or {},
        })

    out = Path(a.out)
    for sub in ("raw", "glb", "shots"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    rows_out, assembly_out, picks = [], [], {}
    picked = 0
    for brief in briefs:
        brief_id = brief["id"]
        candidates = candidates_for(brief_id, loaded)
        if not candidates:
            picks[brief_id] = {"picked_from": None, "rank_keys": None}
            continue
        winner = pick(candidates)
        picked += 1
        copy_winner(out, brief_id, winner)
        row = dict(winner["row"])
        row["picked_from"] = winner["run_name"]
        rows_out.append(row)
        assembly_out.append(assembly_line_for(brief_id, winner))
        picks[brief_id] = {"picked_from": winner["run_name"], "rank_keys": winner["rank_keys"]}

    (out / "validation.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows_out))
    (out / "assembly.jsonl").write_text("".join(json.dumps(l) + "\n" for l in assembly_out))
    (out / "picks.json").write_text(json.dumps(picks, indent=2) + "\n")
    print(f"picked {picked} of {len(briefs)} briefs")


if __name__ == "__main__":
    main()
