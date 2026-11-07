"""Generate meshes for the baseline's held-out captions with a trained (or any) model, zero-shot, and score them.

Writes the same folder format as scripts/mesh_baseline.py (one JSON per id plus summary.json), so
scripts/mesh_quality.py reads it and before and after compare on the same 30 captions.

backends: --backend mlx     --mlx-model DIR [--adapter DIR]            (local Mac, mlx-lm)
          --backend ollama  --model NAME [--ollama-url URL]            (a converted GGUF served by Ollama)
          --backend openai  --model NAME --base-url URL --key-env VAR  (vLLM, Baseten, any OpenAI-compatible server)
          --backend hf      --hf-model DIR_OR_REPO [--adapter DIR]     (transformers + peft on a GPU box)
"""
import argparse
import json
import os
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path

from mesh_baseline import SYSTEM
from mesh_validate import extract, validate


def strip_thinking(text):
    return text.split("</think>", 1)[1] if "</think>" in text else text


def clean_reply(raw):
    """Decoded with special tokens kept: the reply is what follows the last message marker, minus any control tokens.
    (skip_special_tokens alone leaves the channel header text 'to=user' glued to the first mesh line.)"""
    if "<|message|>" in raw:
        raw = raw.rsplit("<|message|>", 1)[1]
    return re.sub(r"<\|[^|>]*\|>", "", raw).strip()


def runaway(text, run=6):
    """True when the last `run` vertex lines step by the same nonzero amount (v 31 63 32, v 31 63 31, v 31 63 30, ...):
    the counting loop trained models fall into on shapes they do not know. Real meshes do not do this for six lines."""
    pts = [tuple(int(x) for x in ln.split()[1:4]) for ln in text.splitlines()[-(run + 1):] if ln.startswith("v ") and len(ln.split()) == 4 and all(x.lstrip("-").isdigit() for x in ln.split()[1:4])]
    if len(pts) < run:
        return False
    pts = pts[-run:]
    steps = {tuple(b[i] - a[i] for i in range(3)) for a, b in zip(pts, pts[1:])}
    return len(steps) == 1 and steps != {(0, 0, 0)}


def features(answer):
    """Size vector of a valid mesh: bounding-box extents, triangle count, colour groups (all scaled to roughly 0..1)."""
    text = extract(answer)
    vs = [[int(x) for x in ln.split()[1:4]] for ln in text.splitlines() if ln.startswith("v ")]
    ext = [(max(v[i] for v in vs) - min(v[i] for v in vs)) / 63 for i in range(3)]
    tris = sum(1 for ln in text.splitlines() if ln.startswith("f ")) / 300
    cols = sum(1 for ln in text.splitlines() if ln.startswith("c ")) / 4
    return ext + [tris, cols]


def pick_best(answers):
    """Among sampled answers for one caption, choose one. Returns (index, n_valid).

    With 3 or more valid samples take the medoid (the one closest in size, triangle count and colour count to the
    others): independent samples agree on what the object roughly is, outliers are usually the failures.
    With fewer, the first valid one; with none, the first answer.
    """
    ok = [validate(a)[0] for a in answers]
    good = [i for i, o in enumerate(ok) if o]
    if len(good) >= 3:
        f = {i: features(answers[i]) for i in good}
        dist = lambda i, j: sum(abs(a - b) for a, b in zip(f[i], f[j]))
        return min(good, key=lambda i: (sum(dist(i, j) for j in good), i)), len(good)
    return (good[0] if good else 0), len(good)


def run(items, gen, out_dir):
    """items: [{id, caption, ref_tris}]; gen(caption) -> (answer, tokens, done). Resumable; returns summary."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    pre = {}   # id -> (answer, tokens, done, secs) from a batched backend (gen.many), one call per chunk
    many = getattr(gen, "many", None)
    todo = [it for it in items if not (out / f"{it['id']}.json").exists()]
    if many and todo:
        step = getattr(gen, "batch", 8)
        for i in range(0, len(todo), step):
            chunk = todo[i:i + step]
            t = time.time()
            for it, r in zip(chunk, many([c["caption"] for c in chunk])):
                pre[it["id"]] = (*r, round(time.time() - t, 1))
            print(f"batch {i // step + 1}: {len(chunk)} captions in {time.time() - t:.0f}s", flush=True)
    for it in items:
        f = out / f"{it['id']}.json"
        if not f.exists():
            t = time.time()
            ans, toks, done, *secs = pre[it["id"]] if it["id"] in pre else gen(it["caption"])
            ans = strip_thinking(ans)
            ok, why, st = validate(ans)
            f.write_text(json.dumps({"id": it["id"], "caption": it["caption"], "ref_tris": it["ref_tris"], "answer": ans, "ok": ok,
                                     "reason": why, "stats": st, "tokens": toks, "done": done, "secs": secs[0] if secs else round(time.time() - t, 1)}))
        results.append(json.loads(f.read_text()))
        print(f"{it['caption']:<28} {results[-1]['reason']}", flush=True)
    why = Counter(x["reason"] for x in results)
    summary = {"n": len(results), "pass": why["ok"], "pass_rate": round(why["ok"] / max(1, len(results)), 3), "reasons": dict(why),
               "hit_token_cap": sum(1 for x in results if x["done"] == "length")}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def messages(caption):
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": caption}]


def make_gen(a):
    kw = json.loads(a.chat_template_kwargs)
    if a.backend == "mlx":
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler
        model, tok = load(a.mlx_model, adapter_path=a.adapter)
        sampler = make_sampler(temp=a.temperature, top_p=a.top_p, top_k=a.top_k)

        def gen(caption):
            prompt = tok.apply_chat_template(messages(caption), add_generation_prompt=True, tokenize=False, **kw)
            text = generate(model, tok, prompt=prompt, max_tokens=a.max_tokens, sampler=sampler)
            n = len(tok.encode(text))
            return text, n, "length" if n >= a.max_tokens else "stop"
        return gen
    if a.backend == "hf":
        import torch
        from transformers import AutoModelForMultimodalLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(a.hf_model)
        model = AutoModelForMultimodalLM.from_pretrained(a.hf_model, dtype=torch.bfloat16, device_map="auto")  # Glimmer is not a causal-LM auto class
        if a.adapter:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, a.adapter)

        def gen(caption):
            enc = tok.apply_chat_template(messages(caption), add_generation_prompt=True, return_tensors="pt", return_dict=True, **kw)
            ids = enc["input_ids"].to(model.device)
            out = model.generate(ids, max_new_tokens=a.max_tokens, do_sample=True, temperature=a.temperature, top_p=a.top_p, top_k=a.top_k)
            new = out[0][ids.shape[1]:]
            return clean_reply(tok.decode(new, skip_special_tokens=False)), len(new), "length" if len(new) >= a.max_tokens else "stop"

        from transformers import StoppingCriteria, StoppingCriteriaList

        class LoopGuard(StoppingCriteria):
            """Ends a row as soon as its tail is a counting runaway; checked every 8 tokens on the last 160 only."""
            def __init__(self, start):
                self.start, self.step = start, 0

            def __call__(self, input_ids, scores, **kw):
                import torch
                self.step += 1
                stop = torch.zeros(input_ids.shape[0], dtype=torch.bool, device=input_ids.device)
                if self.step % 8:
                    return stop
                for i, row in enumerate(input_ids[:, self.start:]):
                    stop[i] = runaway(clean_reply(tok.decode(row[-160:], skip_special_tokens=False)).split("\n", 1)[-1])
                return stop

        def many(captions):
            # left-padded batch: decoding is memory-bound, so a batch of 30 costs about the same wall time as one
            n_s = max(1, a.samples)
            captions = [c for c in captions for _ in range(n_s)]
            tok.padding_side = "left"
            if tok.pad_token_id is None:
                tok.pad_token = tok.eos_token
            texts = [tok.apply_chat_template(messages(c), add_generation_prompt=True, tokenize=False, **kw) for c in captions]
            enc = tok(texts, return_tensors="pt", padding=True, add_special_tokens=False).to(model.device)
            stops = StoppingCriteriaList([LoopGuard(enc["input_ids"].shape[1])]) if a.loop_guard else None
            out = model.generate(**enc, max_new_tokens=a.max_tokens, do_sample=True, temperature=a.temperature, top_p=a.top_p, top_k=a.top_k, stopping_criteria=stops)
            res = []
            for row in out[:, enc["input_ids"].shape[1]:]:
                n = int((row != tok.pad_token_id).sum())
                res.append((clean_reply(tok.decode(row, skip_special_tokens=False)), n, "length" if n >= a.max_tokens else "stop"))
            best = []
            for k in range(0, len(res), n_s):
                group = res[k:k + n_s]
                answers = [strip_thinking(r[0]) for r in group]
                i, n_ok = pick_best(answers)
                with open(a.out.rstrip("/") + ".samples.jsonl", "a") as sf:  # every sample, to compare pick rules offline
                    sf.write(json.dumps({"caption": captions[k], "picked": i, "answers": answers}) + "\n")
                print(f"samples {k // n_s}: {n_ok}/{n_s} valid", flush=True)
                best.append(group[i])
            return best
        gen.many, gen.batch = many, a.batch
        return gen
    if a.backend == "ollama":
        def gen(caption):
            body = {"model": a.model, "stream": False, "think": False, "messages": messages(caption),
                    "options": {"temperature": a.temperature, "top_p": a.top_p, "top_k": a.top_k, "num_ctx": 16384, "num_predict": a.max_tokens}}
            r = json.load(urllib.request.urlopen(urllib.request.Request(a.ollama_url + "/api/chat", json.dumps(body).encode(),
                                                                          {"Content-Type": "application/json"}), timeout=1800))
            return r["message"].get("content") or "", r.get("eval_count"), "length" if r.get("done_reason") == "length" else "stop"
        return gen
    from openai import OpenAI
    c = OpenAI(base_url=a.base_url, api_key=os.environ[a.key_env])

    def gen(caption):
        r = c.chat.completions.create(model=a.model, messages=messages(caption), temperature=a.temperature, top_p=a.top_p, max_tokens=a.max_tokens)
        return r.choices[0].message.content or "", r.usage.completion_tokens if r.usage else None, r.choices[0].finish_reason
    return gen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["mlx", "ollama", "openai", "hf"], required=True)
    ap.add_argument("--captions-from", default="eval/mesh_baseline", help="baseline folder; its ids and captions are the test set")
    ap.add_argument("--objects", default="data/mesh/objects.jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--mlx-model"), ap.add_argument("--hf-model"), ap.add_argument("--adapter")
    ap.add_argument("--model"), ap.add_argument("--base-url"), ap.add_argument("--key-env", default="OPENAI_API_KEY")
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    ap.add_argument("--max-tokens", type=int, default=8000, help="a 380-triangle mesh needs about 5,000 tokens (measured)")
    ap.add_argument("--batch", type=int, default=10, help="hf backend: captions generated together per call")
    ap.add_argument("--samples", type=int, default=1, help="hf backend: samples per caption; the first valid one is kept")
    ap.add_argument("--loop-guard", action="store_true", help="hf backend: end a sample when it starts counting a coordinate (runaway)")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--top-k", type=int, default=64)
    ap.add_argument("--chat-template-kwargs", default="{}", help='JSON passed to apply_chat_template. Glimmer\'s template reads reasoning_strength (default high; no off value). Leave empty to match training, which used the default')
    a = ap.parse_args()

    objs = {json.loads(l)["id"]: json.loads(l) for l in Path(a.objects).read_text().splitlines() if l.strip()}
    items = []
    for f in sorted(Path(a.captions_from).glob("m*.json")):
        d = json.loads(f.read_text())
        items.append({"id": d["id"], "caption": d["caption"], "ref_tris": objs[d["id"]]["tris"] if d["id"] in objs else None})
    items = items[: a.limit] if a.limit else items
    print(json.dumps(run(items, make_gen(a), a.out)))


if __name__ == "__main__":
    main()
