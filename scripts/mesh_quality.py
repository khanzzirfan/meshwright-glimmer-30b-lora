"""Score a generated text mesh against the real object it was asked for, beyond 'is it valid'.

Metrics (all None when the answer does not validate):
  fscore      F-score of surface samples at a 4-bin tolerance (about 6% of the size), best over
              4 quarter turns x mirror, since the prompt does not fix which way the object faces
  iou         voxel IoU of surface samples on a 16^3 grid, same turns; stricter, shown for reference
  face_ratio  generated faces / reference faces (a 12-triangle box for a 170-triangle cone is ~0.07)
  colours     number of colour groups, generated vs reference
`detailed` is True when the mesh validates, fscore >= --min-fscore and face_ratio >= --min-face-ratio.

usage: python scripts/mesh_quality.py --run eval/mesh_baseline --objects data/mesh/objects.jsonl
       [--pairs data/mesh/baseline_pairs.jsonl]   # reference/generated pairs for preview_mesh.mjs
"""
import argparse
import json
import statistics
from pathlib import Path

import numpy as np

from mesh_validate import BINS, extract, validate

GRID = 16
TAU = 4.0  # F-score tolerance in bins, about 6% of the object's longest side


def load(text):
    """(verts float Nx3, faces int Mx3 zero-based, colour count) from mesh text that already validated."""
    v, f, c = [], [], 0
    for ln in text.splitlines():
        p = ln.split()
        if p[0] == "v":
            v.append([float(x) for x in p[1:4]])
        elif p[0] == "f":
            f.append([int(x) - 1 for x in p[1:4]])
        else:
            c += 1
    return np.array(v), np.array(f), c


def surface_points(v, f, n=6000, seed=0):
    """Area-weighted uniform samples on the triangles, so big flat faces and fine detail count fairly."""
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
    if area.sum() <= 0:
        return np.vstack([a, b, c])
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(f), n, p=area / area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    return (1 - s)[:, None] * a[idx] + (s * (1 - r2))[:, None] * b[idx] + (s * r2)[:, None] * c[idx]


def voxels(points):
    # scale by BINS-1 so the grid is symmetric about the centre and turns/mirrors land in the same cells
    q = np.clip((points / (BINS - 1) * GRID).astype(int), 0, GRID - 1)
    return set(map(tuple, q))


def variants(points):
    """4 quarter turns about the vertical axis, each with and without an x mirror."""
    m = (BINS - 1) / 2
    x, y, z = points[:, 0] - m, points[:, 1], points[:, 2] - m
    out = []
    for xx, zz in ((x, z), (-z, x), (-x, -z), (z, -x)):
        out.append(np.c_[xx + m, y, zz + m])
        out.append(np.c_[-xx + m, y, zz + m])
    return out


def nearest(a, b, chunk=1500):
    """Distance from each point in a to its nearest point in b (chunked brute force; a few thousand points)."""
    out = np.empty(len(a))
    for i in range(0, len(a), chunk):
        d = ((a[i:i + chunk, None, :] - b[None, :, :]) ** 2).sum(-1)
        out[i:i + chunk] = np.sqrt(d.min(1))
    return out


def fscore(gen_text, ref_text, tau=TAU, n=2000):
    """F-score at distance tau (in bins): share of each surface within tau of the other, best over turns/mirror.
    Unlike shell IoU it forgives small proportion and offset differences, which a vague caption cannot pin down."""
    gv, gf, _ = load(gen_text)
    rv, rf, _ = load(ref_text)
    ref = surface_points(rv, rf, n)
    best = 0.0
    for p in variants(surface_points(gv, gf, n)):
        prec = (nearest(p, ref) <= tau).mean()
        rec = (nearest(ref, p) <= tau).mean()
        if prec + rec:
            best = max(best, 2 * prec * rec / (prec + rec))
    return round(float(best), 3)


def iou(gen_text, ref_text):
    gv, gf, _ = load(gen_text)
    rv, rf, _ = load(ref_text)
    ref = voxels(surface_points(rv, rf))
    best = 0.0
    for p in variants(surface_points(gv, gf)):
        g = voxels(p)
        best = max(best, len(g & ref) / len(g | ref))
    return round(best, 3)


def score(answer, ref_text, min_fscore=0.5, min_face_ratio=0.25):
    ok, why, _ = validate(answer)
    if not ok:
        return {"valid": False, "reason": why, "fscore": None, "iou": None, "face_ratio": None, "colours": None, "detailed": False}
    gen = extract(answer)
    _, gf, gc = load(gen)
    _, rf, rc = load(ref_text)
    fs = fscore(gen, ref_text)
    fr = round(len(gf) / max(1, len(rf)), 3)
    return {"valid": True, "reason": "ok", "fscore": fs, "iou": iou(gen, ref_text), "face_ratio": fr, "colours": [gc, rc],
            "detailed": fs >= min_fscore and fr >= min_face_ratio}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="folder written by mesh_baseline.py (one JSON per id)")
    ap.add_argument("--objects", default="data/mesh/objects.jsonl")
    ap.add_argument("--min-fscore", type=float, default=0.5)
    ap.add_argument("--min-face-ratio", type=float, default=0.25)
    ap.add_argument("--pairs", default=None, help="write reference/generated rows for scripts/preview_mesh.mjs")
    a = ap.parse_args()

    refs = {json.loads(l)["id"]: json.loads(l) for l in Path(a.objects).read_text().splitlines() if l.strip()}
    rows, pairs = [], []
    for f in sorted(Path(a.run).glob("*.json")):
        if f.name in ("summary.json", "quality.json"):
            continue
        d = json.loads(f.read_text())
        ref = refs.get(d["id"])
        if not ref:
            continue
        s = score(d["answer"], ref["text"], a.min_fscore, a.min_face_ratio)
        rows.append({"id": d["id"], "caption": d["caption"], **s})
        print(f"{d['caption']:<24} valid={s['valid']!s:<5} fscore={s['fscore']!s:<6} iou={s['iou']!s:<6} faces={s['face_ratio']!s:<6} detailed={s['detailed']}")
        if a.pairs:
            pairs.append({"name": "REF " + d["caption"], "text": ref["text"]})
            pairs.append({"name": "GEN " + d["caption"], "text": extract(d["answer"]) if s["valid"] else "v 0 0 0"})
    if not rows:
        raise SystemExit("no results")
    valid = [r for r in rows if r["valid"]]
    summary = {
        "n": len(rows), "valid": len(valid), "detailed": sum(r["detailed"] for r in rows),
        "median_fscore_of_valid": statistics.median(r["fscore"] for r in valid) if valid else None,
        "median_iou_of_valid": statistics.median(r["iou"] for r in valid) if valid else None,
        "median_face_ratio_of_valid": statistics.median(r["face_ratio"] for r in valid) if valid else None,
        "thresholds": {"min_fscore": a.min_fscore, "min_face_ratio": a.min_face_ratio},
    }
    (Path(a.run) / "quality.json").write_text(json.dumps({"summary": summary, "items": rows}, indent=1))
    if a.pairs:
        Path(a.pairs).write_text("".join(json.dumps(p) + "\n" for p in pairs))
    print(summary)


if __name__ == "__main__":
    main()
