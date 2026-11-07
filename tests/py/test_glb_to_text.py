import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from glb_to_text import BINS, parse_text, to_text  # noqa: E402

CUBE_V = np.array([[x, y, z] for x in (0, 2) for y in (0, 4) for z in (0, 2)], float)
CUBE_T = [(0, 1, 3, "#ff0000"), (0, 3, 2, "#ff0000"), (4, 6, 7, "#00ff00")]


def test_normalises_to_unit_bins_and_ground():
    text, nv, nt = to_text(CUBE_V, CUBE_T)
    verts, faces, colours = parse_text(text)
    assert nt == faces == 3 and nv == len(verts)
    assert verts.min() >= 0 and verts.max() <= BINS - 1
    assert verts[:, 1].min() == 0 and verts[:, 1].max() == BINS - 1  # tallest axis fills the cube, sits on y=0
    assert colours == {"#ff0000", "#00ff00"}


def test_drops_degenerate_faces_and_duplicates():
    tris = CUBE_T + [(0, 0, 1, "#ff0000"), (0, 1, 3, "#ff0000")]
    _, _, nt = to_text(CUBE_V, tris)
    assert nt == 3


def test_parse_rejects_bad_index():
    with pytest.raises(ValueError):
        parse_text("v 0 0 0\nv 1 0 0\nc #fff\nf 1 2 9")


def test_sort_orders_vertices_zyx_and_keeps_the_same_mesh():
    import numpy as np
    import glb_to_text as g
    verts = np.array([[1.0, 1, 1], [0, 0, 0], [1, 0, 0], [0, 1, 1], [0, 0, 1]])
    tris = [(0, 1, 2, "#ffffff"), (3, 4, 0, "#ffffff"), (1, 2, 4, "#ffffff")]
    text, nv, nt = g.to_text(verts, tris, sort=True)
    pts = [tuple(map(int, l.split()[1:4])) for l in text.splitlines() if l.startswith("v ")]
    assert pts == sorted(pts, key=lambda p: (p[2], p[1], p[0]))
    plain, _, nt2 = g.to_text(verts, tris)
    assert nt == nt2 == 3
    tri = lambda t: sorted(sorted(tuple(pts_of(t)[i - 1] for i in map(int, l.split()[1:4]))) for l in t.splitlines() if l.startswith("f "))
    def pts_of(t): return [tuple(map(int, l.split()[1:4])) for l in t.splitlines() if l.startswith("v ")]
    assert tri(text) == tri(plain)


def test_sort_text_matches_to_text_sort():
    import numpy as np
    import glb_to_text as g
    verts = np.array([[1.0, 1, 1], [0, 0, 0], [1, 0, 0], [0, 1, 1], [0, 0, 1]])
    tris = [(0, 1, 2, "#ffffff"), (3, 4, 0, "#ffffff"), (1, 2, 4, "#aa0000")]
    plain, _, _ = g.to_text(verts, tris)
    assert g.sort_text(plain) == g.to_text(verts, tris, sort=True)[0]
