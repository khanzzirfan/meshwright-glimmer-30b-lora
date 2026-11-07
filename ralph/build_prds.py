#!/usr/bin/env python3
"""Build Ralph-TUI PRD files from compact sources, and validate them.

    python3 ralph/build_prds.py             # build ralph/src/prd-*.json -> ralph/prd-*.json, then validate
    python3 ralph/build_prds.py --check     # validate the built files only (no writes); exit 1 on any error
    python3 ralph/build_prds.py --status    # one line per PRD: stories passing / total, next story

Why a build step: the guardrails and quality gates must be identical in every PRD and every story's
acceptance criteria must end with them (ralph-tui-create-json convention). Authors write only the
story-specific part. Standard library only. Built files are flat: name + userStories at the root.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
MAX_STORIES = 9

UNIVERSAL_GATES = [
    "`bash scripts/check.sh` passes (syntax checks, pytest, node tests; offline)",
    "Any script flag or behaviour you changed or added is described in README.md or the doc the story names",
]
CHROMIUM_GATE = (
    "Browser-driven tests run against the installed Chromium (`npx playwright install chromium` is already done); "
    "if Chromium cannot launch, say so in `notes` instead of skipping silently"
)

GUARDRAILS = [
    "Work offline. Tests use fixtures under tests/fixtures and mocked HTTP. Never call Baseten, Meta, Hugging Face or any remote service from a story, a test or a script you run. The only network use allowed is `npm install` and `.venv/bin/pip install` of packages the story names.",
    "Never commit, push, tag or publish. autoCommit is off and the owner commits.",
    "Never delete, overwrite or reformat anything under data/, out/, eval/, .env or .venv. They are the owner's data (a long Glimmer generation run may be writing data/raw right now). Tests write only to temporary directories.",
    "Do not start long jobs. Any command that would run more than about 5 minutes (corpus generation, training, GGUF conversion, evals) is written as a script plus docs and left for the owner. A live smoke call to the local Ollama is allowed only if the story says so, with at most 2 briefs, and must skip cleanly when Ollama is down. Never rent GPUs or run `runpodctl` with anything that creates a pod.",
    "Edit only the files named in the story's steps, plus their tests and the doc the story names. Do not change prompts/system.txt: every existing raw answer was generated against it.",
    "Match the surrounding code: short comments that explain why, argparse CLIs, resumable file-per-item outputs, no new dependency the story does not name. Python runs with `.venv/bin/python`; Node scripts are ESM `.mjs` (Node 22).",
    "Three.js stays pinned at 0.160.0 and the validator keeps serving the local copy in place of the CDN URL.",
    "Python scripts must stay importable without heavy deps: import torch, transformers, trl or peft only inside functions or under `if __name__ == '__main__'` so pytest can import them.",
    "Record only real results. Never invent pass rates, token counts, timings or costs; where a number is unknown write 'not measured'.",
    "Debug output goes to data/ or a temp dir, never into scripts/ or docs/.",
    "If the spec is wrong or impossible, do the closest thing that works and explain the difference in `notes`. If you cannot finish a story, set `notes` to why and stop; do not mark it passing.",
]


def prd_files(folder: Path) -> list[Path]:
    """prd-NN-*.json (the main tracks) plus <name>-N.prd.json (side experiments such as proof-1.prd.json)."""
    return sorted(set(folder.glob("prd-*.json")) | set(folder.glob("*.prd.json")))


def die(msg: str) -> None:
    print(f"ERROR: {msg}")
    sys.exit(1)


def build(src: Path) -> dict:
    s = json.loads(src.read_text())
    stories = s["stories"]
    out_stories = []
    for i, st in enumerate(stories, 1):
        sid = f"US-{i:03d}"
        deps = st.get("dependsOn", [out_stories[-1]["id"]] if out_stories else [])
        gates = list(UNIVERSAL_GATES) + ([CHROMIUM_GATE] if st.get("chromium") else [])
        out_stories.append({
            "id": sid,
            "title": st["title"],
            "description": st["description"],
            "steps": st["steps"],
            "acceptanceCriteria": st["criteria"] + gates,
            "priority": i,
            "passes": False,
            "notes": "",
            "dependsOn": deps,
        })
    return {
        "name": s["name"],
        "branchName": s["branchName"],
        "description": s["description"],
        "userStories": out_stories,
        "metadata": {
            "specs": s.get("specs", []),
            "readFirst": s.get("readFirst", []),
            "owns": s.get("owns", []),
            "requires": s.get("requires", []),
            "standingRule": s["standingRule"],
            "guardrails": GUARDRAILS,
            "qualityGates": {"universal": UNIVERSAL_GATES, "chromium": [CHROMIUM_GATE]},
            "manualGates": s.get("manualGates", []),
        },
    }


def validate(path: Path) -> list[str]:
    errs = []
    d = json.loads(path.read_text())
    for k in ("name", "branchName", "description", "userStories"):
        if k not in d:
            errs.append(f"{path.name}: missing root key {k}")
    for bad in ("prd", "tasks"):
        if bad in d:
            errs.append(f"{path.name}: wrapper key {bad} not allowed")
    stories = d.get("userStories", [])
    if not 1 <= len(stories) <= MAX_STORIES:
        errs.append(f"{path.name}: {len(stories)} stories (limit {MAX_STORIES})")
    ids = [s["id"] for s in stories]
    if len(set(ids)) != len(ids):
        errs.append(f"{path.name}: duplicate story ids")
    seen = set()
    for s in stories:
        tag = f"{path.name} {s['id']}"
        if len(s["acceptanceCriteria"]) < len(UNIVERSAL_GATES) + 2:
            errs.append(f"{tag}: fewer than 2 story-specific criteria")
        if not s["steps"]:
            errs.append(f"{tag}: no steps")
        if s.get("passes") not in (True, False):
            errs.append(f"{tag}: passes must be a boolean")
        for c in s["acceptanceCriteria"]:
            if re.fullmatch(r"(works|works correctly|good ux|handles edge cases)\.?", c.strip(), re.I):
                errs.append(f"{tag}: vague criterion {c!r}")
        for dep in s["dependsOn"]:
            if dep not in seen:  # dependencies must point backwards: no cycles
                errs.append(f"{tag}: dependsOn {dep} is not an earlier story")
        seen.add(s["id"])
    return errs


def status() -> None:
    for p in prd_files(HERE):
        d = json.loads(p.read_text())
        st = d["userStories"]
        done = sum(1 for s in st if s["passes"])
        nxt = next((s for s in st if not s["passes"]), None)
        nxt_s = f"next {nxt['id']} {nxt['title']}" if nxt else "all passing"
        note = f" | notes on {nxt['id']}: {nxt['notes']}" if nxt and nxt["notes"] else ""
        print(f"{p.name}: {done}/{len(st)} | {nxt_s}{note}")


def main() -> None:
    args = sys.argv[1:]
    if "--status" in args:
        return status()
    if "--check" not in args:
        for src in prd_files(SRC):
            target = HERE / src.name
            built = build(src)
            if target.exists():  # keep progress already written by Ralph
                old = {s["id"]: s for s in json.loads(target.read_text())["userStories"]}
                for s in built["userStories"]:
                    if s["id"] in old and old[s["id"]]["title"] == s["title"]:
                        s["passes"], s["notes"] = old[s["id"]]["passes"], old[s["id"]]["notes"]
            target.write_text(json.dumps(built, indent=2) + "\n")
            print(f"built {target.name} ({len(built['userStories'])} stories)")
    errs = []
    files = prd_files(HERE)
    if not files:
        die("no ralph PRD files found")
    for p in files:
        errs += validate(p)
    if errs:
        die("\n".join(errs))
    print(f"OK: {len(files)} PRDs, {sum(len(json.loads(p.read_text())['userStories']) for p in files)} stories")


if __name__ == "__main__":
    main()
