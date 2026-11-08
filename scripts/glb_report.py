"""Report the GLB benchmark metrics of docs/13 section 5.3, with Wilson intervals.

Reads <root>/<model>/validation.jsonl and <root>/<model>/raw/*.json for every subfolder that has a
validation report, plus the briefs file, and writes <root>/report.json and <root>/report.md. A brief
that a model never validated counts as a failure with the reason 'missing'.
"""
import argparse
import csv
import json
import math
import statistics
from pathlib import Path

LOW_POLY = 5000


def wilson(k, n, z=1.96):
    """95 % Wilson score interval for k successes out of n. Returns (low, high)."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, center - margin), min(1.0, center + margin)


def load_briefs(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def load_model(directory):
    """Load one model folder. Returns {'rows', 'raws', 'assembly'} (assembly is None without assembly.jsonl)."""
    directory = Path(directory)
    rows = []
    report = directory / "validation.jsonl"
    if report.exists():
        rows = [json.loads(line) for line in report.read_text().splitlines() if line.strip()]
    raws = {}
    raw_dir = directory / "raw"
    if raw_dir.is_dir():
        for path in sorted(raw_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            raws[raw.get("id") or path.stem] = raw
    assembly = None
    assembly_file = directory / "assembly.jsonl"
    if assembly_file.exists():
        assembly = [
            json.loads(line) for line in assembly_file.read_text().splitlines() if line.strip()
        ]
    return {"rows": rows, "raws": raws, "assembly": assembly}


def _median(values):
    return statistics.median(values) if values else None


def assembly_summary(rows, assembly_rows=None):
    """Assembled share and median parts over valid rows (docs/14 section 4).

    Prefers a parsed assembly.jsonl (kind-aware) when given, else reads stats.glb.assembly from the
    validation rows. Returns None when there is no assembly data at all.
    """
    valid = 0
    assembled = 0
    parts = []
    if assembly_rows is not None:
        for line in assembly_rows:
            result = line.get("assembly")
            if not result:
                continue
            valid += 1
            if result.get("assembled"):
                assembled += 1
            if isinstance(result.get("parts"), (int, float)):
                parts.append(result["parts"])
    else:
        for row in rows:
            result = ((row.get("stats") or {}).get("glb") or {}).get("assembly")
            if not row.get("ok") or not result:
                continue
            valid += 1
            if result.get("assembled"):
                assembled += 1
            if isinstance(result.get("parts"), (int, float)):
                parts.append(result["parts"])
    if not valid:
        return None
    return {
        "valid": valid,
        "assembled": assembled,
        "share": assembled / valid,
        "median_parts": _median(parts),
    }


def metrics(rows, raws, briefs, assembly_rows=None):
    """Compute the docs/13 section 5.3 metrics over every brief."""
    by_id = {row["id"]: row for row in rows}
    n = len(briefs)
    passed = []
    exported = 0
    reasons = {}
    triangles = []
    animated_total = animated_pass = 0
    by_domain = {}

    for brief in briefs:
        brief_id = brief["id"]
        domain = brief.get("domain")
        bucket = by_domain.setdefault(domain, {"pass": 0, "total": 0})
        bucket["total"] += 1

        row = by_id.get(brief_id)
        if row is None:
            reasons["missing"] = reasons.get("missing", 0) + 1
            ok, glb = False, None
        else:
            ok = bool(row.get("ok"))
            glb = (row.get("stats") or {}).get("glb")
            if glb:
                exported += 1
            if not ok:
                for reason in row.get("reasons") or []:
                    reasons[reason] = reasons.get(reason, 0) + 1

        if ok:
            bucket["pass"] += 1
            passed.append(brief_id)
            if glb and isinstance(glb.get("triangles"), (int, float)):
                triangles.append(glb["triangles"])

        if brief.get("kind") == "animated":
            animated_total += 1
            if ok and glb and (glb.get("animations") or 0) > 0:
                animated_pass += 1

    tokens, seconds = [], []
    for brief in briefs:
        usage = (raws.get(brief["id"]) or {}).get("usage") or {}
        if isinstance(usage.get("completion_tokens"), (int, float)):
            tokens.append(usage["completion_tokens"])
        if isinstance(usage.get("seconds"), (int, float)):
            seconds.append(usage["seconds"])

    low, high = wilson(len(passed), n)
    return {
        "n": n,
        "pass": len(passed),
        "pass_rate": len(passed) / n if n else None,
        "wilson": (low, high),
        "export": exported,
        "export_rate": exported / n if n else None,
        "animated": {
            "pass": animated_pass,
            "total": animated_total,
            "rate": animated_pass / animated_total if animated_total else None,
        },
        "triangles": {
            "median": _median(triangles),
            "max": max(triangles) if triangles else None,
            "share_le_5000": (
                sum(1 for value in triangles if value <= LOW_POLY) / len(passed) if passed else None
            ),
        },
        "failures": dict(sorted(reasons.items())),
        "cost": {
            "median_completion_tokens": _median(tokens),
            "median_seconds": _median(seconds),
            "total_seconds": sum(seconds) if seconds else None,
        },
        "by_domain": by_domain,
        "assembly": assembly_summary(rows, assembly_rows),
    }


def head_to_head(a, b):
    """Compare two {brief_id: passed} maps. Returns both/only_a/only_b/neither counts."""
    counts = {"both": 0, "only_a": 0, "only_b": 0, "neither": 0}
    for brief_id in sorted(set(a) | set(b)):
        passed_a, passed_b = bool(a.get(brief_id)), bool(b.get(brief_id))
        if passed_a and passed_b:
            counts["both"] += 1
        elif passed_a:
            counts["only_a"] += 1
        elif passed_b:
            counts["only_b"] += 1
        else:
            counts["neither"] += 1
    return counts


def recognisable(ratings, key_map, ids):
    """Share of ids rated 1 or 2. A missing key, missing row or empty rating counts as 0."""
    by_key = {row.get("key"): row for row in ratings}
    id_to_key = {info.get("id"): key for key, info in key_map.items()}
    if not ids:
        return None
    good = 0
    for brief_id in ids:
        row = by_key.get(id_to_key.get(brief_id))
        if row is not None and str(row.get("rating", "")).strip() in {"1", "2"}:
            good += 1
    return good / len(ids)


def good_rate(ratings, key_map, ids):
    """Share of ids rated exactly 2 (docs/14 section 1, secondary). Missing rows count as 0."""
    by_key = {row.get("key"): row for row in ratings}
    id_to_key = {info.get("id"): key for key, info in key_map.items()}
    if not ids:
        return None
    good = 0
    for brief_id in ids:
        row = by_key.get(id_to_key.get(brief_id))
        if row is not None and str(row.get("rating", "")).strip() == "2":
            good += 1
    return good / len(ids)


def merge_validation_rows(base_rows, repair_rows):
    """Base rows with each repaired-ok row replacing a failing original (docs/14 section 5)."""
    by_id = {row["id"]: row for row in base_rows}
    order = [row["id"] for row in base_rows]
    for row in repair_rows:
        if row["id"] not in by_id:
            order.append(row["id"])
            by_id[row["id"]] = row
        elif row.get("ok") and not by_id[row["id"]].get("ok"):
            by_id[row["id"]] = row
    return [by_id[brief_id] for brief_id in order]


def merge_assembly_rows(base_lines, repair_lines):
    """Merge two assembly.jsonl line lists by id, a repaired line winning when it has a result."""
    if base_lines is None and repair_lines is None:
        return None
    by_id = {}
    order = []
    for line in (base_lines or []) + (repair_lines or []):
        if line["id"] not in by_id:
            order.append(line["id"])
            by_id[line["id"]] = line
        elif line.get("assembly"):
            by_id[line["id"]] = line
    return [by_id[brief_id] for brief_id in order]


def merge_by_ids(base_items, repair_items, ids):
    """Base rows or assembly lines with the repaired item substituted for each id in `ids` (imp-2).

    Only the ids the assembly repair was applied to (`summary.json` `ids_repaired`) take the repaired
    ok/assembly values; every other brief keeps the original run's item.
    """
    replaced = set(ids)
    repair_by_id = {item["id"]: item for item in repair_items or []}
    merged = []
    seen = set()
    for item in base_items or []:
        brief_id = item["id"]
        merged.append(repair_by_id[brief_id] if brief_id in replaced and brief_id in repair_by_id else item)
        seen.add(brief_id)
    for item in repair_items or []:
        if item["id"] in replaced and item["id"] not in seen:
            merged.append(item)
            seen.add(item["id"])
    return merged


def repaired_ids(directory, repair_rows):
    """The ids an assembly repair was applied to: `summary.json` `ids_repaired`, else the repair rows."""
    summary_file = Path(directory) / "summary.json"
    if summary_file.exists():
        ids = json.loads(summary_file.read_text()).get("ids_repaired")
        if ids is not None:
            return ids
    return [row["id"] for row in repair_rows]


def load_extra_run(name, directory):
    """Load one --extra-runs entry.

    A `repair` directory becomes '<model> after 1 repair', merged with its parent run so its pass
    count is the original ok ids plus the repaired ids. A `repair-asm` directory becomes '<model>
    after assembly repair': the ids in its `summary.json` `ids_repaired` take the repaired ok and
    assembled values, every other brief keeps the original run's (imp-2 US-003).
    """
    directory = Path(directory)
    parent = directory.parent
    if directory.name == "repair-asm" and (parent / "validation.jsonl").exists():
        base = load_model(parent)
        repair = load_model(directory)
        ids = repaired_ids(directory, repair["rows"])
        loaded = {
            "rows": merge_by_ids(base["rows"], repair["rows"], ids),
            "raws": {**base["raws"], **repair["raws"]},
            "assembly": (
                None if base["assembly"] is None and repair["assembly"] is None
                else merge_by_ids(base["assembly"], repair["assembly"], ids)
            ),
        }
        return f"{parent.name} after assembly repair", loaded
    if directory.name == "repair" and (parent / "validation.jsonl").exists():
        base = load_model(parent)
        repair = load_model(directory)
        loaded = {
            "rows": merge_validation_rows(base["rows"], repair["rows"]),
            "raws": {**base["raws"], **repair["raws"]},
            "assembly": merge_assembly_rows(base["assembly"], repair["assembly"]),
        }
        return f"{parent.name} after 1 repair", loaded
    return (name or directory.name), load_model(directory)


def build_report(root, briefs_path, ratings_path=None, key_map_path=None, extra_runs=None):
    root = Path(root)
    briefs = load_briefs(briefs_path)
    brief_ids = [brief["id"] for brief in briefs]
    models = {}
    pass_maps = {}

    loaded_models = {}
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        if not (directory / "validation.jsonl").exists():
            continue
        loaded_models[directory.name] = load_model(directory)
    for name, directory in extra_runs or []:
        label, loaded = load_extra_run(name, directory)
        loaded_models[label] = loaded

    for name, loaded in loaded_models.items():
        models[name] = metrics(loaded["rows"], loaded["raws"], briefs, loaded["assembly"])
        pass_maps[name] = {row["id"]: bool(row.get("ok")) for row in loaded["rows"]}

    ratings = []
    key_map = None
    if ratings_path:
        ratings = list(csv.DictReader(Path(ratings_path).open()))
        key_map = json.loads(Path(key_map_path).read_text())
        for name, result in models.items():
            model_map = {k: v for k, v in key_map.items() if v.get("model") == name}
            result["recognisable"] = recognisable(ratings, model_map, brief_ids)
            result["good_rate"] = good_rate(ratings, model_map, brief_ids)

    head = {}
    names = list(models)
    for i, name_a in enumerate(names):
        for name_b in names[i + 1:]:
            head[f"{name_a} vs {name_b}"] = head_to_head(pass_maps[name_a], pass_maps[name_b])

    return {"briefs": len(briefs), "models": models, "head_to_head": head}


def _percent(value):
    return "n/a" if value is None else f"{value:.1%}"


def _number(value):
    if value is None:
        return "n/a"
    return f"{value:g}" if isinstance(value, float) else str(value)


def render_markdown(report):
    models = report["models"]
    names = list(models)
    lines = ["# GLB benchmark report", "", f"Briefs: {report['briefs']}", ""]

    lines.append("## Models")
    lines.append("")
    header = [
        "Model", "Pass (95% Wilson)", "Export", "Animated pass", "Median triangles",
        "Max triangles", "Share <= 5000 tris", "Recognisable", "Median tokens",
        "Median seconds", "Total seconds",
        "Assembled (of valid)", "Assembled (of all briefs)", "Median parts",
        "Good (rated 2), secondary",
    ]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join("---" for _ in header) + "|")
    for name in names:
        m = models[name]
        low, high = m["wilson"]
        assembly = m.get("assembly")
        assembled_cell = "not computed"
        assembled_all_cell = "not computed"
        parts_cell = "not computed"
        if assembly:
            assembled_cell = f"{assembly['assembled']}/{assembly['valid']} ({_percent(assembly['share'])})"
            share_all = assembly["assembled"] / report["briefs"] if report["briefs"] else None
            assembled_all_cell = (
                f"{assembly['assembled']}/{report['briefs']} ({_percent(share_all)})"
            )
            parts_cell = _number(assembly["median_parts"])
        lines.append("| " + " | ".join([
            name,
            f"{_percent(m['pass_rate'])} ({low:.1%}-{high:.1%})",
            _percent(m["export_rate"]),
            f"{m['animated']['pass']}/{m['animated']['total']} ({_percent(m['animated']['rate'])})",
            _number(m["triangles"]["median"]),
            _number(m["triangles"]["max"]),
            _percent(m["triangles"]["share_le_5000"]),
            _percent(m.get("recognisable")) if "recognisable" in m else "not rated",
            _number(m["cost"]["median_completion_tokens"]),
            _number(m["cost"]["median_seconds"]),
            _number(m["cost"]["total_seconds"]),
            assembled_cell,
            assembled_all_cell,
            parts_cell,
            _percent(m.get("good_rate")) if "good_rate" in m else "not rated",
        ]) + " |")
    lines.append("")

    lines.append("## Failures")
    lines.append("")
    reasons = sorted({reason for m in models.values() for reason in m["failures"]})
    lines.append("| Reason | " + " | ".join(names) + " |")
    lines.append("|" + "|".join("---" for _ in range(len(names) + 1)) + "|")
    for reason in reasons:
        counts = [str(models[name]["failures"].get(reason, 0)) for name in names]
        lines.append("| " + " | ".join([reason] + counts) + " |")
    lines.append("")

    lines.append("## By domain")
    lines.append("")
    domains = sorted({domain for m in models.values() for domain in m["by_domain"]})
    lines.append("| Domain | " + " | ".join(names) + " |")
    lines.append("|" + "|".join("---" for _ in range(len(names) + 1)) + "|")
    for domain in domains:
        cells = []
        for name in names:
            bucket = models[name]["by_domain"].get(domain, {"pass": 0, "total": 0})
            cells.append(f"{bucket['pass']}/{bucket['total']}")
        lines.append("| " + " | ".join([str(domain)] + cells) + " |")
    lines.append("")

    lines.append("## Head to head")
    lines.append("")
    lines.append("| Pair | Both pass | Only first | Only second | Neither |")
    lines.append("|---|---|---|---|---|")
    for pair, counts in report["head_to_head"].items():
        lines.append(
            f"| {pair} | {counts['both']} | {counts['only_a']} | {counts['only_b']} | {counts['neither']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compare GLB benchmark models on the docs/13 5.3 metrics.")
    ap.add_argument("--root", required=True, help="benchmark root with one folder per model")
    ap.add_argument("--briefs", required=True, help="briefs JSONL scored by every model")
    ap.add_argument("--ratings", default=None, help="rating.csv from glb_sheet.mjs")
    ap.add_argument("--key-map", default=None, help="key_map.json (default: beside rating.csv)")
    ap.add_argument(
        "--extra-runs", action="append", default=[], metavar="NAME=DIR",
        help="add a derived run as an extra row (repeatable); a repair directory is labelled "
             "'<model> after 1 repair' and merges its parent's passes, and a repair-asm directory is "
             "labelled '<model> after assembly repair' and takes the repaired ids from its summary.json",
    )
    a = ap.parse_args(argv)

    if a.ratings:
        key_map = a.key_map or str(Path(a.ratings).parent / "key_map.json")
        if not Path(key_map).exists():
            ap.error(f"key map not found: {key_map}")
    else:
        key_map = None

    extra_runs = []
    for value in a.extra_runs:
        if "=" not in value:
            ap.error(f"--extra-runs must be NAME=DIR, got: {value}")
        name, directory = value.split("=", 1)
        if not (Path(directory) / "validation.jsonl").exists():
            ap.error(f"--extra-runs has no validation.jsonl: {directory}")
        extra_runs.append((name, directory))

    root = Path(a.root)
    report = build_report(root, a.briefs, a.ratings, key_map, extra_runs)
    (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    markdown = render_markdown(report)
    (root / "report.md").write_text(markdown + "\n")
    print(markdown)


if __name__ == "__main__":
    main()
