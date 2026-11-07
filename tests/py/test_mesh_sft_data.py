import json
import random

from mesh_sft_data import row, transform, variants
from mesh_validate import validate

BOX_FACES = [(1, 2, 4), (1, 4, 3), (5, 7, 8), (5, 8, 6), (1, 5, 6), (1, 6, 2),
             (3, 4, 8), (3, 8, 7), (1, 3, 7), (1, 7, 5), (2, 6, 8), (2, 8, 4)]


def box(x0, x1, z0, z1, y1=63):
    return "\n".join([f"v {x} {y} {z}" for x in (x0, x1) for y in (0, y1) for z in (z0, z1)]
                     + ["c #888888"] + [f"f {a} {b} {c}" for a, b, c in BOX_FACES])


SLAB = box(0, 63, 0, 20)


def verts(text):
    return {tuple(map(int, l.split()[1:4])) for l in text.splitlines() if l.startswith("v ")}


def test_four_quarter_turns_is_identity():
    assert verts(transform(SLAB, 4)) == verts(SLAB)
    assert verts(transform(transform(SLAB, 1), 3)) == verts(SLAB)


def test_mirror_twice_is_identity_and_flips_winding_once():
    once = transform(SLAB, mirror=True)
    assert transform(once, mirror=True) == SLAB
    assert "f 1 4 2" in once and "f 1 2 4" not in once


def test_every_orientation_validates():
    for t in variants(SLAB, 8, random.Random(1)):
        assert validate(t)[0]


def test_variants_are_distinct_and_start_with_original():
    v = variants(SLAB, 8, random.Random(1))
    assert v[0] == SLAB and len(set(v)) == len(v) and len(v) >= 4
    assert variants(SLAB, 1, random.Random(1)) == [SLAB]


def test_row_is_conversational_prompt_completion():
    r = row("m00001", "a chair", SLAB, "v0")
    assert r["prompt"][0]["role"] == "system" and r["prompt"][1] == {"role": "user", "content": "a chair"}
    assert r["completion"][0]["role"] == "assistant" and r["completion"][0]["content"] == SLAB
    json.dumps(r)
