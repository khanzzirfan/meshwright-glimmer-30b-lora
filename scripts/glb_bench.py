"""Run every enabled GLB model on the 48 briefs, generate then validate. Resumable."""
import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "PASTE_CCORE_SYSTEM_PROMPT_HERE"
FORBIDDEN_ROOTS = (ROOT / "data", ROOT / "out")


class BenchError(Exception):
    pass


def load_models(path):
    return json.loads(Path(path).read_text())


def resolve_path(value):
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def select_models(models, only=None):
    if only:
        names = {m["name"] for m in models}
        unknown = [n for n in only if n not in names]
        if unknown:
            raise BenchError(f"unknown --only name(s): {', '.join(unknown)}")
        wanted = set(only)
        return [m for m in models if m["name"] in wanted]
    return [m for m in models if m.get("enabled")]


def check_out_root(out_root):
    out = Path(out_root).resolve()
    for base in FORBIDDEN_ROOTS:
        base = base.resolve()
        if out == base or base in out.parents:
            raise BenchError(f"--out-root must not be inside {base.relative_to(ROOT)}/ ({out})")


def check_systems(models):
    for m in models:
        path = resolve_path(m["system"])
        if not path.exists():
            raise BenchError(f"{m['name']}: system prompt file not found: {path}")
        if PLACEHOLDER in path.read_text():
            raise BenchError(
                f"{m['name']}: {path} still contains {PLACEHOLDER}; paste ccore's verbatim system prompt first"
            )


def check_paid(models, allow_paid):
    if allow_paid:
        return
    paid = [m["name"] for m in models if m.get("paid")]
    if paid:
        raise BenchError(f"paid model(s) selected without --allow-paid: {', '.join(paid)}")


def check_ollama(models):
    ollama = [m for m in models if m["provider"] == "ollama"]
    if not ollama:
        return
    try:
        listed = subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        raise BenchError("ollama not found; install Ollama or use --dry-run to inspect the commands")
    installed = {line.split()[0] for line in listed.splitlines()[1:] if line.strip()}
    missing = [m["model"] for m in ollama if m["model"] not in installed]
    if missing:
        raise BenchError("missing Ollama model(s); run: " + " && ".join(f"ollama pull {m}" for m in missing))


def _num(value):
    return str(value)


def _add_sampling(cmd, model):
    for flag, key in (("--temperature", "temperature"), ("--top-p", "top_p"),
                      ("--top-k", "top_k"), ("--min-p", "min_p")):
        value = model.get(key)
        if value is not None:
            cmd += [flag, _num(value)]


def plan(models, args):
    """Return the generate and validate command for each selected model, in order."""
    selected = select_models(models, getattr(args, "only", None))
    root = Path(args.out_root)
    briefs = str(getattr(args, "briefs", "bench/glb/briefs.jsonl"))
    commands = []
    for model in selected:
        run_dir = root / model["name"]
        cmd = [
            sys.executable, "scripts/teacher_generate.py",
            "--briefs", briefs,
            "--out", str(run_dir / "raw"),
            "--model", model["model"],
        ]
        if model["provider"] == "ollama":
            cmd.append("--ollama-native")
        cmd += ["--system", str(resolve_path(model["system"]))]
        _add_sampling(cmd, model)
        cmd += [
            "--num-ctx", str(getattr(args, "num_ctx", 49152)),
            "--max-tokens", str(getattr(args, "max_tokens", 40000)),
            "--concurrency", str(getattr(args, "concurrency", 1)),
        ]
        ollama_url = getattr(args, "ollama_url", None)
        if ollama_url and model["provider"] == "ollama":
            cmd += ["--ollama-url", ollama_url]
        if model.get("think"):
            cmd.append("--think")
        limit = getattr(args, "limit", 0)
        if limit:
            cmd += ["--limit", str(limit)]
        commands.append(cmd)
        commands.append([
            "node", "scripts/validate_scenes.mjs",
            "--mode", "glb", "--allow-addons",
            "--raw", str(run_dir / "raw"),
            "--scenes", str(run_dir / "scenes"),
            "--shots", str(run_dir / "shots"),
            "--glb-dir", str(run_dir / "glb"),
            "--report", str(run_dir / "validation.jsonl"),
        ])
    return commands


def print_command(cmd):
    print("+ " + " ".join(shlex.quote(part) for part in cmd), flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run each enabled GLB model then validate its answers.")
    ap.add_argument("--out-root", required=True, help="output root, outside data/ and out/")
    ap.add_argument("--models", default="bench/glb/models.json")
    ap.add_argument("--briefs", default="bench/glb/briefs.jsonl")
    ap.add_argument("--only", action="append", help="model name from models.json; repeatable, selects even if disabled")
    ap.add_argument("--limit", type=int, default=0, help="stop after N briefs per model")
    ap.add_argument("--num-ctx", type=int, default=49152)
    ap.add_argument("--max-tokens", type=int, default=40000)
    ap.add_argument("--ollama-url", default=None, help="Ollama server for generation, e.g. http://localhost:11435 through an SSH tunnel to a rented GPU (default: the local server)")
    ap.add_argument("--concurrency", type=int, default=1, help="parallel requests; use more than 1 only against a server started with OLLAMA_NUM_PARALLEL")
    ap.add_argument("--allow-paid", action="store_true", help="allow rows with paid true")
    ap.add_argument("--dry-run", action="store_true", help="print every command and run nothing")
    a = ap.parse_args(argv)

    models = load_models(a.models)
    try:
        selected = select_models(models, a.only)
        check_out_root(a.out_root)
        check_systems(selected)
        check_paid(selected, a.allow_paid)
    except BenchError as e:
        ap.error(str(e))

    commands = plan(models, a)
    if a.dry_run:
        for cmd in commands:
            print_command(cmd)
        return

    try:
        check_ollama(selected)
    except BenchError as e:
        ap.error(str(e))
    for cmd in commands:
        print_command(cmd)
        rc = subprocess.run(cmd).returncode
        if rc:
            raise SystemExit(rc)


if __name__ == "__main__":
    main()
