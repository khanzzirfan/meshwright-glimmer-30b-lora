import json
from pathlib import Path

import pytest

import glb_best_of
import glb_best_of_cost

ROOT = Path(__file__).resolve().parents[2]

BRIEFS = [
    {"id": "b1", "brief": "A vase.", "domain": "props_and_tools", "kind": "static"},
    {"id": "b2", "brief": "A crate.", "domain": "props_and_tools", "kind": "static"},
    {"id": "b3", "brief": "A tree.", "domain": "nature", "kind": "static"},
    {"id": "b4", "brief": "A rock.", "domain": "nature", "kind": "static"},
]


def asm(parts, share, assembled):
    return {"parts": parts, "components": 1, "largest_share": share, "floaters": 0,
            "min_y": 0, "ground_gap": 0, "tol": 0.1, "assembled": assembled}


def write_run(root, name, spec):
    """spec: {id: (ok, assembly_result_or_None, seconds)}."""
    d = root / name
    (d / "raw").mkdir(parents=True)
    rows, lines = [], []
    for brief_id, (ok, result, seconds) in spec.items():
        rows.append({"id": brief_id, "ok": ok, "reasons": [] if ok else ["bad_glb"],
                     "stats": {"glb": {"triangles": 1000}} if ok else {}})
        lines.append({"id": brief_id, "kind": "static", "assembly": result})
        (d / "raw" / f"{brief_id}.json").write_text(
            json.dumps({"id": brief_id, "usage": {"seconds": seconds}}))
    (d / "validation.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (d / "assembly.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines))
    return d


def make_env(tmp_path):
    """3 runs, 4 briefs: b1 stops at 1, b2 at 2, b3 never assembles, b4 has no ok candidate."""
    briefs = tmp_path / "briefs.jsonl"
    briefs.write_text("".join(json.dumps(b) + "\n" for b in BRIEFS))
    root = tmp_path / "runs"
    r1 = write_run(root, "run1", {
        "b1": (True, asm(10, 0.9, True), 10), "b2": (True, asm(10, 0.5, False), 11),
        "b3": (True, asm(10, 0.5, False), 12), "b4": (False, None, 13)})
    r2 = write_run(root, "run2", {
        "b1": (False, None, 20), "b2": (True, asm(10, 0.9, True), 21),
        "b3": (True, asm(12, 0.5, False), 22), "b4": (False, None, 23)})
    r3 = write_run(root, "run3", {
        "b1": (False, None, 30), "b2": (False, None, 31),
        "b3": (True, asm(14, 0.5, False), 32), "b4": (False, None, 33)})
    return [r1, r2, r3], briefs


def base_argv(runs, briefs, out=None):
    argv = ["--runs", *[str(r) for r in runs], "--briefs", str(briefs)]
    if out is not None:
        argv += ["--out", str(out)]
    return argv


def test_hand_computed_adaptive_versus_always(tmp_path):
    runs, briefs = make_env(tmp_path)
    out = tmp_path / "cost.json"
    glb_best_of_cost.main(base_argv(runs, briefs, out))
    report = json.loads(out.read_text())

    adaptive = report["adaptive"]
    assert adaptive["mean_samples"] == 2.25
    assert adaptive["mean_seconds"] == 44.25
    assert adaptive["median_seconds"] == 49.0
    assert adaptive["share_ok"] == 0.75
    assert adaptive["share_assembled"] == 0.5

    always = report["always_n"]
    assert always["samples"] == 3.0
    assert always["mean_seconds"] == 64.5
    assert always["median_seconds"] == 64.5
    assert always["share_ok"] == 0.75
    assert always["share_assembled"] == 0.5


def test_per_brief_samples_seconds_and_picks(tmp_path):
    runs, briefs = make_env(tmp_path)
    out = tmp_path / "cost.json"
    glb_best_of_cost.main(base_argv(runs, briefs, out))
    per_brief = json.loads(out.read_text())["per_brief"]

    assert [per_brief[b]["samples"] for b in ("b1", "b2", "b3", "b4")] == [1, 2, 3, 3]
    assert [per_brief[b]["seconds"] for b in ("b1", "b2", "b3", "b4")] == [10, 32, 66, 69]
    assert [per_brief[b]["picked_from"] for b in ("b1", "b2", "b3", "b4")] == [
        "run1", "run2", "run1", "run1"]
    assert per_brief["b1"]["assembled"] is True
    assert per_brief["b3"]["ok"] is True and per_brief["b3"]["assembled"] is False
    assert per_brief["b4"]["ok"] is False


def test_pick_is_imported_from_glb_best_of_not_duplicated(tmp_path, monkeypatch):
    runs, briefs = make_env(tmp_path)
    calls = []
    real_pick = glb_best_of.pick

    def spy(candidates):
        calls.append(list(candidates))
        return real_pick(candidates)

    monkeypatch.setattr(glb_best_of, "pick", spy)
    loaded = glb_best_of_cost.load_runs(runs)
    glb_best_of_cost.simulate_cost(loaded, glb_best_of.read_jsonl(briefs))

    # Every brief is scored with the imported picker (once per brief here).
    assert len(calls) == 4
    assert all(len(c) == 3 for c in calls)


def test_missing_assembly_jsonl_warns_and_counts_as_not_assembled(tmp_path, capsys):
    runs, briefs = make_env(tmp_path)
    (runs[0] / "assembly.jsonl").unlink()
    out = tmp_path / "cost.json"
    glb_best_of_cost.main(base_argv(runs, briefs, out))

    captured = capsys.readouterr()
    assert "run1 has no assembly.jsonl" in captured.err
    assert "count as not assembled" in captured.err

    per_brief = json.loads(out.read_text())["per_brief"]
    assert per_brief["b1"]["samples"] == 3  # run1 no longer stops it at sample 1
    assert per_brief["b1"]["assembled"] is False


def test_table_is_printed(tmp_path, capsys):
    runs, briefs = make_env(tmp_path)
    glb_best_of_cost.main(base_argv(runs, briefs))
    out = capsys.readouterr().out
    assert "adaptive" in out and "always-3" in out
    assert "2.25" in out and "64.50" in out


@pytest.mark.parametrize("sub", ["data/cost.json", "out/cost.json", "eval/cost.json"])
def test_out_inside_data_out_or_eval_is_refused(tmp_path, sub):
    runs, briefs = make_env(tmp_path)

    with pytest.raises(SystemExit) as exc:
        glb_best_of_cost.main(base_argv(runs, briefs, ROOT / sub))

    assert exc.value.code != 0
