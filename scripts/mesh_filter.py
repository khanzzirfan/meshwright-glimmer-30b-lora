"""Keep only meshes that look like standalone objects; drop flat tiles, slabs and wall fragments.

Reads data/mesh/assets.jsonl, writes data/mesh/objects.jsonl with a rough `caption` taken from the
model name (a placeholder until real captions exist) and prints what was dropped and why.
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

from glb_to_text import parse_text

# name fragments of modular building pieces, not objects someone would ask for
PIECE = re.compile(
    r"road|sidewalk|curb|tile|slab|floor|wall|roof|trim|corner|straight|crossing|bridge|"
    r"doorframe|entrance|stairs_|window_|fence_|stripe|plane|ground|base|wheel|debris|detail|overhang|"
    r"low$|skyline|junction|split|end$|pit|ramp|decal|"
    r"brick|cornice|column|shutter|vine|hole|electricity|metal|stair|support|chimney|petal|pebble|rock_path|"
    r"wires|object|flat|round_|cross|double|wide|extended", re.I)


def extents(verts):
    return sorted(int(x) for x in (verts.max(0) - verts.min(0)))


def reject_reason(row):
    verts, faces, _ = parse_text(row["text"])
    e = extents(verts)
    if PIECE.search(row["name"]):
        return "piece_name"
    if faces < 12:
        return "too_few_faces"
    if e[0] < 4:
        return "flat"          # thinner than ~6% of its longest side
    if e[2] < 40:
        return "small_span"    # longest side does not fill the cube
    return None


def caption(name):
    s = re.sub(r"^q-", "", name)
    s = re.sub(r"[_\-]+", " ", s)
    s = re.sub(r"\b\d+\b", "", s)
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s or name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/mesh/assets.jsonl")
    ap.add_argument("--out", default="data/mesh/objects.jsonl")
    a = ap.parse_args()
    rows = [json.loads(l) for l in Path(a.inp).read_text().splitlines() if l.strip()]
    kept, why = [], Counter()
    for r in rows:
        w = reject_reason(r)
        if w:
            why[w] += 1
            continue
        r["caption"] = caption(r["name"])
        kept.append(r)
    Path(a.out).write_text("".join(json.dumps(r) + "\n" for r in kept))
    print(f"kept {len(kept)} of {len(rows)}; dropped {dict(why)}")
    print("by pack:", dict(Counter(r["pack"] for r in kept)))


if __name__ == "__main__":
    main()
