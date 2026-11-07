"""Convert CC0 kit GLB models to compact text meshes (LLaMA-Mesh style) for SFT.

Each model becomes: a unit-cube-normalised, 0..BINS-1 quantised OBJ-like text with
`v x y z` and `f a b c` lines, plus `c #rrggbb` lines that start a colour group.
Writes one JSON line per model to --out and, with --check, round-trips every text
back to geometry to confirm it still parses and is not degenerate.
"""
import argparse
import json
import struct
from pathlib import Path

import numpy as np

BINS = 64
COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb(path):
    b = Path(path).read_bytes()
    if b[:4] != b"glTF":
        raise ValueError("not a GLB")
    n = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + n])
    off = 20 + n
    binary = b""
    while off + 8 <= len(b):
        ln, kind = struct.unpack("<II", b[off:off + 8])
        if kind == 0x004E4942:
            binary = b[off + 8:off + 8 + ln]
            break
        off += 8 + ln
    return j, binary


def accessor(j, binary, idx):
    a = j["accessors"][idx]
    if "bufferView" not in a:
        return np.zeros((a["count"], NCOMP[a["type"]]), COMP[a["componentType"]])
    bv = j["bufferViews"][a["bufferView"]]
    dt, nc = np.dtype(COMP[a["componentType"]]), NCOMP[a["type"]]
    stride = bv.get("byteStride") or dt.itemsize * nc
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    buf = np.frombuffer(binary, np.uint8)
    rows = [np.frombuffer(buf[start + i * stride:start + i * stride + dt.itemsize * nc].tobytes(), dt) for i in range(a["count"])] \
        if stride != dt.itemsize * nc else None
    if rows is not None:
        return np.stack(rows)
    return np.frombuffer(binary, dt, a["count"] * nc, start).reshape(a["count"], nc)


def node_matrix(n):
    if "matrix" in n:
        return np.array(n["matrix"], float).reshape(4, 4).T
    t = np.array(n.get("translation", [0, 0, 0]), float)
    x, y, z, w = n.get("rotation", [0, 0, 0, 1])
    s = np.array(n.get("scale", [1, 1, 1]), float)
    r = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    m = np.eye(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m


def material_hex(j, mi):
    if mi is None:
        return "#b0b0b0"
    pbr = j["materials"][mi].get("pbrMetallicRoughness", {})
    c = pbr.get("baseColorFactor", [0.7, 0.7, 0.7, 1])[:3]
    lin = [min(1, max(0, v)) for v in c]
    srgb = [12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055 for v in lin]
    return "#" + "".join(f"{round(v * 255):02x}" for v in srgb)


def collect(j, binary):
    """Return (verts Nx3 world-space, tris list of (a,b,c,colour)) merged across the scene."""
    verts, tris = [], []

    def walk(ni, parent):
        n = j["nodes"][ni]
        m = parent @ node_matrix(n)
        if "mesh" in n:
            for pr in j["meshes"][n["mesh"]]["primitives"]:
                if pr.get("mode", 4) != 4:
                    continue
                pos = accessor(j, binary, pr["attributes"]["POSITION"]).astype(float)
                world = (np.c_[pos, np.ones(len(pos))] @ m.T)[:, :3]
                idx = accessor(j, binary, pr["indices"]).astype(int).ravel() if "indices" in pr else np.arange(len(pos))
                base = sum(len(v) for v in verts)
                col = material_hex(j, pr.get("material"))
                verts.append(world)
                tris.extend((base + idx[i], base + idx[i + 1], base + idx[i + 2], col) for i in range(0, len(idx) - 2, 3))
        for c in n.get("children", []):
            walk(c, m)

    scene = j["scenes"][j.get("scene", 0)]
    for r in scene["nodes"]:
        walk(r, np.eye(4))
    return (np.vstack(verts) if verts else np.zeros((0, 3))), tris


def to_text(verts, tris, sort=False):
    """Normalise to the unit cube (longest side = 1, base on y=0), quantise, dedupe, emit text.

    sort=True orders vertices by z, then y, then x and each colour group's faces by lowest vertex index (LLaMA-Mesh style),
    so neighbouring vertices are numerically close and the sequence is canonical.
    """
    lo, hi = verts.min(0), verts.max(0)
    size = (hi - lo).max()
    if size <= 0:
        raise ValueError("zero-size mesh")
    centre = (lo + hi) / 2
    norm = (verts - centre) / size  # -0.5..0.5
    norm[:, 1] += 0.5 - (hi[1] - lo[1]) / size / 2  # sit on the ground plane
    q = np.clip(np.round((norm + 0.5) * (BINS - 1)), 0, BINS - 1).astype(int)
    remap, out_v = {}, []
    for i, p in enumerate(map(tuple, q)):
        if p not in remap:
            remap[p] = len(out_v) + 1
            out_v.append(p)
        remap[i] = remap[p]
    if sort:
        order = sorted(range(len(out_v)), key=lambda i: (out_v[i][2], out_v[i][1], out_v[i][0]))
        new = {old + 1: k + 1 for k, old in enumerate(order)}
        out_v = [out_v[i] for i in order]
        remap = {k: new[v] for k, v in remap.items()}
    groups = {}
    for a, b, c, col in tris:
        f = (remap[a], remap[b], remap[c])
        if len(set(f)) < 3:
            continue
        groups.setdefault(col, []).append(f)
    if sort:
        def canon(f):  # rotate so the lowest index comes first, keeping the winding
            k = f.index(min(f))
            return f[k:] + f[:k]
        groups = {col: sorted(canon(f) for f in fs) for col, fs in groups.items()}
    lines = [f"v {x} {y} {z}" for x, y, z in out_v]
    for col, fs in groups.items():
        lines.append(f"c {col}")
        lines.extend(f"f {a} {b} {c}" for a, b, c in dict.fromkeys(fs))
    ntri = sum(len(set(fs)) for fs in groups.values())
    return "\n".join(lines), len(out_v), ntri


def sort_text(text):
    """Canonical ordering of an existing text mesh: vertices by z,y,x, faces by lowest vertex index per colour group."""
    vs, groups, col = [], {}, None
    for ln in text.splitlines():
        p = ln.split()
        if p[0] == "v":
            vs.append(tuple(map(int, p[1:4])))
        elif p[0] == "c":
            col = p[1]
        elif p[0] == "f":
            groups.setdefault(col, []).append(tuple(map(int, p[1:4])))
    order = sorted(range(len(vs)), key=lambda i: (vs[i][2], vs[i][1], vs[i][0]))
    new = {old + 1: k + 1 for k, old in enumerate(order)}

    def canon(f):
        f = tuple(new[i] for i in f)
        k = f.index(min(f))
        return f[k:] + f[:k]
    lines = [f"v {x} {y} {z}" for x, y, z in (vs[i] for i in order)]
    for c, fs in groups.items():
        lines.append(f"c {c}")
        lines.extend(f"f {a} {b} {d}" for a, b, d in sorted(canon(f) for f in fs))
    return "\n".join(lines)


def parse_text(text):
    """Round-trip: back to (verts, faces, colours). Raises on bad index or bad line."""
    verts, faces = [], 0
    colours = set()
    for ln in text.splitlines():
        p = ln.split()
        if p[0] == "v":
            verts.append([int(x) for x in p[1:4]])
        elif p[0] == "c":
            colours.add(p[1])
        elif p[0] == "f":
            ids = [int(x) for x in p[1:4]]
            if any(i < 1 or i > len(verts) for i in ids) or len(set(ids)) < 3:
                raise ValueError("bad face")
            faces += 1
        else:
            raise ValueError("bad line " + ln)
    return np.array(verts), faces, colours


def pack_of(path):
    """kit name from .../<vendor>/<kit>/<version>/models/x.glb; else the folder the file sits in"""
    parts = Path(path).parts
    return "/".join(parts[-5:-3]) if "models" in parts else parts[-2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", action="append", required=True, help="kit folder (repeatable), e.g. special-kits/kenney")
    ap.add_argument("--out", default="data/mesh/assets.jsonl")
    ap.add_argument("--max-tris", type=int, default=2000)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--sort", action="store_true", help="sort vertices by z,y,x and faces by lowest index")
    a = ap.parse_args()

    seen, rows, skipped = set(), [], {"too_big": 0, "empty": 0, "dup": 0, "error": 0}
    for root in a.root:
        for f in sorted(Path(root).rglob("*.glb")):
            if "clay" in f.parts or "original" in f.parts:  # untextured copies of the same models
                continue
            try:
                j, binary = read_glb(f)
                verts, tris = collect(j, binary)
                if not len(tris):
                    skipped["empty"] += 1
                    continue
                if len(tris) > a.max_tris * 4:  # cheap pre-filter before quantising
                    skipped["too_big"] += 1
                    continue
                text, nv, nt = to_text(verts, tris, sort=a.sort)
                if nt == 0 or nt > a.max_tris:
                    skipped["too_big" if nt else "empty"] += 1
                    continue
                if text in seen:
                    skipped["dup"] += 1
                    continue
                seen.add(text)
                if a.check:
                    parse_text(text)
                rows.append({"id": f"m{len(rows):05d}", "name": f.stem, "pack": pack_of(f),
                             "source": str(f), "verts": nv, "tris": nt, "text": text})
            except Exception as e:
                skipped["error"] += 1
                print("skip", f.name, e)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    t = sorted(r["tris"] for r in rows)
    print(f"kept {len(rows)}  skipped {skipped}")
    if t:
        print(f"tris median {t[len(t) // 2]}  p90 {t[int(len(t) * .9)]}  max {t[-1]}  chars median {sorted(len(r['text']) for r in rows)[len(rows) // 2]}")


if __name__ == "__main__":
    main()
