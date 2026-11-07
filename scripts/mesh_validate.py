"""Check a model-written text mesh. Used for the baseline, for dataset checks and for the student's eval."""
import re

import numpy as np

BINS = 64


def extract(answer):
    """Pull the mesh lines out of an answer that may be wrapped in a code fence or chatter."""
    m = re.search(r"```[a-z]*\n(.*?)```", answer, re.S)
    body = m.group(1) if m else answer
    return "\n".join(l.strip() for l in body.splitlines() if re.match(r"^\s*(v|c|f)\s", l))


def validate(answer):
    """Return (ok, reason, stats). Reasons: no_mesh, bad_line, out_of_range, bad_face, too_small, flat, small_span, unused_verts."""
    text = extract(answer)
    if not text:
        return False, "no_mesh", {}
    verts, faces, colours = [], [], 0
    for ln in text.splitlines():
        p = ln.split()
        try:
            if p[0] == "v":
                verts.append([int(x) for x in p[1:4]])
                if len(p) != 4:
                    return False, "bad_line", {}
            elif p[0] == "c":
                colours += 1
            else:
                faces.append([int(x) for x in p[1:4]])
                if len(p) != 4:
                    return False, "bad_line", {}
        except ValueError:
            return False, "bad_line", {}
    if len(verts) < 8 or len(faces) < 12:
        return False, "too_small", {"verts": len(verts), "faces": len(faces)}
    v = np.array(verts)
    if v.min() < 0 or v.max() > BINS - 1:
        return False, "out_of_range", {}
    f = np.array(faces)
    if f.min() < 1 or f.max() > len(v) or any(len(set(r)) < 3 for r in f.tolist()):
        return False, "bad_face", {}
    e = sorted((v.max(0) - v.min(0)).tolist())
    stats = {"verts": len(v), "faces": len(f), "colours": colours, "extents": e}
    if e[0] < 4:
        return False, "flat", stats
    if e[2] < 40:
        return False, "small_span", stats
    if len(set(f.ravel().tolist())) < 0.7 * len(v):
        return False, "unused_verts", stats
    return True, "ok", stats
