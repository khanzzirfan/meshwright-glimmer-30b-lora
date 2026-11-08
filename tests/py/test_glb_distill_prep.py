"""Tests for scripts/glb_distill_prep.py (docs/14, imp-5 US-007).

A tiny fake glb_generate.py run of five briefs pins the keep rule (two kept, one not ok, one unassembled,
one over budget) plus one refused id and one refused title; stats.json counts every drop reason by name and
mesh_lora_hf.py's own loader (mesh_lora_hf.check_data) accepts the writer's train.jsonl and val.jsonl.
"""
import json
from pathlib import Path

import pytest

import glb_distill_prep
import mesh_lora_hf
from tags import THINK_OPEN

ROOT = Path(__file__).resolve().parents[2]

# A real bench/glb/briefs.jsonl title (g001), so the title refusal is exercised against the real eval set.
EVAL_TITLE = "Wooden crate"

# x0001 hashes to train and x0004 to val at the default --val-frac 0.1, so the split leaves both files
# non-empty and mesh_lora_hf.check_data (which wants a row in each) accepts the output.
BRIEFS = [
    {"id": "x0001", "title": "Timber cabin", "brief": "A timber cabin with a steep roof.", "domain": "buildings", "level": 1, "style": "low-poly", "kind": "static"},
    {"id": "x0004", "title": "Stone bridge", "brief": "A stone bridge over a river.", "domain": "buildings", "level": 1, "style": "low-poly", "kind": "static"},
    {"id": "x0003", "title": "Red barn", "brief": "A red timber barn.", "domain": "buildings", "level": 1, "style": "low-poly", "kind": "static"},
    {"id": "x0005", "title": "Market kiosk", "brief": "A small market kiosk.", "domain": "buildings", "level": 1, "style": "low-poly", "kind": "static"},
    {"id": "x0006", "title": "Steel silo", "brief": "Two steel silos.", "domain": "buildings", "level": 1, "style": "low-poly", "kind": "set"},
    {"id": "g999", "title": "Not an eval title", "brief": "A g id.", "domain": "buildings", "level": 1, "style": "low-poly", "kind": "static"},
    {"id": "x0007", "title": EVAL_TITLE, "brief": "A crate-ish title.", "domain": "buildings", "level": 1, "style": "low-poly", "kind": "static"},
]


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_attempt(brief_id, run, *, ok, assembled, within_budget, obb=True, content="<html>asset</html>",
                  seed=1, repair=None, reasoning=None):
    """One brief's DIR/<id>/ with a result.json and a single attempt directory (raw + validation row)."""
    d = Path(run) / brief_id
    attempt = d / "attempts" / str(seed)
    (attempt / "raw").mkdir(parents=True, exist_ok=True)
    (attempt / "raw" / "asset.json").write_text(json.dumps({"content": content, "reasoning": reasoning}))
    (attempt / "validation.jsonl").write_text(json.dumps({
        "id": "asset", "ok": ok,
        "stats": {"glb": {"assembly": {"assembled": assembled, "assembled_obb": obb}}},
    }) + "\n")
    record = {"seed": seed, "ok": ok, "assembled": assembled, "parts": 10, "triangles": 100,
              "seconds": 1.0, "grounded_shift": None, "within_budget": within_budget}
    if repair:
        record["repair"] = repair
    (d / "result.json").write_text(json.dumps({
        "picked_seed": seed, "picked_ok": ok, "picked_assembled": assembled,
        "picked_within_budget": within_budget, "attempts": [record],
    }))


@pytest.fixture
def fake_run(tmp_path):
    briefs = tmp_path / "briefs.jsonl"
    briefs.write_text("".join(json.dumps(b) + "\n" for b in BRIEFS))
    run = tmp_path / "run"
    write_attempt("x0001", run, ok=True, assembled=True, within_budget=True, content="<html>cabin</html>")
    write_attempt("x0004", run, ok=True, assembled=True, within_budget=True, content="<html>a stone bridge</html>")
    write_attempt("x0003", run, ok=False, assembled=False, within_budget=False)
    write_attempt("x0005", run, ok=True, assembled=False, within_budget=True)
    write_attempt("x0006", run, ok=True, assembled=True, within_budget=False)
    # g999 and x0007 are refused by id/title before the run is read, so they get no result.json.
    system = tmp_path / "system.txt"
    system.write_text("You are the GLB coder.\n")
    return run, briefs, system


def run_main(out, run, briefs, system, *extra):
    glb_distill_prep.main(["--run", str(run), "--briefs", str(briefs), "--out", str(out),
                           "--system", str(system), *extra])


def test_fixture_keeps_two_rows_and_counts_drops_by_reason(tmp_path, fake_run, capsys):
    run, briefs, system = fake_run
    out = tmp_path / "out"
    run_main(out, run, briefs, system)

    stats = json.loads((out / "stats.json").read_text())
    assert stats["kept"] == 2
    assert stats["train"] == 1 and stats["val"] == 1
    # one not ok, one unassembled, one over budget, one g id and one eval title -> the rest stay zero.
    assert stats["dropped_by_reason"] == {
        "eval_id": 1, "eval_title": 1, "missing": 0, "not_ok": 1,
        "unassembled": 1, "over_budget": 1, "no_content": 0, "not_obb": 0,
    }
    assert stats["by_domain"] == {"buildings": 2}
    assert stats["by_kind"] == {"static": 2}
    assert {r["id"] for r in read_rows(out / "train.jsonl") + read_rows(out / "val.jsonl")} == {"x0001", "x0004"}
    assert "kept 2 (1 train, 1 val)" in capsys.readouterr().out


def test_rows_are_the_ccore_format_and_mesh_lora_hf_accepts_them(tmp_path, fake_run):
    run, briefs, system = fake_run
    out = tmp_path / "out"
    run_main(out, run, briefs, system)

    mesh_lora_hf.check_data(str(out))  # the loader asserts prompt/completion and a row in each split

    train = read_rows(out / "train.jsonl")
    row = next(r for r in train if r["id"] == "x0001")
    assert set(row) == {"id", "domain", "title", "prompt", "completion"}
    assert [m["role"] for m in row["prompt"]] == ["system", "user"]
    assert row["prompt"][0]["content"] == "You are the GLB coder.\n"
    assert row["prompt"][1]["content"] == "A timber cabin with a steep roof."
    assert row["completion"] == [{"role": "assistant", "content": "<html>cabin</html>"}]


def test_the_picked_attempt_reasoning_is_not_in_the_completion(tmp_path):
    run = tmp_path / "run"
    write_attempt("x0001", run, ok=True, assembled=True, within_budget=True,
                  content="<html>cabin</html>", reasoning="let me think about the roof")
    briefs = tmp_path / "briefs.jsonl"
    briefs.write_text(json.dumps(BRIEFS[0]) + "\n")
    system = tmp_path / "system.txt"
    system.write_text("sys\n")

    run_main(tmp_path / "out", run, briefs, system)

    row = read_rows(tmp_path / "out" / "train.jsonl")[0]
    assert row["completion"][0]["content"] == "<html>cabin</html>"
    assert "think about the roof" not in row["completion"][0]["content"]
    assert THINK_OPEN not in row["completion"][0]["content"]


def test_a_picked_repair_turn_uses_the_repair_directory(tmp_path):
    run = tmp_path / "run"
    # The sample (seed 1) failed; the error repair shares seed 1 and succeeded, so the repair is picked.
    d = run / "x0001"
    (d / "attempts" / "1" / "raw").mkdir(parents=True)
    (d / "attempts" / "1" / "raw" / "asset.json").write_text(json.dumps({"content": "<html>broken</html>"}))
    (d / "attempts" / "repair" / "raw").mkdir(parents=True)
    (d / "attempts" / "repair" / "raw" / "asset.json").write_text(json.dumps({"content": "<html>fixed</html>"}))
    (d / "result.json").write_text(json.dumps({
        "picked_seed": 1, "picked_ok": True, "picked_assembled": True, "picked_within_budget": True,
        "attempts": [
            {"seed": 1, "ok": False, "assembled": False, "parts": 0, "triangles": None, "within_budget": False},
            {"seed": 1, "ok": True, "assembled": True, "parts": 10, "triangles": 100,
             "within_budget": True, "repair": True},
        ],
    }))
    briefs = tmp_path / "briefs.jsonl"
    briefs.write_text(json.dumps(BRIEFS[0]) + "\n")
    system = tmp_path / "system.txt"
    system.write_text("sys\n")

    run_main(tmp_path / "out", run, briefs, system)

    row = read_rows(tmp_path / "out" / "train.jsonl")[0]
    assert row["completion"][0]["content"] == "<html>fixed</html>"


def test_require_obb_drops_a_kept_brief_whose_oriented_box_is_not_assembled(tmp_path):
    run = tmp_path / "run"
    write_attempt("x0001", run, ok=True, assembled=True, within_budget=True, obb=False)
    briefs = tmp_path / "briefs.jsonl"
    briefs.write_text(json.dumps(BRIEFS[0]) + "\n")
    system = tmp_path / "system.txt"
    system.write_text("sys\n")

    run_main(tmp_path / "out-plain", run, briefs, system)
    assert json.loads((tmp_path / "out-plain" / "stats.json").read_text())["kept"] == 1

    run_main(tmp_path / "out-obb", run, briefs, system, "--require-obb")
    stats = json.loads((tmp_path / "out-obb" / "stats.json").read_text())
    assert stats["kept"] == 0
    assert stats["dropped_by_reason"]["not_obb"] == 1


def test_a_missing_result_is_counted(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    briefs = tmp_path / "briefs.jsonl"
    briefs.write_text(json.dumps(BRIEFS[0]) + "\n")
    system = tmp_path / "system.txt"
    system.write_text("sys\n")

    run_main(tmp_path / "out", run, briefs, system)

    assert json.loads((tmp_path / "out" / "stats.json").read_text())["dropped_by_reason"]["missing"] == 1


def test_split_of_is_stable_and_respects_the_bounds():
    assert glb_distill_prep.split_of("x0042", 0.0) == "train"
    assert glb_distill_prep.split_of("x0042", 1.0) == "val"
    assert glb_distill_prep.split_of("x0042", 0.1) == glb_distill_prep.split_of("x0042", 0.1)
    # x0001 and x0004 were chosen to land in different splits at the default 0.1.
    assert glb_distill_prep.split_of("x0001", 0.1) == "train"
    assert glb_distill_prep.split_of("x0004", 0.1) == "val"


@pytest.mark.parametrize("sub", ["data/distill", "out/distill", "eval/distill", "data", "out", "eval"])
def test_out_inside_protected_roots_is_refused(tmp_path, fake_run, sub):
    run, briefs, system = fake_run
    with pytest.raises(SystemExit) as exc:
        run_main(ROOT / sub / "sft", run, briefs, system)
    assert exc.value.code != 0
