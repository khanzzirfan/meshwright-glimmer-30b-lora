"""Build the phase 2 training set from ccore's validated parquet data (docs/14 section 7).

Reads the downloaded *.parquet shards, keeps ccore's own train/validation split and writes
DIR/train.jsonl and DIR/val.jsonl in the conversational prompt/completion format that
scripts/mesh_lora_hf.py reads (check_data). Reasoning traces are dropped (Glimmer runs without
thinking) and rows whose title matches an eval subject are removed, so phase 2 is never trained on
the 48 eval briefs. DIR/stats.json counts every drop reason, kept rows by domain and the input
hashes. --extra-run adds the valid, assembled rows of a Glimmer run with --extra-system, refusing
any id that is one of the eval briefs.
"""
import argparse
import collections
import hashlib
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_ROOTS = (ROOT / "data", ROOT / "out", ROOT / "eval")
DEFAULT_SYSTEM = "prompts/ccore_glb_system.txt"
DEFAULT_LEAK = "bench/glb/eval_subjects.json"
EVAL_BRIEFS = ROOT / "bench" / "glb" / "briefs.jsonl"

# The docs/14 section 7 drop rules, applied in this order; the first match wins.
DROP_REASONS = ("no_html", "too_long", "eval_subject", "duplicate")


class CcorePrepError(Exception):
    pass


def read_jsonl(path):
    """Parse a JSONL file into a list, or [] when it does not exist."""
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def resolve_path(value):
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def display_path(path):
    """A path relative to ROOT when possible, else the path as given."""
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_out_dir(out_dir):
    """Refuse --out under data/, out/ or eval/ (docs/14 section 7)."""
    out = Path(out_dir).resolve()
    for base in FORBIDDEN_ROOTS:
        base = base.resolve()
        if out == base or base in out.parents:
            raise CcorePrepError(f"--out must not be inside {base.relative_to(ROOT)}/ ({out})")


def load_leak_phrases(path):
    """Every subject phrase in a leak file: the values, skipping the _comment key."""
    data = json.loads(Path(path).read_text())
    phrases = []
    for key, value in data.items():
        if not key.startswith("_"):
            phrases.extend(value)
    return phrases


def title_is_eval_subject(title, phrases):
    """Whole-word, case-insensitive; a multi-word phrase matches as a phrase.

    So 'crate' drops 'Wooden Crate' but not 'Crater Lamp'.
    """
    text = (title or "").lower()
    return any(re.search(r"\b" + re.escape(phrase.lower()) + r"\b", text) for phrase in phrases)


def split_of(name):
    """train-*.parquet -> 'train', validation-*.parquet -> 'val', anything else -> None."""
    stem = Path(name).name.lower()
    if stem.startswith("train"):
        return "train"
    if stem.startswith("validation") or stem.startswith("val"):
        return "val"
    return None


def parse_conversation(messages):
    """(user text, answer text) from a ccore message list; reasoning_content and extra turns are dropped."""
    user = answer = None
    for message in messages or []:
        role = message.get("role")
        content = message.get("content") or ""
        if role == "user" and user is None:
            user = content
        elif role == "assistant" and answer is None:
            answer = content
    return user, answer


def build_row(row_id, domain, title, system, user, answer):
    """The phase 2 row shape (docs/14 section 7)."""
    return {
        "id": row_id,
        "domain": domain,
        "title": title,
        "prompt": [{"role": "system", "content": system}, {"role": "user", "content": user or ""}],
        "completion": [{"role": "assistant", "content": answer or ""}],
    }


def has_html_bundle(answer):
    """A row must carry one ```html block and the Export GLB button (docs/14 section 7, rule 1)."""
    text = answer or ""
    return "```html" in text and "Export GLB" in text


def first_drop_reason(record, answer, max_chars, phrases, seen):
    """The first docs/14 section 7 drop rule that matches, or None to keep."""
    if not has_html_bundle(answer):
        return "no_html"
    if len(answer) > max_chars:
        return "too_long"
    if title_is_eval_subject(record.get("title"), phrases):
        return "eval_subject"
    if answer in seen:
        return "duplicate"
    return None


def read_records(path):
    """One parquet shard as a list of dicts. pyarrow is imported here so the module stays importable."""
    import pyarrow.parquet as pq

    return pq.read_table(path).to_pylist()


def collect_ccore_rows(parquet_dir, system, max_chars, phrases):
    """Walk the shards in name order and split them into kept rows and per-reason drop counts.

    Returns (files, rows, dropped, domains): files are (split, path) pairs, rows/dropped/domains are
    keyed by split. Dedup is shared across splits, so an answer first seen in train drops in val.
    """
    rows = {"train": [], "val": []}
    dropped = {"train": collections.Counter(), "val": collections.Counter()}
    domains = {"train": collections.Counter(), "val": collections.Counter()}
    seen = set()
    files = []
    for path in sorted(Path(parquet_dir).glob("*.parquet")):
        split = split_of(path.name)
        if split is None:
            continue
        files.append((split, path))
        for record in read_records(path):
            user, answer = parse_conversation(record.get("messages"))
            answer = answer or ""
            reason = first_drop_reason(record, answer, max_chars, phrases, seen)
            if reason:
                dropped[split][reason] += 1
                continue
            seen.add(answer)
            domains[split][record.get("domain") or ""] += 1
            rows[split].append(
                build_row(record.get("id"), record.get("domain"), record.get("title"), system, user, answer)
            )
    return files, rows, dropped, domains


def collect_extra_rows(run_dir, system, eval_ids):
    """Rows from RUN_DIR/raw whose validation row is ok and whose assembly entry is assembled.

    Refuses (raises) when one of those ids is an eval brief: phase 2 must never train on them.
    """
    run_dir = Path(run_dir)
    validations = {row["id"]: row for row in read_jsonl(run_dir / "validation.jsonl")}
    assembly = {line["id"]: line for line in read_jsonl(run_dir / "assembly.jsonl")}
    added, refused = [], []
    for raw_path in sorted((run_dir / "raw").glob("*.json")):
        raw = json.loads(raw_path.read_text())
        brief_id = raw.get("id") or raw_path.stem
        row = validations.get(brief_id)
        if not row or not row.get("ok"):
            continue
        if not ((assembly.get(brief_id) or {}).get("assembly") or {}).get("assembled"):
            continue
        if brief_id in eval_ids:
            refused.append(brief_id)
            continue
        brief = raw.get("brief") or {}
        added.append(
            build_row(brief_id, brief.get("domain"), brief.get("title"), system,
                      brief.get("brief"), raw.get("content"))
        )
    if refused:
        raise CcorePrepError(
            "--extra-run contains eval-brief ids (never train on bench/glb/briefs.jsonl): "
            + ", ".join(sorted(refused))
        )
    return added


def chars_stats(rows):
    """Completion-length median (upper) and max over the written rows, matching mesh_lora_hf."""
    chars = sorted(len(row["completion"][0]["content"]) for row in rows)
    if not chars:
        return {"count": 0, "median": None, "max": None}
    return {"count": len(chars), "median": chars[len(chars) // 2], "max": chars[-1]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the phase 2 prompt/completion set from ccore's parquet data (docs/14 section 7).")
    ap.add_argument("--parquet-dir", required=True, help="directory of ccore *.parquet shards")
    ap.add_argument("--out", required=True, help="output directory (outside data/, out/ and eval/)")
    ap.add_argument("--max-chars", type=int, default=22000, help="drop answers longer than this many characters")
    ap.add_argument("--system", default="ccore", help="'ccore' for prompts/ccore_glb_system.txt, or a file path")
    ap.add_argument("--leak-file", default=DEFAULT_LEAK, help="eval-subject phrases to drop from titles")
    ap.add_argument("--extra-run", action="append", default=[], metavar="DIR", help="Glimmer run to add its ok+assembled rows; repeatable")
    ap.add_argument("--extra-system", default=None, metavar="FILE", help="system prompt file for the --extra-run rows")
    ap.add_argument("--seed", type=int, default=7, help="shuffle seed for the train split (val keeps its input order)")
    a = ap.parse_args(argv)

    try:
        check_out_dir(a.out)
        system_path = resolve_path(DEFAULT_SYSTEM) if a.system == "ccore" else resolve_path(a.system)
        if not system_path.exists():
            raise CcorePrepError(f"system prompt file not found: {system_path}")
        leak_path = resolve_path(a.leak_file)
        if not leak_path.exists():
            raise CcorePrepError(f"leak file not found: {leak_path}")
        if a.extra_run and not a.extra_system:
            raise CcorePrepError("--extra-system FILE is required with --extra-run")
        extra_system_path = resolve_path(a.extra_system) if a.extra_system else None
        if extra_system_path is not None and not extra_system_path.exists():
            raise CcorePrepError(f"extra system prompt file not found: {extra_system_path}")
    except CcorePrepError as e:
        ap.error(str(e))

    system = system_path.read_text()
    phrases = load_leak_phrases(leak_path)
    files, rows, dropped, domains = collect_ccore_rows(a.parquet_dir, system, a.max_chars, phrases)

    extra_rows = []
    if a.extra_run:
        extra_system = extra_system_path.read_text()
        eval_ids = {row["id"] for row in read_jsonl(EVAL_BRIEFS)}
        try:
            for run_dir in a.extra_run:
                extra_rows.extend(collect_extra_rows(run_dir, extra_system, eval_ids))
        except CcorePrepError as e:
            ap.error(str(e))

    random.Random(a.seed).shuffle(rows["train"])
    train_rows = rows["train"] + extra_rows
    val_rows = rows["val"]

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "train.jsonl").write_text("".join(json.dumps(r) + "\n" for r in train_rows))
    (out / "val.jsonl").write_text("".join(json.dumps(r) + "\n" for r in val_rows))

    stats = {
        "seed": a.seed,
        "max_chars": a.max_chars,
        "system_file": display_path(system_path),
        "system_sha256": hashlib.sha256(system.encode()).hexdigest(),
        "leak_file": display_path(leak_path),
        "leak_file_sha256": sha256_file(leak_path),
        "inputs": [{"file": f.name, "split": split, "sha256": sha256_file(f)} for split, f in files],
        "splits": {
            "train": {"kept": len(rows["train"]), "dropped": {r: dropped["train"][r] for r in DROP_REASONS}},
            "val": {"kept": len(rows["val"]), "dropped": {r: dropped["val"][r] for r in DROP_REASONS}},
        },
        "kept_by_domain": {"train": dict(domains["train"]), "val": dict(domains["val"])},
        "completion_chars": {"train": chars_stats(train_rows), "val": chars_stats(val_rows)},
        "extra": {"kept": len(extra_rows), "runs": [display_path(r) for r in a.extra_run]},
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    totals = {reason: dropped["train"][reason] + dropped["val"][reason] for reason in DROP_REASONS}
    print(f"kept {len(train_rows)} train, {len(val_rows)} val; dropped "
          + ", ".join(f"{reason} {totals[reason]}" for reason in DROP_REASONS))


if __name__ == "__main__":
    main()
