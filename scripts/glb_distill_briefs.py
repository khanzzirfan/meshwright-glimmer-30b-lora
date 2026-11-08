"""Author the self-distillation briefs from bench/distill/subjects.json (docs/14, imp-5 US-005).

Reads a subjects file shaped as {domain: [{title, brief, kind}, ...]}, keeps the entries that do not leak
an eval subject, and writes them as JSONL in the eval brief field format (bench/glb/briefs.jsonl):
{id, title, brief, domain, level, style, kind}. Ids are assigned in domain order (x0001, x0002, ...); the
level is 1-3 by brief length and the style is always 'low-poly'. An entry is dropped when its title or
brief contains an eval subject phrase (whole word, case-insensitive), when its title equals an eval title
(case-insensitive) or when its title was already kept (duplicate). Kept and per-reason dropped counts are
printed, and --out is refused inside data/, out/ or eval/.
"""
import argparse
import json
from pathlib import Path

from ccore_prep import load_leak_phrases, title_is_eval_subject

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_ROOTS = (ROOT / "data", ROOT / "out", ROOT / "eval")
DEFAULT_SUBJECTS = "bench/distill/subjects.json"
DEFAULT_EVAL_BRIEFS = "bench/glb/briefs.jsonl"
DEFAULT_LEAK = "bench/glb/eval_subjects.json"
DEFAULT_OUT = "bench/distill/briefs.jsonl"
STYLE = "low-poly"
# level 1 for short briefs, 2 for the middle band, 3 for the longest (docs/14, imp-5 US-005).
LEVEL_MAX_CHARS = (70, 120)
DROP_REASONS = ("leak_phrase", "leak_title", "duplicate")
SUBJECT_KEYS = {"title", "brief", "kind"}


def read_jsonl(path):
    """Parse a JSONL file into a list, or [] when it does not exist."""
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def resolve_path(value):
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def level_for(brief):
    """The 1-3 level a brief's length maps to (LEVEL_MAX_CHARS bounds inclusive)."""
    length = len(brief)
    if length <= LEVEL_MAX_CHARS[0]:
        return 1
    if length <= LEVEL_MAX_CHARS[1]:
        return 2
    return 3


def eval_titles(path):
    """The eval brief titles, normalised for a case-insensitive, whitespace-insensitive equality check."""
    return {row.get("title", "").strip().casefold() for row in read_jsonl(path)}


def check_out(out_path):
    """Refuse an --out under data/, out/ or eval/ (the imp guardrail)."""
    out = Path(out_path).resolve()
    for base in FORBIDDEN_ROOTS:
        base = base.resolve()
        if out == base or base in out.parents:
            raise ValueError(f"--out must not be inside {base.relative_to(ROOT)}/ ({out})")


def check_subjects(subjects):
    """A subjects file is {domain: [{title, brief, kind}, ...]}; raise on anything else."""
    if not isinstance(subjects, dict):
        raise ValueError("subjects file must be a JSON object of {domain: [entries]}")
    for domain, entries in subjects.items():
        if not isinstance(entries, list):
            raise ValueError(f"domain {domain!r} must map to a list of entries")
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != SUBJECT_KEYS:
                raise ValueError(f"domain {domain!r} has an entry that is not {{title, brief, kind}}: {entry!r}")
            if not entry["title"] or not entry["brief"]:
                raise ValueError(f"domain {domain!r} has an entry with an empty title or brief: {entry!r}")


def build_briefs(subjects, phrases, titles):
    """Split the subjects into kept rows and per-reason drop counts, assigning ids in domain order."""
    kept, dropped = [], {reason: 0 for reason in DROP_REASONS}
    seen = set()
    for domain, entries in subjects.items():
        for entry in entries:
            title, brief = entry["title"], entry["brief"]
            if title_is_eval_subject(title, phrases) or title_is_eval_subject(brief, phrases):
                dropped["leak_phrase"] += 1
                continue
            key = title.strip().casefold()
            if key in titles:
                dropped["leak_title"] += 1
                continue
            if key in seen:
                dropped["duplicate"] += 1
                continue
            seen.add(key)
            kept.append({
                "id": f"x{len(kept) + 1:04d}",
                "title": title,
                "brief": brief,
                "domain": domain,
                "level": level_for(brief),
                "style": STYLE,
                "kind": entry["kind"],
            })
    return kept, dropped


def main(argv=None):
    ap = argparse.ArgumentParser(description="Author self-distillation briefs from a subjects file (docs/14, imp-5 US-005).")
    ap.add_argument("--subjects", default=DEFAULT_SUBJECTS, help="the {domain: [{title, brief, kind}]} file")
    ap.add_argument("--eval-briefs", default=DEFAULT_EVAL_BRIEFS, help="eval briefs whose titles and fields are reused")
    ap.add_argument("--leak-file", default=DEFAULT_LEAK, help="eval-subject phrases to drop from titles and briefs")
    ap.add_argument("--out", default=DEFAULT_OUT, help="JSONL output (outside data/, out/ and eval/)")
    a = ap.parse_args(argv)

    try:
        check_out(a.out)
        subjects_path = resolve_path(a.subjects)
        eval_path = resolve_path(a.eval_briefs)
        leak_path = resolve_path(a.leak_file)
        for path, flag in ((subjects_path, "--subjects"), (eval_path, "--eval-briefs"), (leak_path, "--leak-file")):
            if not path.exists():
                raise ValueError(f"{flag} file not found: {path}")
        subjects = json.loads(subjects_path.read_text())
        check_subjects(subjects)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        ap.error(str(e))

    phrases = load_leak_phrases(leak_path)
    titles = eval_titles(eval_path)
    kept, dropped = build_briefs(subjects, phrases, titles)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(row) + "\n" for row in kept))
    print(f"kept {len(kept)}; dropped " + ", ".join(f"{reason} {dropped[reason]}" for reason in DROP_REASONS))


if __name__ == "__main__":
    main()
