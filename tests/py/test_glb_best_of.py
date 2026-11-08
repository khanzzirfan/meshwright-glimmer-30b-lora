import json
from pathlib import Path

import pytest

import glb_best_of
import glb_report

ROOT = Path(__file__).resolve().parents[2]

BRIEFS = [
    {"id": "v1", "brief": "A vase.", "domain": "props_and_tools", "kind": "static"},
    {"id": "a1", "brief": "A crate.", "domain": "props_and_tools", "kind": "static"},
    {"id": "t1", "brief": "A tree.", "domain": "nature", "kind": "static"},
    {"id": "n1", "brief": "Never generated.", "domain": "nature", "kind": "static"},
]


def row(brief_id, ok, triangles=None):
    glb = {"ok": True, "triangles": triangles} if triangles is not None else None
    return {"id": brief_id, "ok": ok, "reasons": [] if ok else ["bad_glb"], "stats": {"glb": glb} if glb else {}}


def asm_result(parts, share, assembled):
    return {"parts": parts, "components": 1, "largest_share": share, "floaters": 0,
            "min_y": 0, "ground_gap": 0, "tol": 0.1, "assembled": assembled}


def write_run(root, name, rows, assembly, raw_ids, glb_ids=(), shot_ids=()):
    d = root / name
    (d / "raw").mkdir(parents=True)
    (d / "glb").mkdir()
    (d / "shots").mkdir()
    (d / "validation.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (d / "assembly.jsonl").write_text(
        "".join(json.dumps({"id": i, "kind": "static", "assembly": a}) + "\n" for i, a in assembly.items())
    )
    for brief_id in raw_ids:
        (d / "raw" / f"{brief_id}.json").write_text(
            json.dumps({"id": brief_id, "brief": {"id": brief_id}, "content": "<html></html>"})
        )
    for brief_id in glb_ids:
        (d / "glb" / f"{brief_id}.glb").write_bytes(b"glTF" + b"\x00" * 8)
    for brief_id in shot_ids:
        (d / "shots" / f"{brief_id}.png").write_bytes(b"png")
    return d


def make_env(tmp_path):
    """Three runs: v1 only valid in run3; a1 assembled only in run2; t1 identical in run1/run2."""
    briefs = tmp_path / "briefs.jsonl"
    briefs.write_text("".join(json.dumps(b) + "\n" for b in BRIEFS))
    root = tmp_path / "runs"
    r1 = write_run(root, "run1",
                   [row("v1", False), row("a1", True, 1000), row("t1", True, 1000)],
                   {"v1": None, "a1": asm_result(10, 0.5, False), "t1": asm_result(10, 0.9, True)},
                   raw_ids=["v1", "a1", "t1"], glb_ids=["a1"], shot_ids=["a1"])
    r2 = write_run(root, "run2",
                   [row("v1", False), row("a1", True, 1000), row("t1", True, 1000)],
                   {"v1": None, "a1": asm_result(10, 1.0, True), "t1": asm_result(10, 0.9, True)},
                   raw_ids=["v1", "a1", "t1"], glb_ids=["v1"])
    r3 = write_run(root, "run3",
                   [row("v1", True, 1000)],
                   {"v1": asm_result(10, 0.9, True)},
                   raw_ids=["v1"], glb_ids=["v1"], shot_ids=["v1"])
    return [r1, r2, r3], briefs


def base_argv(runs, briefs, out, *extra):
    return ["--runs", *[str(r) for r in runs], "--briefs", str(briefs), "--out", str(out), *extra]


def test_picks_the_run_where_the_brief_is_valid(tmp_path):
    runs, briefs = make_env(tmp_path)
    glb_best_of.main(base_argv(runs, briefs, tmp_path / "bench" / "best-of-3"))

    picks = json.loads((tmp_path / "bench" / "best-of-3" / "picks.json").read_text())
    assert picks["v1"]["picked_from"] == "run3"


def test_picks_the_assembled_candidate(tmp_path):
    runs, briefs = make_env(tmp_path)
    glb_best_of.main(base_argv(runs, briefs, tmp_path / "bench" / "best-of-3"))

    picks = json.loads((tmp_path / "bench" / "best-of-3" / "picks.json").read_text())
    assert picks["a1"]["picked_from"] == "run2"


def test_a_tie_picks_the_first_run(tmp_path):
    runs, briefs = make_env(tmp_path)
    glb_best_of.main(base_argv(runs, briefs, tmp_path / "bench" / "best-of-3"))

    picks = json.loads((tmp_path / "bench" / "best-of-3" / "picks.json").read_text())
    assert picks["t1"]["picked_from"] == "run1"


def test_picks_json_records_picked_from_for_every_brief(tmp_path, capsys):
    runs, briefs = make_env(tmp_path)
    out = tmp_path / "bench" / "best-of-3"
    glb_best_of.main(base_argv(runs, briefs, out))

    picks = json.loads((out / "picks.json").read_text())
    assert list(picks) == ["v1", "a1", "t1", "n1"]
    assert picks["n1"] == {"picked_from": None, "rank_keys": None}
    for brief_id in ("v1", "a1", "t1"):
        assert len(picks[brief_id]["rank_keys"]) == 6
    assert "picked 3 of 4 briefs" in capsys.readouterr().out


def test_winner_files_are_copied_with_picked_from(tmp_path):
    runs, briefs = make_env(tmp_path)
    out = tmp_path / "bench" / "best-of-3"
    glb_best_of.main(base_argv(runs, briefs, out))

    raw = json.loads((out / "raw" / "v1.json").read_text())
    assert raw["picked_from"] == "run3"
    assert (out / "glb" / "v1.glb").exists()
    assert (out / "shots" / "v1.png").exists()
    # a1's winner (run2) has no GLB, so nothing is copied for it
    assert (out / "raw" / "a1.json").exists()
    assert not (out / "glb" / "a1.glb").exists()

    rows = [json.loads(line) for line in (out / "validation.jsonl").read_text().splitlines()]
    assert [(r["id"], r["picked_from"]) for r in rows] == [
        ("v1", "run3"), ("a1", "run2"), ("t1", "run1"),
    ]
    lines = [json.loads(line) for line in (out / "assembly.jsonl").read_text().splitlines()]
    assert [line["id"] for line in lines] == ["v1", "a1", "t1"]
    assert lines[0]["kind"] == "static" and lines[0]["assembly"]["assembled"] is True


def test_build_report_runs_on_the_best_of_directory(tmp_path):
    runs, briefs = make_env(tmp_path)
    out = tmp_path / "bench" / "best-of-3"
    glb_best_of.main(base_argv(runs, briefs, out))

    report = glb_report.build_report(out.parent, briefs)

    assert "best-of-3" in report["models"]
    assert report["models"]["best-of-3"]["pass"] == 3
    assert report["models"]["best-of-3"]["assembly"] == {
        "valid": 3, "assembled": 3, "share": 1.0, "median_parts": 10
    }


def test_no_compute_without_assembly_jsonl_fails_clearly(tmp_path):
    runs, briefs = make_env(tmp_path)
    (runs[1] / "assembly.jsonl").unlink()
    out = tmp_path / "bench" / "best-of-3"

    with pytest.raises(SystemExit) as exc:
        glb_best_of.main(base_argv(runs, briefs, out, "--no-compute"))

    assert exc.value.code != 0
    assert not out.exists()


@pytest.mark.parametrize("sub", ["data/best3", "out/best3", "eval/best3", "data", "out", "eval"])
def test_out_inside_data_out_or_eval_is_refused(tmp_path, sub):
    runs, briefs = make_env(tmp_path)

    with pytest.raises(SystemExit) as exc:
        glb_best_of.main(base_argv(runs, briefs, ROOT / sub))

    assert exc.value.code != 0


def test_out_equal_to_an_input_is_refused(tmp_path):
    runs, briefs = make_env(tmp_path)

    with pytest.raises(SystemExit) as exc:
        glb_best_of.main(base_argv(runs, briefs, runs[0]))

    assert exc.value.code != 0


def test_rank_keys_are_the_docs_14_section_6_order():
    good_row = {"id": "x", "ok": True, "stats": {"glb": {"triangles": 1000}}}
    good_line = {"id": "x", "assembly": asm_result(10, 1.0, True)}
    assert glb_best_of.rank_keys(good_row, good_line, 0) == [1, 1, 1, 1, 1.0, 0]
    assert glb_best_of.rank_keys({"id": "y", "ok": False, "stats": {}}, None, 1) == [0, 0, 0, 0, -1.0, 1]
    out_of_range = {"id": "z", "assembly": asm_result(200, None, False)}
    assert glb_best_of.rank_keys({"id": "z", "ok": True, "stats": {"glb": {"triangles": 9000}}},
                                 out_of_range, 2) == [1, 0, 0, 0, -1.0, 2]


def test_pick_breaks_a_tie_by_run_order():
    first = {"rank_keys": [1, 1, 1, 1, 1.0, 0]}
    second = {"rank_keys": [1, 1, 1, 1, 1.0, 1]}
    assert glb_best_of.pick([first, second]) is first
    assert glb_best_of.pick([second, first]) is first
