import json

import mesh_generate

from mesh_generate import clean_reply, run, strip_thinking

BOX_FACES = [(1, 2, 4), (1, 4, 3), (5, 7, 8), (5, 8, 6), (1, 5, 6), (1, 6, 2),
             (3, 4, 8), (3, 8, 7), (1, 3, 7), (1, 7, 5), (2, 6, 8), (2, 8, 4)]
GOOD = "\n".join([f"v {x} {y} {z}" for x in (0, 63) for y in (0, 63) for z in (0, 63)]
                 + ["c #888888"] + [f"f {a} {b} {c}" for a, b, c in BOX_FACES])


def test_strip_thinking():
    assert strip_thinking("<think>hmm</think>v 1 2 3") == "v 1 2 3"
    assert strip_thinking("v 1 2 3") == "v 1 2 3"


def test_run_scores_writes_and_resumes(tmp_path):
    items = [{"id": "a", "caption": "cube", "ref_tris": 12}, {"id": "b", "caption": "junk", "ref_tris": 12}]
    calls = []

    def gen(caption):
        calls.append(caption)
        return (GOOD if caption == "cube" else "I cannot do that"), 100, "stop"

    s = run(items, gen, tmp_path)
    assert s["pass"] == 1 and s["reasons"] == {"ok": 1, "no_mesh": 1} and s["hit_token_cap"] == 0
    assert json.loads((tmp_path / "a.json").read_text())["ok"] is True
    run(items, gen, tmp_path)
    assert calls == ["cube", "junk"]   # second run made no calls


def test_token_cap_is_counted(tmp_path):
    s = run([{"id": "a", "caption": "x", "ref_tris": 1}], lambda c: ("v 1 2", 8000, "length"), tmp_path)
    assert s["hit_token_cap"] == 1 and s["pass"] == 0


def test_batched_backend_is_used_and_resumes(tmp_path):
    items = [{"id": c, "caption": c, "ref_tris": 12} for c in "abcde"]
    calls = []

    def gen(caption):
        raise AssertionError("single path must not run")

    def many(caps):
        calls.append(list(caps))
        return [(GOOD, 50, "stop") for _ in caps]
    gen.many, gen.batch = many, 2
    s = run(items, gen, tmp_path)
    assert s["pass"] == 5 and calls == [["a", "b"], ["c", "d"], ["e"]]
    run(items, gen, tmp_path)
    assert len(calls) == 3


def test_clean_reply_drops_channel_header_and_control_tokens():
    assert clean_reply(" to=user<|message|>v 1 2 3\nf 1 2 3<|eot|><|pad|>") == "v 1 2 3\nf 1 2 3"
    assert clean_reply("v 1 2 3") == "v 1 2 3"


def test_runaway_detects_a_counting_loop_but_not_a_real_mesh():
    loop = "\n".join(f"v 31 63 {40 - i}" for i in range(8))
    assert mesh_generate.runaway(loop)
    real = "v 3 3 0\nv 60 0 3\nv 63 3 3\nv 60 3 63\nv 63 3 60\nv 60 0 60\nv 3 3 63"
    assert not mesh_generate.runaway(real)
    assert not mesh_generate.runaway("v 1 1 1\nv 1 1 1\nv 1 1 1\nv 1 1 1\nv 1 1 1\nv 1 1 1")
    assert not mesh_generate.runaway("v 31 63 32\nv 31 63 31")


def test_pick_best_prefers_the_first_valid_sample():
    import json as _json
    good = _json.loads(open("corpus/short_objects.jsonl").readline())["text"]
    i, n = mesh_generate.pick_best(["v 31 63", good, good])
    assert (i, n) == (1, 2)
    assert mesh_generate.pick_best(["junk", "junk"]) == (0, 0)


def test_pick_best_takes_the_consensus_when_three_samples_are_valid():
    import json as _json
    from mesh_validate import validate
    objs = [_json.loads(l)["text"] for l in open("corpus/short_objects.jsonl")]
    objs = [t for t in objs if validate(t)[0]]
    a = objs[0]
    b = max(objs, key=lambda t: sum(abs(x - y) for x, y in zip(mesh_generate.features(t), mesh_generate.features(a))))
    i, n = mesh_generate.pick_best([b, a, a])
    assert (i, n) == (1, 3)
