"""Check the Baseten key and Muse Spark Open with two real calls. Paid: needs --yes.

Ported from pixitween-director scripts/live/baseten-smoke.ts, extended with the call this project
actually makes (a scene from prompts/system.txt) so you see tokens, reasoning and the html fence
before any larger run. The key is read from .env / the environment and never printed.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from common import ROOT, client, system_prompt

BRIEF = "A small low-poly lighthouse on a rocky island at dusk, with a rotating beam and gentle waves."


def call(c, model, messages, max_tokens):
    t0 = time.time()
    r = c.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens, temperature=0.7, top_p=0.95)
    m = r.choices[0].message
    reasoning = getattr(m, "reasoning_content", None) or getattr(m, "reasoning", None)
    return {
        "seconds": round(time.time() - t0, 1), "finish": r.choices[0].finish_reason,
        "prompt_tokens": r.usage.prompt_tokens if r.usage else None,
        "completion_tokens": r.usage.completion_tokens if r.usage else None,
        "reasoning_chars": len(reasoning or ""), "content": m.content or "", "reasoning": reasoning,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="actually spend credits (about 10k tokens in total)")
    ap.add_argument("--model", default=os.environ.get("TEACHER_MODEL"))
    ap.add_argument("--max-tokens", type=int, default=12000)
    a = ap.parse_args()

    if not os.environ.get("BASETEN_API_KEY"):
        sys.exit("BASETEN_API_KEY is not set. Copy your .env into this folder (see docs/baseten-spark-open.md).")
    if not a.model:
        sys.exit("TEACHER_MODEL is not set (expected meta-models/muse-spark-open-1026).")
    print(f"model {a.model}\nplan: one tiny call, then one scene call (max {a.max_tokens} tokens; reasoning counts).")
    print("estimate: roughly 10k tokens, a few cents of hackathon credit (no per-token price published).")
    if not a.yes:
        sys.exit("dry run only. Add --yes to make the calls.")

    c = client()
    out = ROOT / "data" / "baseten_smoke"
    out.mkdir(parents=True, exist_ok=True)
    try:
        tiny = call(c, a.model, [{"role": "user", "content": "Reply with the single word: ready"}], 512)
        print(f"tiny  ok {tiny['seconds']}s tokens {tiny['prompt_tokens']}+{tiny['completion_tokens']} reasoning={'yes' if tiny['reasoning_chars'] else 'no'} reply={tiny['content'].strip()[:60]!r}")
        scene = call(c, a.model, [{"role": "system", "content": system_prompt()}, {"role": "user", "content": BRIEF}], a.max_tokens)
    except Exception as e:
        status = getattr(e, "status_code", None)
        hint = {401: "key rejected: wrong or revoked", 404: "model not found: the hackathon key only works with meta-models/muse-spark-open-1026"}.get(status, "")
        sys.exit(f"FAILED status {status} {hint} {str(e)[:200]}")
    (out / "scene.json").write_text(json.dumps(scene, indent=2))
    tps = scene["completion_tokens"] / scene["seconds"] if scene["completion_tokens"] and scene["seconds"] else 0
    print(f"scene ok {scene['seconds']}s tokens {scene['prompt_tokens']}+{scene['completion_tokens']} ({tps:.0f} tok/s) finish={scene['finish']} "
          f"reasoning_chars={scene['reasoning_chars']} html_fence={'```html' in scene['content']}")
    print(f"saved {out / 'scene.json'}  (validate it: copy to data/raw as id baseten-smoke with the same keys, or just open the html)")


if __name__ == "__main__":
    main()
