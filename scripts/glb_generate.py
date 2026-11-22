"""One command: a text prompt in, the best GLB out (docs/14, imp-4 US-001).

Samples the frozen prompt up to --max-samples times (seeds seed-start, seed-start+1, ...). Each sample
is one Ollama /api/chat call (reusing teacher_generate.call_ollama, which forwards options.seed), then
validated with `node scripts/validate_scenes.mjs --mode glb --allow-addons` and dropped onto the ground
with glb_ground.mjs (docs/14 section 4), so a hovering asset is fixed for free and the grounding's
assembly_after decides that attempt's `assembled` value. The grounded copy is then passed through
glb_names.mjs, which rewrites any name ending in a long fractional suffix so Blender 5.2 does not abort on
it, and the attempt records how many names changed (`renamed_names`, promo-1 US-008). The loop stops at
the first candidate that is valid (ok), assembled and within --tri-budget (default 5000) triangles. When
none is assembled it keeps every sample and picks a winner with glb_best_of.py's ranking (imported, never
copied). Every attempt is recorded:

    OUT_DIR/attempts/<seed>/
        raw/asset.json          the generation row (its brief carries the kind)
        page.html               the page extracted from the answer, when there is one
        scenes/asset.html       the validator's copy of the page
        shots/asset.png         the validator's screenshot
        glb/asset.glb           the exported GLB
        glb/asset.grounded.glb  the grounded copy (this attempt's GLB from then on)
        validation.jsonl        the validator's one validation row

When every sample failed and one of them failed for a reason glb_repair.py can fix, the loop spends
one repair turn (glb_repair.py's four-message builder and fix message, imported, never copied) into
OUT_DIR/attempts/repair/, its record tagged `repair: true`. Truncated, no_html and external_dep are
never repaired. When samples are valid but none is assembled, it instead spends one assembly repair turn
on the best valid sample (glb_repair.py's assembly fix message, imported) into OUT_DIR/attempts/repair-asm/,
its record tagged `repair: "assembly"`. Either turn is validated and grounded like a sample and competes
in the ranking. --no-repair turns both off.

The winner's GLB is copied to OUT_DIR/asset.glb and the run summary to OUT_DIR/result.json.
It refuses an --out-dir under data/, out/ or eval/ and a paid model row, like glb_bench.py, and
exits 0 when the picked candidate is valid, else 2.

With --briefs FILE (mutually exclusive with the positional PROMPT) it runs the same loop for every
brief (id, prompt, kind) into OUT_DIR/<id>/, skipping a brief whose result.json already exists
(resumable: a rerun makes no request), then writes OUT_DIR/summary.json {briefs, picked_ok,
picked_assembled, mean_samples, mean_seconds, repairs_used} over every brief's result.json and prints
a one-screen table. mean_samples is the mean of the generation samples per brief (the repair turn is
reported separately in repairs_used). --ids-file restricts the briefs and --limit caps them.

Tests swap the validator by pointing GLB_GENERATE_VALIDATOR at a script (the same --mode/--raw/
--glb-dir/--report flags are passed, so a small fake can stand in for Chromium offline).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import glb_bench
import glb_best_of
import glb_repair
import teacher_generate

ROOT = Path(__file__).resolve().parent.parent
VALIDATE_SCRIPT = "scripts/validate_scenes.mjs"
FORBIDDEN_ROOTS = (ROOT / "data", ROOT / "out", ROOT / "eval")
ATTEMPT_ID = "asset"  # the single candidate in each attempt directory
REPAIR_DIR = "repair"  # the one error repair turn lives beside the seed directories
ASSEMBLY_REPAIR_DIR = "repair-asm"  # the one assembly repair turn (glb_repair.py's --mode assembly layout)
GROUND_SCRIPT = ROOT / "scripts" / "glb_ground.mjs"  # absolute so the grounding works from any cwd
NAMES_SCRIPT = ROOT / "scripts" / "glb_names.mjs"  # makes Blender-unsafe names safe (promo-1 US-008)
DEFAULT_TRI_BUDGET = 5000  # glb_best_of.py's triangle ceiling, so the stop rule matches its ranking
NUM_CTX = 49152
NUM_PREDICT = 40000

FENCE = re.compile(r"```html\s*\n([\s\S]*?)```", re.IGNORECASE)
DOCTYPE = re.compile(r"<!doctype html[\s\S]*?</html>", re.IGNORECASE)
BARE_HTML = re.compile(r"<html[\s\S]*?</html>", re.IGNORECASE)


class GenerateError(Exception):
    pass


def check_out_dir(out_dir):
    """Refuse an --out-dir under data/, out/ or eval/ (never write the owner's data)."""
    out = Path(out_dir).resolve()
    for base in FORBIDDEN_ROOTS:
        base = base.resolve()
        if out == base or base in out.parents:
            raise GenerateError(f"--out-dir must not be inside {base.relative_to(ROOT)}/ ({out})")


def find_model(models, name):
    for model in models:
        if model["name"] == name:
            return model
    raise GenerateError(f"unknown --model-row: {name}")


def validator_base():
    """The validator command prefix: the pinned script, or GLB_GENERATE_VALIDATOR (tests)."""
    override = os.environ.get("GLB_GENERATE_VALIDATOR")
    if not override:
        return ["node", VALIDATE_SCRIPT]
    if override.endswith(".py"):
        return [sys.executable, override]
    if override.endswith((".mjs", ".js")):
        return ["node", override]
    if override.endswith(".sh"):
        return ["bash", override]
    return [override]


def validator_command(attempt_dir):
    """The GLB-mode validator command for one attempt directory (docs/14 section 5 layout)."""
    attempt_dir = Path(attempt_dir)
    return validator_base() + [
        "--mode", "glb", "--allow-addons",
        "--raw", str(attempt_dir / "raw"),
        "--scenes", str(attempt_dir / "scenes"),
        "--shots", str(attempt_dir / "shots"),
        "--glb-dir", str(attempt_dir / "glb"),
        "--report", str(attempt_dir / "validation.jsonl"),
    ]


def read_validation(path, attempt_id):
    """The attempt's validation row, or None when the report is missing or empty."""
    path = Path(path)
    if not path.exists():
        return None
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for row in rows:
        if row.get("id") == attempt_id:
            return row
    return rows[0] if rows else None


def extract_html(text):
    """The page inside a fenced ```html block, a doctype document or a bare <html> document."""
    for pattern in (FENCE, DOCTYPE, BARE_HTML):
        match = pattern.search(text or "")
        if match:
            return (match.group(1) if pattern is FENCE else match.group(0)).strip()
    return None


def chat_args(model_row, ollama_url, seed):
    """The teacher_generate.call_ollama options namespace: the model row's sampling plus options.seed."""
    return SimpleNamespace(
        ollama_url=ollama_url,
        temperature=model_row.get("temperature", 0.7),
        top_p=model_row.get("top_p", 0.95),
        num_ctx=NUM_CTX,
        max_tokens=NUM_PREDICT,
        think=bool(model_row.get("think")),
        top_k=model_row.get("top_k"),
        min_p=model_row.get("min_p"),
        repeat_penalty=None,
        seed=seed,
    )


def attempt_record(seed, ok, reasons, assembled, parts, triangles, seconds, repair=False,
                   grounded_shift=None, within_budget=False, renamed_names=0):
    """One result.json `attempts` entry, in the docs/14 US-001 field order (plus the imp-5 fields).

    `grounded_shift` is the vertical shift glb_ground.mjs applied (null when there was no GLB or it could
    not be read) and `within_budget` says whether `triangles` is at or under --tri-budget. `renamed_names`
    is how many Blender-unsafe names glb_names.mjs rewrote in the attempt's GLB (promo-1 US-008). An error
    repair turn carries `repair: true`; an assembly repair turn carries `repair: "assembly"`; a sample
    carries neither key.
    """
    record = {"seed": seed, "ok": ok, "reasons": reasons, "assembled": assembled,
              "parts": parts, "triangles": triangles, "seconds": seconds,
              "grounded_shift": grounded_shift, "within_budget": within_budget,
              "renamed_names": renamed_names}
    if repair:
        record["repair"] = repair
    return record


def candidate(seed, attempt_dir, row, kind, run_index, glb=None, assembled=None):
    """A glb_best_of candidate: the validation row, its assembly line and the ranking vector.

    `glb` is the path of the attempt's GLB (the grounded copy when there is one) and `assembled` overrides
    the row's assembled flag with the grounding's assembly_after, so the ranking sees the grounded value.
    """
    assembly = ((row.get("stats") or {}).get("glb") or {}).get("assembly")
    if assembled is not None and isinstance(assembly, dict):
        assembly = dict(assembly, assembled=assembled)
    line = {"id": ATTEMPT_ID, "kind": kind, "assembly": assembly}
    return {"seed": seed, "dir": Path(attempt_dir), "row": row, "assembly_line": line,
            "glb": Path(glb) if glb is not None else Path(attempt_dir) / "glb" / f"{ATTEMPT_ID}.glb",
            "rank_keys": glb_best_of.rank_keys(row, line, run_index)}


def within_budget(triangles, tri_budget):
    """Whether a validation row's triangle count is at or under the budget (an absent count is not)."""
    return isinstance(triangles, (int, float)) and triangles <= tri_budget


def ground_command(in_file, out_file, kind):
    """The glb_ground.mjs command that drops one GLB onto the ground (docs/14 section 4)."""
    return ["node", str(GROUND_SCRIPT), "--in", str(in_file), "--out", str(out_file), "--kind", kind]


def ground_attempt(attempt_dir, kind):
    """Ground the attempt's GLB: return (glb_path, shift, assembly_after).

    Skips with (the exported GLB, None, None) when the validator wrote no GLB, when glb_ground.mjs fails or
    when the grounding could not read the file (assembly_after carries an error), so the validator's
    `assembled` value stands and `grounded_shift` is null. Otherwise the grounded copy is the attempt's GLB
    from then on and its `shift`/`assembly_after` are returned.
    """
    original = Path(attempt_dir) / "glb" / f"{ATTEMPT_ID}.glb"
    if not original.exists():
        return original, None, None
    grounded = Path(attempt_dir) / "glb" / f"{ATTEMPT_ID}.grounded.glb"
    try:
        proc = subprocess.run(ground_command(original, grounded, kind), capture_output=True, text=True)
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError):
        return original, None, None
    after = payload.get("assembly_after")
    if not (isinstance(after, dict) and after.get("error") is None and after.get("parts") is not None):
        return original, None, None
    return (grounded if grounded.exists() else original), payload.get("shift"), after


def names_command(in_file, out_file):
    """The glb_names.mjs command that rewrites Blender-unsafe names in a GLB (promo-1 US-008)."""
    return ["node", str(NAMES_SCRIPT), "--in", str(in_file), "--out", str(out_file)]


def sanitize_names(glb_path):
    """Rewrite the attempt's GLB names in place; return (glb_path, renamed count).

    Runs after grounding, so the delivered GLB is the sanitized grounded copy. A missing file, a failed
    command or unparseable output leaves the GLB as is with 0 renamed, so a name problem is never fatal
    (the GLB still loads in three.js, only Blender 5.2 aborts on it).
    """
    glb_path = Path(glb_path)
    if not glb_path.exists():
        return glb_path, 0
    try:
        proc = subprocess.run(names_command(glb_path, glb_path), capture_output=True, text=True)
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        return glb_path, int(payload.get("renamed") or 0)
    except (OSError, ValueError, IndexError):
        return glb_path, 0


def assembly_of(candidate_entry):
    """The assembly the validator measured for one candidate, or {} (the assembly repair's numbers)."""
    return (((candidate_entry.get("row") or {}).get("stats") or {}).get("glb") or {}).get("assembly") or {}


def validate_attempt(attempt_dir, seed, kind, raw, run_index, repair=False,
                     tri_budget=DEFAULT_TRI_BUDGET):
    """Validate one attempt directory, ground its GLB and build its (record, candidate).

    The grounding runs after validation: its assembly_after decides the attempt's `assembled` value and its
    grounded copy becomes the attempt's GLB, and its shift is recorded (docs/14 section 4, imp-5 US-003).
    """
    rc = subprocess.run(validator_command(attempt_dir)).returncode
    if rc:
        raise SystemExit(rc)
    row = read_validation(Path(attempt_dir) / "validation.jsonl", ATTEMPT_ID) or {
        "id": ATTEMPT_ID, "ok": False, "reasons": ["no_validation_row"], "stats": {}
    }
    stats = row.get("stats") or {}
    glb = stats.get("glb") or {}
    assembly = glb.get("assembly") or {}
    glb_path, shift, after = ground_attempt(attempt_dir, kind)
    glb_path, renamed = sanitize_names(glb_path)
    assembled = bool(after["assembled"]) if after is not None else bool(assembly.get("assembled"))
    triangles = glb.get("triangles")
    record = attempt_record(
        seed, bool(row.get("ok")), list(row.get("reasons") or []), assembled,
        assembly.get("parts"), triangles,
        (raw.get("usage") or {}).get("seconds") or 0.0, repair=repair,
        grounded_shift=shift, within_budget=within_budget(triangles, tri_budget),
        renamed_names=renamed,
    )
    cand = candidate(seed, attempt_dir, row, kind, run_index, glb=glb_path, assembled=assembled)
    cand["within_budget"] = record["within_budget"]  # the winner's flag must use --tri-budget, not best_of's
    return record, cand


def repairable_seed(candidates):
    """The first sample whose reasons glb_repair.py would repair, or None (docs/14 section 5).

    glb_repair.select_ids is that rule (not ok, at least one reason, none of truncated/no_html/
    external_dep and at least one repairable reason). It is reused with each seed as the id, so the
    rule is imported rather than copied.
    """
    rows = [
        {"id": c["seed"], "ok": (c["row"] or {}).get("ok"), "reasons": (c["row"] or {}).get("reasons")}
        for c in candidates
    ]
    selected = glb_repair.select_ids(rows)
    return selected[0] if selected else None


def repair_turn(source, out, model_row, system, system_file, system_sha256, ollama_url, run_index,
                tri_budget=DEFAULT_TRI_BUDGET, mode="error"):
    """One repair turn for a failing sample (docs/14 section 5), validated and grounded like a sample.

    `mode` is `error` (the failed sample's error fix message, tag `repair: true`) or `assembly` (the valid
    but unassembled sample's assembly fix message, tag `repair: "assembly"`); both messages and the
    four-message builder come from glb_repair.py. A failed call is recorded as a request_error attempt so
    the run still finishes, like a failed sample.
    """
    seed = source["seed"]
    kind = source["assembly_line"]["kind"]
    tag = True if mode == "error" else "assembly"
    attempt_dir = Path(out) / "attempts" / (REPAIR_DIR if mode == "error" else ASSEMBLY_REPAIR_DIR)
    (attempt_dir / "raw").mkdir(parents=True, exist_ok=True)
    orig = json.loads((Path(source["dir"]) / "raw" / f"{ATTEMPT_ID}.json").read_text())
    fix = glb_repair.fix_message(source["row"]) if mode == "error" else \
        glb_repair.assembly_fix_message(assembly_of(source))
    messages = glb_repair.repair_messages(
        system, (orig.get("brief") or {}).get("brief", ""), orig.get("content", ""), fix
    )
    try:
        raw = glb_repair.chat(messages, model_row, ollama_url)
    except Exception as e:  # a failed repair is recorded, not fatal, like a failed sample
        print(f"error: repair of seed {seed}: {e}", file=sys.stderr)
        row = {"id": ATTEMPT_ID, "ok": False, "reasons": ["request_error"], "stats": {}}
        record = attempt_record(seed, False, ["request_error"], False, None, None, 0.0, repair=tag)
        return record, candidate(seed, attempt_dir, row, kind, run_index)
    raw.update({
        "id": ATTEMPT_ID, "brief": orig.get("brief"), "model": model_row["model"],
        "repair_of": seed, "fix_message": fix,
        "system_file": system_file, "system_sha256": system_sha256,
    })
    (attempt_dir / "raw" / f"{ATTEMPT_ID}.json").write_text(json.dumps(raw))
    (attempt_dir / "page.html").write_text(extract_html(raw.get("content") or "") or "")
    return validate_attempt(attempt_dir, seed, kind, raw, run_index, repair=tag, tri_budget=tri_budget)


def generate_run(prompt, kind, out, model_row, system, system_file, system_sha256,
                 ollama_url, seed_start, max_samples, no_validate, no_repair=False,
                 tri_budget=DEFAULT_TRI_BUDGET):
    """Sample until valid, assembled and within budget, then write OUT_DIR/asset.glb and result.json.

    Returns (result, exit_code): exit 0 when the picked candidate is valid, else 2.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    attempts, candidates = [], []
    for index in range(max_samples):
        seed = seed_start + index
        attempt_dir = out / "attempts" / str(seed)
        (attempt_dir / "raw").mkdir(parents=True, exist_ok=True)
        brief = {"id": ATTEMPT_ID, "brief": prompt, "kind": kind}
        try:
            raw = teacher_generate.call_ollama(
                model_row["model"], system, brief, chat_args(model_row, ollama_url, seed)
            )
        except Exception as e:  # a failed call is recorded, not fatal, so the loop can continue
            print(f"error: seed {seed}: {e}", file=sys.stderr)
            row = {"id": ATTEMPT_ID, "ok": False, "reasons": ["request_error"], "stats": {}}
            attempts.append(attempt_record(seed, False, ["request_error"], False, None, None, 0.0))
            candidates.append(candidate(seed, attempt_dir, row, kind, index))
            continue

        raw["seed"] = seed
        raw["system_file"] = system_file
        raw["system_sha256"] = system_sha256
        (attempt_dir / "raw" / f"{ATTEMPT_ID}.json").write_text(json.dumps(raw))
        (attempt_dir / "page.html").write_text(extract_html(raw.get("content") or "") or "")

        if no_validate:
            attempts.append(attempt_record(seed, False, ["not_validated"], False, None, None, 0.0))
            candidates.append(candidate(seed, attempt_dir, {"id": ATTEMPT_ID, "ok": False,
                                                            "reasons": ["not_validated"], "stats": {}}, kind, index))
            continue

        record, cand = validate_attempt(attempt_dir, seed, kind, raw, index, tri_budget=tri_budget)
        attempts.append(record)
        candidates.append(cand)
        if record["ok"] and record["assembled"] and record["within_budget"]:
            break

    if not no_repair and not any(attempt["ok"] for attempt in attempts):
        # Every sample failed: one error repair turn on the first repairable failure (docs/14 section 5).
        seed = repairable_seed(candidates)
        source = next((c for c in candidates if c["seed"] == seed), None)
        if source is not None:
            record, cand = repair_turn(
                source, out, model_row, system, system_file, system_sha256, ollama_url, len(candidates),
                tri_budget=tri_budget,
            )
            attempts.append(record)
            candidates.append(cand)
    elif not no_repair and any(attempt["ok"] for attempt in attempts) \
            and not any(attempt["assembled"] for attempt in attempts):
        # Valid samples exist but none is assembled: one assembly repair turn on the best of them.
        ok_candidates = [c for c in candidates if (c["row"] or {}).get("ok")]
        source = glb_best_of.pick(ok_candidates) if ok_candidates else None
        if source is not None:
            record, cand = repair_turn(
                source, out, model_row, system, system_file, system_sha256, ollama_url, len(candidates),
                tri_budget=tri_budget, mode="assembly",
            )
            attempts.append(record)
            candidates.append(cand)

    winner = glb_best_of.pick(candidates) if candidates else None
    if winner is not None and winner["glb"].exists():
        shutil.copyfile(winner["glb"], out / "asset.glb")

    result = {
        "prompt": prompt,
        "kind": kind,
        "attempts": attempts,
        "picked_seed": winner["seed"] if winner is not None else None,
        "picked_ok": bool(winner is not None and winner["rank_keys"][0]),
        "picked_assembled": bool(winner is not None and winner["rank_keys"][1]),
        "picked_within_budget": bool(winner is not None and winner.get("within_budget")),
        "total_seconds": sum(attempt["seconds"] for attempt in attempts),
        "system_sha256": system_sha256,
        "assembly_repairs_used": sum(1 for attempt in attempts if attempt.get("repair") == "assembly"),
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result, (0 if result["picked_ok"] else 2)


def load_briefs(briefs_path, ids_file=None, limit=0):
    """The batch's briefs: the JSONL file, restricted by --ids-file, then capped by --limit."""
    briefs = [json.loads(line) for line in Path(briefs_path).read_text().splitlines() if line.strip()]
    if ids_file:
        wanted = set(teacher_generate.read_ids_file(ids_file))
        briefs = [brief for brief in briefs if brief["id"] in wanted]
    if limit:
        briefs = briefs[:limit]
    return briefs


def batch_row(brief_id, result):
    """One summary-table row from a brief's result.json (samples counts the generation samples only)."""
    attempts = result.get("attempts") or []
    return {
        "id": brief_id,
        "ok": bool(result.get("picked_ok")),
        "assembled": bool(result.get("picked_assembled")),
        "within_budget": bool(result.get("picked_within_budget")),
        "samples": len([a for a in attempts if not a.get("repair")]),
        "seconds": result.get("total_seconds") or 0.0,
        "repair": any(a.get("repair") for a in attempts),
        "assembly_repair": (result.get("assembly_repairs_used") or 0) > 0,
    }


def batch_summary(rows):
    """OUT_DIR/summary.json (docs/14 US-003): the batch totals over every brief's result.json."""
    samples = [row["samples"] for row in rows]
    seconds = [row["seconds"] for row in rows]
    return {
        "briefs": len(rows),
        "picked_ok": sum(1 for row in rows if row["ok"]),
        "picked_assembled": sum(1 for row in rows if row["assembled"]),
        "picked_within_budget": sum(1 for row in rows if row["within_budget"]),
        "mean_samples": round(sum(samples) / len(samples), 4) if samples else 0.0,
        "mean_seconds": round(sum(seconds) / len(seconds), 4) if seconds else 0.0,
        "repairs_used": sum(1 for row in rows if row["repair"]),
        "assembly_repairs_used": sum(1 for row in rows if row["assembly_repair"]),
    }


def print_summary_table(rows, summary):
    """The one-screen table: one line per brief plus the totals."""
    print(f"{'id':<20} {'ok':<3} {'asm':<3} {'bud':<3} {'samples':>7} {'seconds':>8} {'repair':<6}")
    for row in rows:
        print(f"{row['id']:<20} {'y' if row['ok'] else 'n':<3} {'y' if row['assembled'] else 'n':<3} "
              f"{'y' if row['within_budget'] else 'n':<3} {row['samples']:>7} {row['seconds']:>8.2f} "
              f"{'y' if row['repair'] else '-':<6}")
    print(
        f"total {summary['picked_ok']}/{summary['briefs']} ok, "
        f"{summary['picked_assembled']}/{summary['briefs']} assembled, "
        f"{summary['picked_within_budget']}/{summary['briefs']} within budget, "
        f"mean {summary['mean_samples']:.2f} samples, {summary['mean_seconds']:.2f} s per brief, "
        f"{summary['repairs_used']} repair(s), {summary['assembly_repairs_used']} assembly repair(s)"
    )


def generate_batch(briefs, out_root, model_row, system, system_file, system_sha256,
                   ollama_url, seed_start, max_samples, no_validate, no_repair,
                   tri_budget=DEFAULT_TRI_BUDGET):
    """Run the loop for each brief into OUT_ROOT/<id>/, skipping a finished result.json.

    Returns (summary, exit_code): exit 0 when every brief's pick is valid, else 2. The summary is
    recomputed from every brief's result.json, so a rerun (which skips generation) still reports it.
    """
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for brief in briefs:
        brief_id = brief["id"]
        out = out_root / brief_id
        result_path = out / "result.json"
        if result_path.exists():  # resumable: a finished brief is never requested again
            result = json.loads(result_path.read_text())
        else:
            result, _ = generate_run(
                brief["brief"], brief.get("kind") or "static", out, model_row, system, system_file,
                system_sha256, ollama_url, seed_start, max_samples, no_validate, no_repair,
                tri_budget=tri_budget,
            )
        rows.append(batch_row(brief_id, result))
    summary = batch_summary(rows)
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print_summary_table(rows, summary)
    return summary, (0 if summary["picked_ok"] == summary["briefs"] else 2)


def build_parser():
    """The argument parser, so a test can parse a command line without running anything."""
    ap = argparse.ArgumentParser(description="Generate one GLB from a prompt, sampling until valid and assembled (docs/14).")
    ap.add_argument("prompt", nargs="?", help="the asset brief (or use --briefs FILE)")
    ap.add_argument("--briefs", default=None, help="briefs JSONL; run the loop for each brief into OUT_DIR/<id>/ (mutually exclusive with PROMPT)")
    ap.add_argument("--limit", type=int, default=0, help="with --briefs: run at most N briefs (applied after --ids-file)")
    ap.add_argument("--ids-file", default=None, help="with --briefs: only the brief ids listed (one per line, blank lines and # comments ignored)")
    ap.add_argument("--kind", choices=("static", "animated", "set"), default="static")
    ap.add_argument("--out-dir", required=True, help="output directory (outside data/, out/ and eval/)")
    ap.add_argument("--max-samples", type=int, default=3, help="most samples to spend (default 3)")
    ap.add_argument("--seed-start", type=int, default=1, help="first sampling seed (default 1)")
    ap.add_argument("--tri-budget", type=int, default=DEFAULT_TRI_BUDGET,
                    help=f"stop only at a candidate at or under this many triangles (default {DEFAULT_TRI_BUDGET})")
    ap.add_argument("--model-row", default="glimmer-v3", help="model name from --models (default glimmer-v3)")
    ap.add_argument("--models", default="bench/glb/models.json", help="the model rows file")
    ap.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama server for generation")
    ap.add_argument("--allow-paid", action="store_true", help="allow a model row with paid true")
    ap.add_argument("--no-validate", action="store_true", help="generate only; do not run the validator")
    ap.add_argument("--no-repair", action="store_true", help="do not repair when no sample is valid")
    return ap


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)

    if bool(a.prompt) == bool(a.briefs):
        ap.error("give either a positional PROMPT or --briefs FILE (not both and not neither)")
    if a.limit and not a.briefs:
        ap.error("--limit needs --briefs")
    if a.ids_file and not a.briefs:
        ap.error("--ids-file needs --briefs")

    try:
        check_out_dir(a.out_dir)
        models = glb_bench.load_models(a.models)
        model_row = find_model(models, a.model_row)
        glb_bench.check_paid([model_row], a.allow_paid)
        system_path = glb_bench.resolve_path(model_row["system"])
        if not system_path.exists():
            raise GenerateError(f"{model_row['name']}: system prompt file not found: {system_path}")
        briefs = load_briefs(a.briefs, a.ids_file, a.limit) if a.briefs else None
    except (GenerateError, glb_bench.BenchError, OSError) as e:
        ap.error(str(e))

    system = system_path.read_text()
    system_sha256 = hashlib.sha256(system.encode()).hexdigest()

    if a.briefs:
        _, code = generate_batch(
            briefs, a.out_dir, model_row, system, str(model_row["system"]), system_sha256,
            a.ollama_url, a.seed_start, a.max_samples, a.no_validate, a.no_repair, a.tri_budget,
        )
        return code

    result, code = generate_run(
        a.prompt, a.kind, a.out_dir, model_row, system, str(model_row["system"]), system_sha256,
        a.ollama_url, a.seed_start, a.max_samples, a.no_validate, a.no_repair, a.tri_budget,
    )
    print(
        f"samples {len(result['attempts'])}, picked seed {result['picked_seed']}, "
        f"ok {result['picked_ok']}, assembled {result['picked_assembled']}, "
        f"within budget {result['picked_within_budget']}"
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
