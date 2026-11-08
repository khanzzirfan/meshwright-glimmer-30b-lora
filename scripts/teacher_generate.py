"""Send each brief to a model (teacher or student) and save raw answers. Resumable."""
import argparse
import hashlib
import json
import os
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tqdm import tqdm

from common import ROOT, client, system_prompt
from tags import THINK_CLOSE, THINK_OPEN


def call_ollama(model, system, brief, a):
    # native /api/chat: the only Ollama route where `think` is a documented switch
    options = {"temperature": a.temperature, "top_p": a.top_p, "num_ctx": a.num_ctx, "num_predict": a.max_tokens}
    for key in ("top_k", "min_p", "repeat_penalty"):
        value = getattr(a, key)
        if value is not None:
            options[key] = value
    if getattr(a, "seed", None) is not None:
        options["seed"] = a.seed
    body = {
        "model": model, "stream": False, "think": a.think,
        "options": options,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": brief["brief"]}],
    }
    req = urllib.request.Request(a.ollama_url + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=1800))
    m = r["message"]
    return {
        "id": brief["id"], "brief": brief, "model": model, "content": (m.get("content") or "").strip(),
        "reasoning": m.get("thinking") or None,
        "finish_reason": "length" if r.get("done_reason") == "length" else "stop",
        "usage": {"completion_tokens": r.get("eval_count"), "prompt_tokens": r.get("prompt_eval_count"),
                  "seconds": r.get("total_duration", 0) / 1e9},
        "ts": time.time(),
    }


def call(c, model, system, brief, a):
    err = None
    for attempt in range(5):
        try:
            if a.ollama_native:
                return call_ollama(model, system, brief, a)
            r = c.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": brief["brief"]}],
                temperature=a.temperature, top_p=a.top_p, max_tokens=a.max_tokens,
            )
            m = r.choices[0].message
            # providers differ: reasoning may be a separate field, inline <think>, or absent
            reasoning = getattr(m, "reasoning_content", None) or getattr(m, "reasoning", None)
            content = m.content or ""
            if reasoning is None and THINK_CLOSE in content:
                reasoning, content = content.split(THINK_CLOSE, 1)
                reasoning = reasoning.replace(THINK_OPEN, "").strip()
            return {
                "id": brief["id"], "brief": brief, "model": model, "content": content.strip(),
                "reasoning": reasoning, "finish_reason": r.choices[0].finish_reason,
                "usage": r.usage.model_dump() if r.usage else None, "ts": time.time(),
            }
        except Exception as e:  # rate limit or transient server error: back off and retry
            err = str(e)
            status = getattr(e, "status_code", None) or getattr(e, "code", None)
            if isinstance(status, int) and 400 <= status < 500 and status != 429:
                break  # bad request, auth, unknown model: retrying will not help
            time.sleep(2 ** attempt * 2)
    return {"id": brief["id"], "error": err}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--briefs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=os.environ.get("TEACHER_MODEL"))
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--max-tokens", type=int, default=12000)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--token-budget", type=int, default=0, help="stop starting new calls once this many prompt+completion tokens are used (0 = no cap); in-flight calls still finish")
    ap.add_argument("--ollama-native", action="store_true", help="call a local Ollama /api/chat instead of an OpenAI endpoint")
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    ap.add_argument("--think", action="store_true", help="with --ollama-native: ask for a reasoning trace")
    ap.add_argument("--num-ctx", type=int, default=16384)
    ap.add_argument("--system", default=None, help="system prompt file (default: prompts/system.txt)")
    ap.add_argument("--top-k", type=int, default=None, help="with --ollama-native: only sent when given")
    ap.add_argument("--min-p", type=float, default=None, help="with --ollama-native: only sent when given")
    ap.add_argument("--repeat-penalty", type=float, default=None, help="with --ollama-native: only sent when given")
    ap.add_argument("--seed", type=int, default=None, help="with --ollama-native: sampling seed (options.seed); recorded in each raw row; omitted by default")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    briefs = [json.loads(l) for l in Path(a.briefs).read_text().splitlines() if l.strip()]
    todo = [b for b in briefs if not (out / f"{b['id']}.json").exists()]
    if a.limit:
        todo = todo[: a.limit]
    c = None if a.ollama_native else client(a.base_url, a.api_key)
    if a.system:
        system_file = a.system
        system = Path(a.system).read_text()
    else:
        system_file = str((ROOT / "prompts" / "system.txt").relative_to(ROOT))
        system = system_prompt()
    system_sha256 = hashlib.sha256(system.encode()).hexdigest()

    spent, lock = [0], threading.Lock()  # tokens used so far, for the paid-run budget

    def work(b):
        if a.token_budget and spent[0] >= a.token_budget:
            return {"id": b["id"], "skipped": "token budget reached"}
        res = call(c, a.model, system, b, a)
        if "error" not in res:  # failed calls are not saved, so a rerun retries them
            res["system_file"] = system_file
            res["system_sha256"] = system_sha256
            if a.seed is not None:  # only recorded when given, so default rows are unchanged
                res["seed"] = a.seed
            (out / f"{b['id']}.json").write_text(json.dumps(res))
            u = res.get("usage") or {}
            with lock:
                spent[0] += (u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0)
        return res

    errors = skipped = 0
    with ThreadPoolExecutor(a.concurrency) as ex:
        for res in tqdm(ex.map(work, todo), total=len(todo)):
            errors += "error" in res
            skipped += "skipped" in res
    print(f"done, {errors} failed (rerun to retry), {skipped} skipped by budget, {spent[0]} tokens used")


if __name__ == "__main__":
    main()
