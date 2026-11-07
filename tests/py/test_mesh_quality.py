from mesh_quality import fscore, iou, score

BOX_FACES = [(1, 2, 4), (1, 4, 3), (5, 7, 8), (5, 8, 6), (1, 5, 6), (1, 6, 2),
             (3, 4, 8), (3, 8, 7), (1, 3, 7), (1, 7, 5), (2, 6, 8), (2, 8, 4)]


def box(x0, x1, z0, z1, y1=63):
    """A closed box as mesh text in the 0..63 format, 12 triangles."""
    return "\n".join([f"v {x} {y} {z}" for x in (x0, x1) for y in (0, y1) for z in (z0, z1)]
                     + ["c #888888"] + [f"f {a} {b} {c}" for a, b, c in BOX_FACES])


CUBE = box(0, 63, 0, 63)
POST = box(28, 35, 28, 35)       # tall thin post in the middle
SLAB = box(0, 63, 0, 20)         # long low wall, asymmetric in x/z


def test_identical_mesh_scores_full():
    s = score(CUBE, CUBE)
    assert s["valid"] and s["fscore"] == 1.0 and s["iou"] == 1.0 and s["face_ratio"] == 1.0 and s["detailed"]


def test_different_shape_scores_low():
    assert iou(POST, CUBE) < 0.3 and fscore(POST, CUBE) < 0.3
    assert not score(POST, CUBE)["detailed"]


def test_rotation_does_not_matter():
    assert iou(box(0, 20, 0, 63), SLAB) >= 0.95   # same slab turned a quarter


def test_invalid_answer_has_no_metrics():
    s = score("sorry, I cannot", CUBE)
    assert not s["valid"] and s["iou"] is None and not s["detailed"]


def test_too_few_faces_is_not_detailed():
    dense = CUBE + "\n" + "\n".join(f"f 1 2 {3 + i % 6}" for i in range(100))
    s = score(CUBE, dense)
    assert s["face_ratio"] < 0.25 and not s["detailed"]


def test_fscore_forgives_small_proportion_change():
    # a slightly narrower box (45 wide instead of 63) is the same idea; shell IoU punishes it, F-score less so
    narrow = box(9, 54, 9, 54)
    assert fscore(narrow, CUBE) > iou(narrow, CUBE)
