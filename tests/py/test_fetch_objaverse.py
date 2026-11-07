import fetch_objaverse as fo


def ann():
    base = {"anim": 0, "cats": ["furniture-home"], "name": "x", "user": "u", "uri": "", "tags": []}
    return {
        "a": {**base, "license": "cc0", "faces": 100},
        "b": {**base, "license": "by", "faces": 300},
        "c": {**base, "license": "by-nc", "faces": 100},
        "d": {**base, "license": "by", "faces": 900},
        "e": {**base, "license": "by", "faces": 100, "anim": 2},
        "f": {**base, "license": "by", "faces": 100, "cats": ["people"]},
        "g": {**base, "license": "by", "faces": 10},
    }


def test_select_keeps_only_licensed_small_static_wanted():
    assert sorted(fo.select(ann(), {"cc0", "by"}, 300, 10)) == ["a", "b"]


def test_select_is_deterministic_and_capped():
    assert fo.select(ann(), {"cc0", "by"}, 300, 1) == fo.select(ann(), {"cc0", "by"}, 300, 1)
    assert len(fo.select(ann(), {"cc0", "by"}, 300, 1)) == 1


def test_skip_gives_disjoint_batches():
    base = {"anim": 0, "cats": ["furniture-home"], "name": "x", "user": "u", "uri": "", "tags": [], "license": "by", "faces": 100}
    many = {f"u{i}": dict(base) for i in range(20)}
    a = fo.select(many, {"by"}, 300, 8)
    b = fo.select(many, {"by"}, 300, 8, skip=8)
    assert not set(a) & set(b) and len(b) == 8
