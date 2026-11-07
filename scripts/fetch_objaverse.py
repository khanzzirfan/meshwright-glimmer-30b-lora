"""Pick and download low-poly Objaverse objects with a licence we can train on, plus an attribution manifest.

Stage 1 (metadata only, no 3D download): reads the slim annotation file made from objaverse.load_annotations(),
keeps licence in --licenses, 40 <= faces <= --max-faces, no animation, wanted categories, and samples --n of them.
Stage 2: downloads the GLBs with objaverse.load_objects into --out/glb and writes --out/manifest.jsonl
(uid, name, author, licence, source url, faces, categories, tags) so CC-BY attribution can ship with the model.
Captions come later (Cap3D csv or a vision model). Run: .venv/bin/python scripts/fetch_objaverse.py --n 3000
"""
import argparse
import json
import random
from pathlib import Path

WANTED = {"furniture-home", "food-drink", "nature-plants", "cars-vehicles", "animals-pets", "electronics-gadgets",
          "architecture", "science-technology", "places-travel", "fashion-style", "cultural-heritage-history"}


def select(ann, licenses, max_faces, n, seed=1, wanted=WANTED, min_faces=40, skip=0):
    """ann: {uid: {license, faces, anim, cats, ...}} -> list of uids, deterministic for a seed."""
    ok = sorted(u for u, v in ann.items()
                if v["license"] in licenses and v.get("faces") and min_faces <= v["faces"] <= max_faces
                and not v.get("anim") and wanted & set(v.get("cats") or []))
    random.Random(seed).shuffle(ok)
    return ok[skip:skip + n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slim", default="/tmp/scrape/ann_slim.json")
    ap.add_argument("--out", default="/tmp/scrape/objaverse_pick")
    ap.add_argument("--licenses", default="cc0,by")
    ap.add_argument("--max-faces", type=int, default=300)
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--skip", type=int, default=0, help="skip this many of the shuffled candidates (e.g. the 3000 already fetched)")
    ap.add_argument("--select-only", action="store_true")
    a = ap.parse_args()
    ann = json.load(open(a.slim))
    uids = select(ann, set(a.licenses.split(",")), a.max_faces, a.n, skip=a.skip)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "manifest.jsonl", "w") as f:
        for u in uids:
            v = ann[u]
            f.write(json.dumps({"uid": u, "name": v["name"], "author": v["user"], "license": v["license"],
                                "url": v["uri"], "faces": v["faces"], "cats": v["cats"], "tags": v["tags"]}) + "\n")
    print(f"selected {len(uids)}")
    if a.select_only:
        return
    import objaverse
    objaverse.BASE_PATH = str(out / "cache")
    got = objaverse.load_objects(uids, download_processes=8)
    paths = {u: p for u, p in got.items() if p and Path(p).exists()}
    json.dump(paths, open(out / "paths.json", "w"))
    print(f"downloaded {len(paths)} of {len(uids)}")


if __name__ == "__main__":
    main()
