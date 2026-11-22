"""One-shot repair retry for failing GLB pages (docs/14 section 5).

For each id in RUN/validation.jsonl that failed with a repairable reason, send the model one
more /api/chat call: the system prompt, the original brief, the answer it wrote, then a fix
message that quotes the failure. The corrected answer is validated like the bench validates a run.
Resumable: an id whose RAW/repair/raw/<id>.json already exists is never requested again.

`--mode assembly` (imp-2) instead feeds back a valid page whose asset is not assembled, quoting
the assembly numbers (separate groups, the largest group's share, floaters and the ground gap).
Its output goes to RAW/repair-asm/ and its summary adds `assembled_after`. It also writes
RAW/repair-asm/assembly.jsonl (imp-3): one `{id, kind, assembly}` line per selected id, so the
report's assembly-repair row reads the repaired assembled values, not the originals.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import glb_bench

ROOT = Path(__file__).resolve().parent.parent

# A reason the model can plausibly fix by changing its own page.
REPAIRABLE_REASONS = (
    "js_error",
    "load_fail",
    "no_download",
    "export_error",
    "bad_glb",
    "empty_glb",
    "nan_transform",
    "nan_geometry",
    "no_export_button",
)
# Extra hint per reason, appended to the fix message when the reason is present.
REASON_HINTS = {
    "nan_transform": (
        "Some parts have a position, rotation or scale that is NaN (for example from an undefined variable or "
        "a division by zero in a loop), so they vanish and the GLB is invalid. Compute every position from "
        "defined numbers."
    ),
    "nan_geometry": (
        "Some geometry has NaN vertex positions (for example a size or radius computed from an undefined "
        "variable), so the GLB is invalid. Build every shape from defined numbers."
    ),
}
# Not one-line bugs: the answer was cut off, never produced a page, or leans on the network.
SKIP_REASONS = {"truncated", "no_html", "external_dep"}

# Assembly mode only feeds a valid but under-assembled asset back when it has at least this many
# parts; a 1-2 part asset has nothing to assemble (docs/14 section 2; imp-2).
ASSEMBLY_MIN_PARTS = 3

# The same generation options teacher_generate.py sends on the native /api/chat route.
NUM_CTX = 49152
NUM_PREDICT = 40000

FORBIDDEN_ROOTS = (ROOT / "data", ROOT / "out", ROOT / "eval")


class RepairError(Exception):
    pass


def read_rows(path):
    """Parse a JSONL file into a list, or [] when it does not exist."""
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def check_run_dir(run_dir):
    """Refuse a --run under data/, out/ or eval/ (docs/14 section 5)."""
    run = Path(run_dir).resolve()
    for base in FORBIDDEN_ROOTS:
        base = base.resolve()
        if run == base or base in run.parents:
            raise RepairError(f"--run must not be inside {base.relative_to(ROOT)}/ ({run})")


def find_model(models, name):
    for model in models:
        if model["name"] == name:
            return model
    raise RepairError(f"unknown --model-row: {name}")


def select_ids(rows):
    """Ids to repair, in file order: not ok, repairable and never one of the skip reasons."""
    selected = []
    for row in rows:
        if row.get("ok"):
            continue
        reasons = set(row.get("reasons") or [])
        if not reasons or reasons & SKIP_REASONS:
            continue
        if reasons & set(REPAIRABLE_REASONS):
            selected.append(row["id"])
    return selected


def select_assembly_ids(rows, assembly_by_id, min_parts=ASSEMBLY_MIN_PARTS):
    """Ids to repair in assembly mode, in file order: ok, not assembled and at least min_parts parts.

    `assembly_by_id` maps id -> {id, kind, assembly} (the assembly.jsonl entry). A row without an
    entry, with a null assembly or with fewer than min_parts is skipped.
    """
    selected = []
    for row in rows:
        if not row.get("ok"):
            continue
        entry = assembly_by_id.get(row["id"])
        if not entry:
            continue
        asm = entry.get("assembly")
        if not asm or asm.get("assembled"):
            continue
        if (asm.get("parts") or 0) < min_parts:
            continue
        selected.append(row["id"])
    return selected


def repair_messages(system, brief_text, original_content, fix):
    """The exact four-message list of docs/14 section 5."""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": brief_text},
        {"role": "assistant", "content": original_content},
        {"role": "user", "content": fix},
    ]


def fix_message(row):
    """The fix message text of docs/14 section 5."""
    reasons = ", ".join(row.get("reasons") or [])
    error = (row.get("stats") or {}).get("error") or "none recorded"
    return (
        f"The page you wrote failed when tested: {reasons}. "
        f"First error: {error}. "
        "Reply with the complete corrected HTML file in one ```html block. "
        "Keep the asset the same and fix only what is broken. "
        "Remember the GLB exporter rules in the system prompt."
        + "".join(" " + REASON_HINTS[r] for r in (row.get("reasons") or []) if r in REASON_HINTS)
    )


def assembly_fix_message(assembly):
    """The assembly fix message text (imp-2): the group, percent, floater and ground numbers.

    Percent and metres are rounded to 2 decimals.
    """
    components = assembly.get("components", 0)
    percent = round(float(assembly.get("largest_share", 0.0)) * 100, 2)
    floaters = assembly.get("floaters", 0)
    ground = round(float(assembly.get("ground_gap", 0.0)), 2)
    return (
        f"Your page works, but the exported model is not assembled: it has {components} separate "
        f"groups of parts (largest group holds {percent}% of the parts), {floaters} parts float in "
        f"the air and the lowest point is {ground} above the ground. "
        "Reply with the complete corrected HTML file in one ```html block. "
        "Keep the same design and parts; only move or resize parts so they touch their neighbours, "
        "sit on the ground (lowest y = 0), and keep it in one THREE.Group named \"asset\"."
    )


def chat(messages, model_row, ollama_url, num_ctx=NUM_CTX, num_predict=NUM_PREDICT):
    """One /api/chat call with the whole message list, sampling from the model row."""
    options = {"num_ctx": num_ctx, "num_predict": num_predict}
    for key in ("temperature", "top_p", "top_k", "min_p"):
        value = model_row.get(key)
        if value is not None:
            options[key] = value
    body = {
        "model": model_row["model"],
        "stream": False,
        "think": bool(model_row.get("think")),
        "options": options,
        "messages": messages,
    }
    req = urllib.request.Request(
        ollama_url.rstrip("/") + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    r = json.load(urllib.request.urlopen(req, timeout=1800))
    m = r["message"]
    return {
        "content": (m.get("content") or "").strip(),
        "reasoning": m.get("thinking") or None,
        "finish_reason": "length" if r.get("done_reason") == "length" else "stop",
        "usage": {
            "completion_tokens": r.get("eval_count"),
            "prompt_tokens": r.get("prompt_eval_count"),
            "seconds": r.get("total_duration", 0) / 1e9,
        },
        "ts": time.time(),
    }


def validate_command(directory):
    """The GLB-mode validator command for a repair directory, matching the bench layout."""
    directory = Path(directory)
    return [
        "node", "scripts/validate_scenes.mjs", "--mode", "glb", "--allow-addons",
        "--raw", str(directory / "raw"),
        "--scenes", str(directory / "scenes"),
        "--shots", str(directory / "shots"),
        "--glb-dir", str(directory / "glb"),
        "--report", str(directory / "validation.jsonl"),
    ]


def validated_repairs(selected_ids, repair_rows):
    """The selected ids whose repair validation row is now ok."""
    ok = {row["id"] for row in repair_rows if row.get("ok")}
    return [brief_id for brief_id in selected_ids if brief_id in ok]


def validated_assembly(selected_ids, repair_rows):
    """The selected ids whose repair row is ok and reports the repaired asset as assembled."""
    by_id = {row["id"]: row for row in repair_rows}
    assembled = []
    for brief_id in selected_ids:
        row = by_id.get(brief_id)
        if not row or not row.get("ok"):
            continue
        asm = ((row.get("stats") or {}).get("glb") or {}).get("assembly") or {}
        if asm.get("assembled"):
            assembled.append(brief_id)
    return assembled


def brief_kind(raw_dir, brief_id):
    """The brief kind from a repair raw row, or None when the file is absent."""
    path = Path(raw_dir) / f"{brief_id}.json"
    if not path.exists():
        return None
    return (json.loads(path.read_text()).get("brief") or {}).get("kind")


def assembly_lines(selected_ids, repair_rows, assembly_by_id, raw_dir):
    """The `repair-asm/assembly.jsonl` lines (imp-3), one per selected id.

    The assembly comes from the repair validation row's `stats.glb.assembly`, or `null` when the row
    is missing or not ok. The kind comes from the original `assembly.jsonl` entry, else the brief.
    """
    by_id = {row["id"]: row for row in repair_rows}
    lines = []
    for brief_id in selected_ids:
        row = by_id.get(brief_id)
        asm = None
        if row and row.get("ok"):
            asm = ((row.get("stats") or {}).get("glb") or {}).get("assembly")
        kind = assembly_by_id.get(brief_id, {}).get("kind")
        if kind is None:
            kind = brief_kind(raw_dir, brief_id)
        lines.append({"id": brief_id, "kind": kind, "assembly": asm})
    return lines


def build_parser():
    """The argument parser, so a test can parse a command line without running anything."""
    ap = argparse.ArgumentParser(description="Feed each repairable failure back to the model once (docs/14 section 5).")
    ap.add_argument("--run", required=True, help="model run directory with validation.jsonl and raw/")
    ap.add_argument("--model-row", required=True, help="model name from models.json")
    ap.add_argument("--models", default="bench/glb/models.json")
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    ap.add_argument("--limit", type=int, default=0, help="stop after N selected ids")
    ap.add_argument("--mode", choices=("error", "assembly"), default="error",
                    help="error: repair pages that failed (default); assembly: repair valid but unassembled pages")
    ap.add_argument("--no-validate", action="store_true", help="generate only; do not run validate_scenes.mjs")
    ap.add_argument("--allow-paid", action="store_true", help="allow a model row with paid true")
    return ap


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)

    try:
        check_run_dir(a.run)
        models = glb_bench.load_models(a.models)
        model_row = find_model(models, a.model_row)
        glb_bench.check_paid([model_row], a.allow_paid)
    except (RepairError, glb_bench.BenchError) as e:
        ap.error(str(e))

    run = Path(a.run)
    system_path = glb_bench.resolve_path(model_row["system"])
    if not system_path.exists():
        ap.error(f"{model_row['name']}: system prompt file not found: {system_path}")
    system = system_path.read_text()
    system_file = str(model_row["system"])
    system_sha256 = hashlib.sha256(system.encode()).hexdigest()

    rows = read_rows(run / "validation.jsonl")
    by_id = {row["id"]: row for row in rows}
    assembly_by_id = {row["id"]: row for row in read_rows(run / "assembly.jsonl")}
    if a.mode == "assembly":
        selected = select_assembly_ids(rows, assembly_by_id)
    else:
        selected = select_ids(rows)
    if a.limit:
        selected = selected[: a.limit]

    repair = run / ("repair-asm" if a.mode == "assembly" else "repair")
    raw_out = repair / "raw"
    raw_out.mkdir(parents=True, exist_ok=True)

    attempted = 0
    for brief_id in selected:
        out_file = raw_out / f"{brief_id}.json"
        if out_file.exists():  # resumable: already written, never requested again
            continue
        orig_file = run / "raw" / f"{brief_id}.json"
        if not orig_file.exists():
            print(f"skip {brief_id}: original raw not found", file=sys.stderr)
            continue
        orig = json.loads(orig_file.read_text())
        if a.mode == "assembly":
            fix = assembly_fix_message(assembly_by_id[brief_id]["assembly"])
        else:
            fix = fix_message(by_id[brief_id])
        messages = repair_messages(
            system, (orig.get("brief") or {}).get("brief", ""), orig.get("content", ""), fix
        )
        try:
            result = chat(messages, model_row, a.ollama_url)
        except Exception as e:  # a failed call is not saved, so a rerun retries it
            print(f"error {brief_id}: {e}", file=sys.stderr)
            continue
        result.update({
            "id": brief_id, "brief": orig.get("brief"), "model": model_row["model"],
            "repair_of": brief_id, "fix_message": fix,
            "system_file": system_file, "system_sha256": system_sha256,
        })
        out_file.write_text(json.dumps(result))
        attempted += 1

    if not a.no_validate:
        rc = subprocess.run(validate_command(repair)).returncode
        if rc:
            raise SystemExit(rc)

    repair_rows = read_rows(repair / "validation.jsonl")
    repaired_ids = validated_repairs(selected, repair_rows)
    if a.mode == "assembly":
        lines = assembly_lines(selected, repair_rows, assembly_by_id, raw_out)
        (repair / "assembly.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    summary = {
        "mode": a.mode,
        "selected": len(selected),
        "attempted": attempted,
        "repaired": len(repaired_ids),
        "ids_repaired": repaired_ids,
        "model": model_row["name"],
        "system_file": system_file,
        "system_sha256": system_sha256,
    }
    if a.mode == "assembly":
        summary["assembled_after"] = len(validated_assembly(selected, repair_rows))
    (repair / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if a.mode == "assembly":
        print(f"repaired {len(repaired_ids)} of {len(selected)}, assembled after {summary['assembled_after']}")
    else:
        print(f"repaired {len(repaired_ids)} of {len(selected)}")


if __name__ == "__main__":
    main()
