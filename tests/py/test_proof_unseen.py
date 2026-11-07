import json

import pytest

import proof_unseen

MESH = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3"


def objs(*ids):
    return [{"id": i, "caption": f"cap {i}", "text": MESH} for i in ids]


def test_build_keeps_heldout_out_of_train():
    train, valid, targets = proof_unseen.build(objs("a", "b", "c"), ["a", "b"], ["c"], 2)
    assert len(train) == 4 and len(valid) == 1
    assert all("cap c" not in json.dumps(r) for r in train)
    assert targets == [{"id": "c", "caption": "cap c", "mesh": MESH}]


def test_build_rejects_overlap_and_unknown_ids():
    with pytest.raises(ValueError, match="both"):
        proof_unseen.build(objs("a"), ["a"], ["a"], 1)
    with pytest.raises(ValueError, match="unknown"):
        proof_unseen.build(objs("a"), ["a"], ["zz"], 1)


def test_build_drops_meshes_over_max_lines():
    long = {"id": "d", "caption": "cap d", "text": "\n".join(["v 0 0 0"] * 50)}
    train, valid, targets = proof_unseen.build(objs("a", "c") + [long], ["a", "d"], ["c"], 1, max_lines=10)
    assert len(train) == 1 and len(valid) == 1


def test_shipped_split_has_no_overlap_and_known_ids():
    train, holdout = proof_unseen.load_split("corpus/short_split.json")
    ids = {json.loads(l)["id"] for l in open("corpus/short_objects.jsonl")}
    assert not set(train) & set(holdout)
    assert set(train) | set(holdout) == ids


def test_build_sort_gives_sorted_vertices_everywhere():
    objs = [{"id": "a", "caption": "x", "text": "v 5 5 5\nv 0 0 0\nv 9 0 0\nc #ffffff\nf 1 2 3"}]
    train, valid, targets = proof_unseen.build(
        objs + [{"id": "b", "caption": "y", "text": objs[0]["text"]}], ["a"], ["b"], 3, sort=True)
    for t in [r["messages"][2]["content"] for r in train + valid] + [t["mesh"] for t in targets]:
        pts = [tuple(map(int, l.split()[1:4])) for l in t.splitlines() if l.startswith("v ")]
        assert pts == sorted(pts, key=lambda p: (p[2], p[1], p[0]))
