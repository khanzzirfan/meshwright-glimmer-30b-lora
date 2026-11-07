"""Score a generation run against the exact meshes from proof_data's targets.json.

The scorer answers three independent questions per target: did the model copy the
target text exactly, did it produce a valid mesh, and did it stop before the token
cap. ``compare`` handles one output; ``score_run`` aggregates a whole run. The MLX
backend is built by ``make_mlx_gen``, which imports mlx_lm only when called so this
module stays importable in the offline test environment.

usage: python scripts/proof_score.py --targets /tmp/proof/targets.json \
    --sft-system-from /tmp/proof/train.jsonl --model Qwen/Qwen2.5-0.5B-Instruct \
    --adapter /tmp/proof/adapter --max-tokens 8000 --temperature 0.0 \
    --out /tmp/proof/report.json
"""
import argparse
import json
import sys
from pathlib import Path

from mesh_validate import validate

PROTECTED = ("data", "eval", "out")


def _lines(text):
    stripped = text.strip()
    return stripped.splitlines() if stripped else []


def compare(output, target, tokens, max_tokens):
    """Compare one generated output with its target mesh.

    exact: stripped output equals the stripped target text.
    lines_identical / lines_total: matching lines at the same position, over the
    longer of the two line lists (extra generated lines count against it).
    valid / reason: from mesh_validate.validate on the output.
    stopped: the model stopped before reaching max_tokens.
    """
    output = output or ""
    target = target or ""
    out_lines = _lines(output)
    target_lines = _lines(target)
    lines_total = max(len(out_lines), len(target_lines))
    lines_identical = sum(1 for a, b in zip(out_lines, target_lines) if a.strip() == b.strip())
    valid, reason, _stats = validate(output)
    return {
        "exact": output.strip() == target.strip(),
        "lines_identical": lines_identical,
        "lines_total": lines_total,
        "valid": valid,
        "reason": reason,
        "stopped": tokens is not None and int(tokens) < int(max_tokens),
        "tokens": tokens,
    }


def score_run(targets, gen, max_tokens):
    """Score every target with an injected gen(caption) -> (text, tokens).

    Returns a report of counts plus one item per target. Every number is computed
    from the compared items; nothing is estimated or filled in.
    """
    items = []
    for target in targets:
        text, tokens = gen(target["caption"])
        result = compare(text, target["mesh"], tokens, max_tokens)
        items.append({"id": target["id"], "caption": target["caption"], **result})

    total_lines = sum(item["lines_total"] for item in items)
    identical_lines = sum(item["lines_identical"] for item in items)
    return {
        "n": len(items),
        "exact": sum(1 for item in items if item["exact"]),
        "valid": sum(1 for item in items if item["valid"]),
        "stopped": sum(1 for item in items if item["stopped"]),
        "lines_identical_share": (identical_lines / total_lines) if total_lines else 0.0,
        "items": items,
    }


def write_report(report, out_path):
    """Write a report exactly as score_run built it."""
    Path(out_path).write_text(json.dumps(report, indent=1) + "\n")
    return report


def system_from_train(path):
    """The system message from the first row of a proof_data train.jsonl."""
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        messages = row.get("messages") or row.get("prompt") or []
        for message in messages:
            if message.get("role") == "system":
                return message["content"]
    raise ValueError(f"no system message in {path}")


def make_mlx_gen(model, adapter, system_text, temperature, max_tokens):
    """Build a gen(caption) -> (text, tokens) callable backed by mlx_lm.

    mlx_lm is imported here, not at module level, so importing proof_score works
    without MLX installed.
    """
    from mlx_lm import load, stream_generate
    from mlx_lm.sample_utils import make_sampler

    loaded, tokenizer = load(model, adapter_path=adapter)
    sampler = make_sampler(temp=temperature)

    def gen(caption):
        messages = [{"role": "system", "content": system_text},
                    {"role": "user", "content": caption}]
        prompt = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        # count the tokens the model really produced: re-encoding the text can land below the cap on a runaway
        # that was cut off, which would wrongly score it as stopped
        parts, tokens, reason = [], 0, None
        for r in stream_generate(loaded, tokenizer, prompt=prompt, max_tokens=max_tokens, sampler=sampler):
            parts.append(r.text)
            tokens, reason = r.generation_tokens, r.finish_reason
        return "".join(parts), (max_tokens if reason == "length" else tokens)

    return gen


def _protected_folder(out_path):
    """Name of the protected repo folder containing out_path, or None."""
    root = Path(__file__).resolve().parent.parent
    target = Path(out_path).resolve()
    for name in PROTECTED:
        base = (root / name).resolve()
        if target == base or base in target.parents:
            return name
    return None


def main():
    ap = argparse.ArgumentParser(description="Score generated meshes against targets.json.")
    ap.add_argument("--targets", required=True, help="targets.json from scripts/proof_data.py")
    ap.add_argument("--sft-system-from", required=True, help="train.jsonl whose first system message is the prompt")
    ap.add_argument("--model", required=True, help="MLX model path or Hugging Face repo")
    ap.add_argument("--adapter", default=None, help="optional MLX LoRA adapter folder")
    ap.add_argument("--max-tokens", type=int, default=8000)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--out", required=True, help="report JSON to write")
    a = ap.parse_args()

    blocked = _protected_folder(a.out)
    if blocked:
        print(f"refusing to write inside {blocked}/: choose a work folder such as /tmp/proof", file=sys.stderr)
        raise SystemExit(2)

    targets = json.loads(Path(a.targets).read_text())
    system_text = system_from_train(a.sft_system_from)
    gen = make_mlx_gen(a.model, a.adapter, system_text, a.temperature, a.max_tokens)
    report = write_report(score_run(targets, gen, a.max_tokens), a.out)
    print(f"{report['exact']}/{report['n']} exact, {report['valid']}/{report['n']} valid, "
          f"{report['stopped']}/{report['n']} stopped -> {a.out}")


if __name__ == "__main__":
    main()
