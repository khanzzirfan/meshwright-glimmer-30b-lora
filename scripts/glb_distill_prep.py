"""Turn the generator's good picks into a self-distillation training set (docs/14, imp-5 US-007).

Reads a glb_generate.py batch run (`--run DIR`, one `DIR/<id>/result.json` per brief) and keeps the briefs
the generator reports as valid, assembled and within the triangle budget (and `assembled_obb` with
`--require-obb`). The completion is the picked attempt's raw `content` (answer only, no reasoning) and the
prompt is [system from `--system`, user = the brief text], written in the `ccore_prep.py` row shape so
`scripts/mesh_lora_hf.py` reads the output unchanged. Ids in the eval namespace (a `g` prefix, or an id or
title found in `bench/glb/briefs.jsonl`) are refused, the train/val split is a stable hash of the id, and
`--out` is refused inside `data/`, `out/` or `eval/`. `DIR/stats.json` counts every drop reason and the kept
rows by domain and kind.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path

from ccore_prep import (
    CcorePrepError,
    build_row,
    chars_stats,
    check_out_dir,
    display_path,
    read_jsonl,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BRIEFS = "bench/distill/briefs.jsonl"
DEFAULT_SYSTEM = "prompts/system_glb_v3.txt"
EVAL_BRIEFS = ROOT / "bench" / "glb" / "briefs.jsonl"
ATTEMPT_ID = "asset"  # glb_generate.py's single candidate name in every attempt directory
REPAIR_DIRS = {True: "repair", "assembly": "repair-asm"}  # the repair tags and their directories
PARTS_MIN, PARTS_MAX = 8, 60  # glb_best_of.py's ranking band, reused to tell a repair from its source sample
TRIANGLES_MAX = 5000
# The drop rules, in the order keep_completion applies them; the first match wins.
DROP_REASONS = ("eval_id", "eval_title", "missing", "not_ok", "unassembled",
                "over_budget", "no_content", "not_obb")


def resolve_path(value):
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def eval_ids_and_titles(path):
    """The eval briefs' ids and case-folded titles, so a distillation row can never be one of them."""
    rows = read_jsonl(path)
    return {row.get("id") for row in rows}, {(row.get("title") or "").strip().casefold() for row in rows}


def rank_signal(record):
    """The automatic signals glb_best_of.pick ranks first (its largest_share key is not recorded).

    A repair turn shares its source sample's seed, so these tell the two apart without re-running the picker.
    """
    parts = record.get("parts")
    triangles = record.get("triangles")
    return (
        1 if record.get("ok") else 0,
        1 if record.get("assembled") else 0,
        1 if isinstance(parts, (int, float)) and PARTS_MIN <= parts <= PARTS_MAX else 0,
        1 if isinstance(triangles, (int, float)) and triangles <= TRIANGLES_MAX else 0,
    )


def picked_record(result):
    """The picked attempt's record from a result.json, or None.

    Among the same-seed records the best signals win; ties keep the earliest, which is glb_best_of.pick's
    run-order tie-break, so a successful repair beats the failed sample it corrects.
    """
    seed = result.get("picked_seed")
    same = [a for a in (result.get("attempts") or []) if a.get("seed") == seed]
    return max(same, key=rank_signal) if same else None


def attempt_dir(brief_dir, record, seed):
    """The picked attempt's directory: the repair dir when the record is a repair turn, else attempts/<seed>."""
    tag = record.get("repair")
    if tag:
        return brief_dir / "attempts" / REPAIR_DIRS.get(tag, "repair")
    return brief_dir / "attempts" / str(seed)


def assembly_of(directory):
    """The picked attempt's assembly from its validation row (`stats.glb.assembly`), or {}."""
    rows = read_jsonl(Path(directory) / "validation.jsonl")
    row = next((r for r in rows if r.get("id") == ATTEMPT_ID), rows[0] if rows else None)
    return (((row or {}).get("stats") or {}).get("glb") or {}).get("assembly") or {}


def picked_content(brief_dir, result):
    """(the picked attempt's answer text, its directory), or (None, None) when it cannot be read."""
    record = picked_record(result)
    if record is None:
        return None, None
    directory = attempt_dir(brief_dir, record, result.get("picked_seed"))
    raw_path = directory / "raw" / f"{ATTEMPT_ID}.json"
    if not raw_path.exists():
        return None, None
    return (json.loads(raw_path.read_text()).get("content") or ""), directory


def split_of(brief_id, val_frac):
    """The stable train/val split of an id: a fixed hash bucket below val_frac is val, else train."""
    bucket = int(hashlib.sha256(brief_id.encode()).hexdigest(), 16) % 10000
    return "val" if bucket < round(val_frac * 10000) else "train"


def keep_completion(brief, run, eval_ids, eval_titles, require_obb):
    """The picked answer to keep for a brief, or (None, reason) for the first drop rule that matches."""
    brief_id = str(brief.get("id") or "")
    if brief_id.startswith("g"):
        return None, "eval_id"
    if brief_id in eval_ids or (brief.get("title") or "").strip().casefold() in eval_titles:
        return None, "eval_title"
    result_path = Path(run) / brief_id / "result.json"
    if not result_path.exists():
        return None, "missing"
    result = json.loads(result_path.read_text())
    if not result.get("picked_ok"):
        return None, "not_ok"
    if not result.get("picked_assembled"):
        return None, "unassembled"
    if not result.get("picked_within_budget"):
        return None, "over_budget"
    completion, directory = picked_content(Path(run) / brief_id, result)
    if completion is None:
        return None, "no_content"
    if require_obb and not assembly_of(directory).get("assembled_obb"):
        return None, "not_obb"
    return completion, None


def build(briefs, run, system, eval_ids, eval_titles, require_obb, val_frac):
    """Split the briefs into kept rows, the train/val split, per-reason drops and the domain/kind counts."""
    kept = []
    dropped = collections.Counter()
    by_domain, by_kind = collections.Counter(), collections.Counter()
    for brief in briefs:
        completion, reason = keep_completion(brief, run, eval_ids, eval_titles, require_obb)
        if reason is not None:
            dropped[reason] += 1
            continue
        kept.append(build_row(brief.get("id"), brief.get("domain"), brief.get("title"),
                              system, brief.get("brief"), completion))
        by_domain[brief.get("domain") or ""] += 1
        by_kind[brief.get("kind") or ""] += 1
    train = [row for row in kept if split_of(row["id"], val_frac) == "train"]
    val = [row for row in kept if split_of(row["id"], val_frac) == "val"]
    return kept, train, val, dropped, by_domain, by_kind


def build_parser():
    """The argument parser, so a test can parse a command line without running anything."""
    ap = argparse.ArgumentParser(description="Build the self-distillation set from a glb_generate.py run (docs/14, imp-5).")
    ap.add_argument("--run", required=True, help="a glb_generate.py batch run (one DIR/<id>/result.json per brief)")
    ap.add_argument("--briefs", default=DEFAULT_BRIEFS, help="the briefs JSONL the run was generated from")
    ap.add_argument("--out", required=True, help="output directory for train.jsonl, val.jsonl and stats.json (outside data/, out/ and eval/)")
    ap.add_argument("--system", default=DEFAULT_SYSTEM, help="the system prompt written into every row's prompt")
    ap.add_argument("--val-frac", type=float, default=0.1, help="share of ids in val, by a stable hash of the id (default 0.1)")
    ap.add_argument("--require-obb", action="store_true", help="also require the picked attempt's assembled_obb")
    return ap


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)

    try:
        check_out_dir(a.out)
        if not 0.0 <= a.val_frac <= 1.0:
            raise CcorePrepError("--val-frac must be between 0 and 1")
        run = resolve_path(a.run)
        briefs_path = resolve_path(a.briefs)
        system_path = resolve_path(a.system)
        for path, flag in ((run, "--run"), (briefs_path, "--briefs"),
                           (EVAL_BRIEFS, "eval briefs"), (system_path, "--system")):
            if not path.exists():
                raise CcorePrepError(f"{flag} not found: {path}")
    except CcorePrepError as e:
        ap.error(str(e))

    system = system_path.read_text()
    eval_ids, eval_titles = eval_ids_and_titles(EVAL_BRIEFS)
    briefs = read_jsonl(briefs_path)
    kept, train, val, dropped, by_domain, by_kind = build(
        briefs, run, system, eval_ids, eval_titles, a.require_obb, a.val_frac
    )

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "train.jsonl").write_text("".join(json.dumps(r) + "\n" for r in train))
    (out / "val.jsonl").write_text("".join(json.dumps(r) + "\n" for r in val))

    stats = {
        "run": display_path(run),
        "briefs": display_path(briefs_path),
        "system_file": display_path(system_path),
        "system_sha256": hashlib.sha256(system.encode()).hexdigest(),
        "val_frac": a.val_frac,
        "require_obb": a.require_obb,
        "kept": len(kept),
        "train": len(train),
        "val": len(val),
        "dropped_by_reason": {reason: dropped[reason] for reason in DROP_REASONS},
        "completion_chars": chars_stats(kept),
        "by_domain": dict(by_domain),
        "by_kind": dict(by_kind),
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(f"kept {len(kept)} ({len(train)} train, {len(val)} val); dropped "
          + ", ".join(f"{reason} {dropped[reason]}" for reason in DROP_REASONS))


if __name__ == "__main__":
    main()
