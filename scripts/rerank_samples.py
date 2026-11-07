"""Compare pick rules on already-sampled meshes: first, medoid and CLIP.

Glimmer v3/v4 produce valid meshes most of the time but the medoid rule keeps the
average box and throws recognisable shapes away. This tool re-judges one
``gen_*.samples.jsonl`` file for free: ``prepare`` turns its valid answers into
candidates, ``score`` renders nothing itself but scores every candidate's views
against its caption with CLIP and reports how the first, medoid and CLIP picks
compare on validity, caption match and caption retrieval.

``prepare --samples FILE --out-dir DIR`` writes, for rows ``{caption, picked, answers}``
(each row gets an id ``p000``, ``p001`` ... by line order when it has none):

* ``DIR/candidates.jsonl``: ``{name: '<id>_<k>', id, k, caption, text}`` for the valid
  answers only, ``text`` being ``mesh_validate.extract`` of the answer.
* ``DIR/prompts.json``: ``[{id, caption, n_valid}]``.
* ``DIR/samples.jsonl``: the input rows with their ids, so ``score`` can run the
  medoid rule on the original answers.

``score --out-dir DIR --views-dir VDIR`` embeds the rendered views (written by
``scripts/render_views.mjs``) with ``clip_score.score_folder`` and picks, per prompt:
first (lowest ``k``), medoid (``mesh_generate.pick_best`` on the original answers) and
clip (highest CLIP score, ties to the lowest ``k``). A prompt with no valid candidate is
a miss for every rule. It writes ``DIR/rerank_report.json`` and ``DIR/rerank_report.md``
plus ``DIR/sheet_medoid.jsonl`` and ``DIR/sheet_clip.jsonl`` for ``scripts/preview_mesh.mjs``.

There is no separate ``oracle`` rule: with a single scorer its pick is identical to the
CLIP pick, so CLIP is reported as the ceiling.

usage: python scripts/rerank_samples.py prepare --samples GEN.samples.jsonl --out-dir /tmp/rerank
       python scripts/rerank_samples.py score  --out-dir /tmp/rerank --views-dir /tmp/rerank/views
"""
import argparse
import json
import sys
from pathlib import Path

import clip_score
import mesh_generate
import mesh_validate
from proof_data import _protected_folder

VIEWS = 4
RULES = ("first", "medoid", "clip")
NEG_INF = float("-inf")


def load_jsonl(path):
    """Read a JSONL file into a list of rows."""
    text = Path(path).read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _line(item):
    return json.dumps(item) + "\n"


def prepare(samples_path, out_dir):
    """Validate every answer and write the candidates, prompts and samples files.

    Returns ``(candidates, prompts)``. Only valid answers become candidates, named
    ``<id>_<k>`` where ``k`` is the answer's index in the row.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    candidates, prompts, samples = [], [], []

    for i, row in enumerate(load_jsonl(samples_path)):
        pid = row.get("id") or f"p{i:03d}"
        caption = row["caption"]
        answers = row.get("answers", [])
        n_valid = 0
        for k, answer in enumerate(answers):
            ok, _reason, _stats = mesh_validate.validate(answer)
            if not ok:
                continue
            n_valid += 1
            candidates.append({"name": f"{pid}_{k}", "id": pid, "k": k, "caption": caption,
                               "text": mesh_validate.extract(answer)})
        prompts.append({"id": pid, "caption": caption, "n_valid": n_valid})
        samples.append({"id": pid, "caption": caption, "picked": row.get("picked"), "answers": answers})

    (out / "candidates.jsonl").write_text("".join(_line(c) for c in candidates))
    (out / "prompts.json").write_text(json.dumps(prompts, indent=1) + "\n")
    (out / "samples.jsonl").write_text("".join(_line(s) for s in samples))
    return candidates, prompts


def _view_paths(views_dir, name, views):
    """Paths of the ``views`` rendered angles for one candidate name."""
    return [Path(views_dir) / name / clip_score.VIEW_NAME.format(i) for i in range(views)]


def _medoid_pick(pid, answers, candidates_by_id):
    """The medoid candidate name for a prompt, or None when there is no valid answer."""
    index, n_valid = mesh_generate.pick_best(answers)
    if n_valid == 0:
        return None
    for candidate in candidates_by_id.get(pid, []):
        if candidate["k"] == index:
            return candidate["name"]
    return None


def _rule_metrics(picks, prompts, by_name, scores, views_dir, embedder, views):
    """Validity, mean CLIP score and caption retrieval for one pick rule.

    Misses (no candidate, or a candidate with no rendered views) count as a worst-rank
    row, so they lower recall but keep the retrieval denominator at every prompt.
    """
    captions = [p["caption"] for p in prompts]
    text_vecs = embedder.text(captions)
    view_cache, matrix, diagonal = {}, [], []
    for p in prompts:
        name = picks.get(p["id"])
        if name is None or name not in scores:
            matrix.append([NEG_INF] * len(prompts))
            continue
        if name not in view_cache:
            paths = [str(path) for path in _view_paths(views_dir, name, views)]
            view_cache[name] = embedder.images(paths)
        row = [clip_score.mesh_score(view_cache[name], text_vec) for text_vec in text_vecs]
        matrix.append(row)
        diagonal.append(scores[name])

    ranks = clip_score.retrieval_ranks(matrix)
    valid = sum(1 for p in prompts if picks.get(p["id"]) is not None)
    return {
        "valid": valid,
        "mean_clip": round(sum(diagonal) / len(diagonal), 4) if diagonal else 0.0,
        "r_at_1": round(clip_score.recall_at(ranks, 1), 4),
        "r_at_5": round(clip_score.recall_at(ranks, 5), 4),
    }


def _write_sheet(path, picks, by_name):
    """Write ``{name, text}`` rows for the picked candidates, skipping misses."""
    lines = [{"name": name, "text": by_name[name]["text"]}
             for name in picks.values() if name in by_name]
    Path(path).write_text("".join(_line(row) for row in lines))


def _write_markdown(path, report):
    rows = ["| rule | valid | mean_clip | r_at_1 | r_at_5 |",
            "|---|---|---|---|---|"]
    for rule in RULES:
        m = report[rule]
        rows.append(f"| {rule} | {m['valid']} | {m['mean_clip']} | {m['r_at_1']} | {m['r_at_5']} |")
    Path(path).write_text(f"prompts: {report['n_prompts']}\n\n" + "\n".join(rows) + "\n")


def score(out_dir, views_dir, embedder=None, views=VIEWS):
    """Score every candidate's views and report the first, medoid and CLIP picks.

    Pass a fake embedder to keep this offline; when ``embedder`` is None a
    ``clip_score.ClipEmbedder`` is built. Returns the report dict written to
    ``out_dir/rerank_report.json``.
    """
    out = Path(out_dir)
    candidates = load_jsonl(out / "candidates.jsonl")
    prompts = json.loads((out / "prompts.json").read_text())
    samples = {row["id"]: row for row in load_jsonl(out / "samples.jsonl")}
    if embedder is None:
        embedder = clip_score.ClipEmbedder()

    by_id, by_name = {}, {}
    for candidate in candidates:
        by_id.setdefault(candidate["id"], []).append(candidate)
        by_name[candidate["name"]] = candidate

    items = [{"name": c["name"], "caption": c["caption"]} for c in candidates]
    scores = clip_score.score_folder(views_dir, items, embedder, views=views)

    picks = {rule: {} for rule in RULES}
    for p in prompts:
        pid = p["id"]
        cands = by_id.get(pid, [])
        first = min(cands, key=lambda c: c["k"])["name"] if cands else None
        medoid = _medoid_pick(pid, samples[pid]["answers"], by_id) if cands else None
        scored = [c for c in cands if c["name"] in scores]
        clip = min(scored, key=lambda c: (-scores[c["name"]], c["k"]))["name"] if scored else None
        picks["first"][pid] = first
        picks["medoid"][pid] = medoid
        picks["clip"][pid] = clip

    report = {"n_prompts": len(prompts), "views": views, "picks": picks}
    for rule in RULES:
        report[rule] = _rule_metrics(picks[rule], prompts, by_name, scores, views_dir, embedder, views)

    (out / "rerank_report.json").write_text(json.dumps(report, indent=1) + "\n")
    _write_markdown(out / "rerank_report.md", report)
    _write_sheet(out / "sheet_medoid.jsonl", picks["medoid"], by_name)
    _write_sheet(out / "sheet_clip.jsonl", picks["clip"], by_name)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compare first, medoid and CLIP picks on sampled meshes.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    prep = sub.add_parser("prepare", help="validate answers and write candidates.jsonl")
    prep.add_argument("--samples", required=True, help="a gen_*.samples.jsonl file (read only)")
    prep.add_argument("--out-dir", required=True, help="folder for candidates.jsonl, prompts.json, samples.jsonl")

    sc = sub.add_parser("score", help="score candidates and compare the pick rules")
    sc.add_argument("--out-dir", required=True, help="the prepare folder")
    sc.add_argument("--views-dir", required=True, help="folder of rendered views from render_views.mjs")
    sc.add_argument("--views", type=int, default=VIEWS, help="views per mesh (default 4)")
    a = ap.parse_args(argv)

    blocked = _protected_folder(a.out_dir)
    if blocked:
        print(f"refusing to write inside {blocked}/: choose a work folder such as /tmp/rerank", file=sys.stderr)
        raise SystemExit(2)

    if a.cmd == "prepare":
        candidates, prompts = prepare(a.samples, a.out_dir)
        print(f"wrote {len(candidates)} valid candidate(s) for {len(prompts)} prompt(s) to {a.out_dir}")
    else:
        report = score(a.out_dir, a.views_dir, views=a.views)
        print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
