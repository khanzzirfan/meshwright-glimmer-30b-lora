import json
from pathlib import Path

import pytest

import glb_adaptive_ids
import glb_best_of

ROOT = Path(__file__).resolve().parents[2]

BRIEFS = [
    {"id": "b1", "brief": "A vase.", "domain": "props_and_tools", "kind": "static"},
    {"id": "b2", "brief": "A crate.", "domain": "props_and_tools", "kind": "static"},
    {"id": "b3", "brief": "A tree.", "domain": "nature", "kind": "static"},
    {"id": "b4", "brief": "A rock.", "domain": "nature", "kind": "static"},
    {"id": "b5", "brief": "A lamp.", "domain": "props_and_tools", "kind": "static"},
    {"id": "b6", "brief": "A sword.", "domain": "props_and_tools", "kind": "static"},
]


def asm(parts, share, assembled):
    return {"parts": parts, "components": 1, "largest_share": share, "floaters": 0,
            "min_y": 0, "ground_gap": 0, "tol": 0.1, "assembled": assembled}


def write_run(root, name, spec):
    """spec: {id: (ok, assembly_result_or_None)}."""
    d = root / name
    (d / "raw").mkdir(parents=True)
    rows, lines = [], []
    for brief_id, (ok, result) in spec.items():
        rows.append({"id": brief_id, "ok": ok, "reasons": [] if ok else ["bad_glb"],
                     "stats": {"glb": {"triangles": 1000}} if ok else {}})
        lines.append({"id": brief_id, "kind": "static", "assembly": result})
    (d / "validation.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (d / "assembly.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines))
    return d


def make_env(tmp_path):
    """3 runs, 6 briefs: b1 good in run1, b4 good only in run2, b2/b3/b5 only unassembled, b6 never ok."""
    briefs = tmp_path / "briefs.jsonl"
    briefs.write_text("".join(json.dumps(b) + "\n" for b in BRIEFS))
    root = tmp_path / "runs"
    r1 = write_run(root, "run1", {
        "b1": (True, asm(10, 0.9, True)), "b2": (True, asm(10, 0.5, False)), "b3": (False, None)})
    r2 = write_run(root, "run2", {
        "b2": (True, asm(10, 0.5, False)), "b4": (True, asm(10, 0.9, True))})
    r3 = write_run(root, "run3", {
        "b3": (True, asm(10, 0.5, False)), "b5": (True, asm(10, 0.5, False)), "b6": (False, None)})
    return [r1, r2, r3], briefs


def base_argv(runs, briefs, out, *extra):
    return ["--runs", *[str(r) for r in runs], "--briefs", str(briefs), "--out", str(out), *extra]


def ids_out(path):
    return path.read_text().splitlines()


def test_run_one_only_drops_the_brief_it_already_assembled(tmp_path, capsys):
    runs, briefs = make_env(tmp_path)
    out = tmp_path / "ids.txt"
    glb_adaptive_ids.main(base_argv(runs[:1], briefs, out))

    # b1 is good in run1; b2/b3 only unassembled or invalid; b4/b5/b6 have no run1 row.
    assert ids_out(out) == ["b2", "b3", "b4", "b5", "b6"]
    assert "remaining 5 of 6" in capsys.readouterr().out


def test_adding_run_two_drops_the_brief_it_assembled(tmp_path, capsys):
    runs, briefs = make_env(tmp_path)
    out = tmp_path / "ids.txt"
    glb_adaptive_ids.main(base_argv(runs[:2], briefs, out))

    # b4 is good only in run2; b2 stays (only ever unassembled); b3/b5/b6 still have no good candidate.
    assert ids_out(out) == ["b2", "b3", "b5", "b6"]
    assert "remaining 4 of 6" in capsys.readouterr().out


def test_unassembled_only_and_never_ok_briefs_stay(tmp_path):
    runs, briefs = make_env(tmp_path)
    out = tmp_path / "ids.txt"
    glb_adaptive_ids.main(base_argv(runs, briefs, out))

    remaining = ids_out(out)
    assert remaining == ["b2", "b3", "b5", "b6"]
    assert "b2" in remaining  # ok every run, assembled never
    assert "b6" in remaining  # ok never
    assert "b1" not in remaining and "b4" not in remaining  # good somewhere


def test_run_without_validation_jsonl_is_an_error(tmp_path):
    runs, briefs = make_env(tmp_path)
    (runs[0] / "validation.jsonl").unlink()
    out = tmp_path / "ids.txt"

    with pytest.raises(SystemExit) as exc:
        glb_adaptive_ids.main(base_argv(runs, briefs, out))

    assert exc.value.code != 0
    assert not out.exists()


def test_no_compute_without_assembly_jsonl_warns_and_counts_not_assembled(tmp_path, capsys):
    runs, briefs = make_env(tmp_path)
    (runs[0] / "assembly.jsonl").unlink()
    out = tmp_path / "ids.txt"
    glb_adaptive_ids.main(base_argv(runs[:2], briefs, out, "--no-compute"))

    captured = capsys.readouterr()
    assert "run1 has no assembly.jsonl" in captured.err
    assert "count as not assembled" in captured.err
    # run1's b1 no longer counts as assembled, so it stays; b4 is still dropped by run2.
    assert ids_out(out) == ["b1", "b2", "b3", "b5", "b6"]


def test_candidate_check_is_imported_from_glb_best_of(tmp_path, monkeypatch):
    runs, briefs = make_env(tmp_path)
    calls = []
    real = glb_best_of.candidates_for

    def spy(brief_id, loaded):
        calls.append(brief_id)
        return real(brief_id, loaded)

    monkeypatch.setattr(glb_best_of, "candidates_for", spy)
    loaded = glb_adaptive_ids.load_runs(runs, briefs, True)
    glb_adaptive_ids.remaining_ids(glb_best_of.read_jsonl(briefs), loaded)

    assert calls == ["b1", "b2", "b3", "b4", "b5", "b6"]


def test_output_is_one_id_per_line(tmp_path):
    runs, briefs = make_env(tmp_path)
    out = tmp_path / "nested" / "ids.txt"
    glb_adaptive_ids.main(base_argv(runs, briefs, out))

    assert out.read_text() == "b2\nb3\nb5\nb6\n"
