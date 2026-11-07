"""Baseline: ask a model (default untrained Glimmer) to write meshes from captions, few-shot, and score them.

usage: python scripts/mesh_baseline.py --objects data/mesh/objects.jsonl --out eval/mesh_baseline --n 30
Writes one JSON per caption plus summary.json. Resumable. Test objects are held out of the examples.
"""
import argparse
import json
import time
import urllib.request
from collections import Counter
from pathlib import Path

from mesh_validate import validate

SYSTEM = """You write low-poly 3D models as plain text. Reply with only the mesh, no explanation.
Format, one item per line:
  v X Y Z      a vertex, three integers from 0 to 63 (x right, y up, z depth)
  c #rrggbb    starts a colour group; the faces after it use that colour
  f A B C      a triangle of three vertex numbers (1-based, in the order the v lines appear)
Rules: the object stands on y=0, is centred on x and z, and its longest side spans 0 to 63.
Use at least 12 triangles. List every v line before the first c line. Every triangle needs three different vertices."""


def ask(model, url, shots, caption, a):
    msgs = [{"role": "system", "content": SYSTEM}]
    for s in shots:
        msgs += [{"role": "user", "content": s["caption"]}, {"role": "assistant", "content": s["text"]}]
    msgs.append({"role": "user", "content": caption})
    body = {"model": model, "stream": False, "think": False, "messages": msgs,
            "options": {"temperature": a.temperature, "top_p": 0.95, "num_ctx": a.num_ctx, "num_predict": a.max_tokens}}
    req = urllib.request.Request(url + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=1800))
    return r["message"].get("content") or "", r.get("eval_count"), r.get("done_reason")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--objects", default="data/mesh/objects.jsonl")
    ap.add_argument("--out", default="eval/mesh_baseline")
    ap.add_argument("--model", default="muse-glimmer:30b-mlx")
    ap.add_argument("--url", default="http://localhost:11434")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--shots", type=int, default=3)
    ap.add_argument("--max-tris", type=int, default=400, help="only test on objects up to this size")
    ap.add_argument("--max-tokens", type=int, default=9000)
    ap.add_argument("--num-ctx", type=int, default=16384)
    ap.add_argument("--temperature", type=float, default=0.7)
    a = ap.parse_args()

    rows = [json.loads(l) for l in Path(a.objects).read_text().splitlines() if l.strip()]
    test = [r for r in rows if r["tris"] <= a.max_tris][:: max(1, len([r for r in rows if r["tris"] <= a.max_tris]) // a.n)][: a.n]
    held = {r["id"] for r in test}
    pool = sorted((r for r in rows if r["id"] not in held and r["tris"] <= 120), key=lambda r: r["tris"])
    shots = pool[:: max(1, len(pool) // a.shots)][: a.shots]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    print("shots:", [s["caption"] for s in shots], "| test:", len(test))

    results = []
    for r in test:
        f = out / f"{r['id']}.json"
        if not f.exists():
            t = time.time()
            ans, toks, done = ask(a.model, a.url, shots, r["caption"], a)
            ok, why, st = validate(ans)
            f.write_text(json.dumps({"id": r["id"], "caption": r["caption"], "ref_tris": r["tris"], "answer": ans,
                                     "ok": ok, "reason": why, "stats": st, "tokens": toks, "done": done, "secs": round(time.time() - t, 1)}))
        results.append(json.loads(f.read_text()))
        print(f"{r['caption']:<28} {results[-1]['reason']}", flush=True)
    why = Counter(x["reason"] for x in results)
    summary = {"model": a.model, "n": len(results), "pass": why["ok"], "pass_rate": round(why["ok"] / len(results), 3), "reasons": dict(why)}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(summary)


if __name__ == "__main__":
    main()
