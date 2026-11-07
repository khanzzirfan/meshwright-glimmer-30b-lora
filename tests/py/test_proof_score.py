import importlib
import json
import sys

from proof_data import caption_text, completion_text, load_rows
from proof_score import compare, make_mlx_gen, score_run, system_from_train, write_report


def targets(fixtures, n=3):
    rows = load_rows(fixtures / "proof" / "train.jsonl")
    return [{"id": row["id"], "caption": caption_text(row), "mesh": completion_text(row)}
            for row in rows[:n]]


def changed_copy(mesh):
    lines = mesh.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("f "):
            old = line
            lines[index] = "f 1 2 5"
            assert lines[index] != old
            break
    return "\n".join(lines)


def test_compare_exact_copy_is_exact_valid_and_stopped(fixtures):
    target = targets(fixtures, 1)[0]
    result = compare(target["mesh"], target["mesh"], 100, 1000)
    assert result["exact"] is True
    assert result["valid"] is True
    assert result["reason"] == "ok"
    assert result["stopped"] is True
    assert result["lines_identical"] == result["lines_total"] == len(target["mesh"].splitlines())
    assert result["tokens"] == 100


def test_compare_strips_surrounding_whitespace(fixtures):
    target = targets(fixtures, 1)[0]
    result = compare("\n\n" + target["mesh"] + "\n\n", target["mesh"], 10, 100)
    assert result["exact"] is True


def test_compare_one_changed_line_is_not_exact(fixtures):
    target = targets(fixtures, 1)[0]
    result = compare(changed_copy(target["mesh"]), target["mesh"], 50, 1000)
    assert result["exact"] is False
    assert result["lines_identical"] == result["lines_total"] - 1


def test_compare_runaway_at_the_token_cap_did_not_stop(fixtures):
    target = targets(fixtures, 1)[0]
    runaway = "\n".join(["v 0 0 0"] * 400)
    result = compare(runaway, target["mesh"], 64, 64)
    assert result["stopped"] is False
    assert result["valid"] is False
    assert result["exact"] is False
    assert result["reason"] == "too_small"


def test_compare_non_mesh_answer_is_invalid_but_stopped(fixtures):
    target = targets(fixtures, 1)[0]
    result = compare("I cannot draw that mesh.", target["mesh"], 12, 100)
    assert result["valid"] is False
    assert result["reason"] == "no_mesh"
    assert result["exact"] is False
    assert result["stopped"] is True


def test_score_run_mixed_report_has_only_computed_numbers(fixtures):
    three = targets(fixtures, 3)
    outputs = {
        three[0]["caption"]: (three[0]["mesh"], 10),
        three[1]["caption"]: (changed_copy(three[1]["mesh"]), 20),
        three[2]["caption"]: ("no mesh here", 100),
    }
    report = score_run(three, lambda caption: outputs[caption], 100)

    assert report["n"] == 3
    assert report["exact"] == 1
    assert report["valid"] == 2
    assert report["stopped"] == 2
    lines_total = sum(item["lines_total"] for item in report["items"])
    lines_identical = sum(item["lines_identical"] for item in report["items"])
    assert report["lines_identical_share"] == lines_identical / lines_total
    assert [item["id"] for item in report["items"]] == [target["id"] for target in three]
    assert set(report) == {"n", "exact", "valid", "stopped", "lines_identical_share", "items"}


def test_write_report_round_trips_the_tested_report(fixtures, tmp_path):
    three = targets(fixtures, 3)
    report = score_run(three, lambda caption: (three[0]["mesh"], 10), 100)
    out = tmp_path / "report.json"
    assert write_report(report, out) == report
    assert json.loads(out.read_text()) == report


def test_system_from_train_reads_the_first_system_message(fixtures):
    text = system_from_train(fixtures / "proof" / "train.jsonl")
    assert text.startswith("You write low-poly 3D models as plain text.")


def test_import_does_not_import_mlx_lm():
    sys.modules.pop("mlx_lm", None)
    import proof_score
    importlib.reload(proof_score)
    assert "mlx_lm" not in sys.modules
    assert callable(make_mlx_gen)


def test_cut_off_runaway_is_not_stopped_even_if_gen_reports_the_cap():
    # make_mlx_gen reports max_tokens when the generator's finish_reason is "length"; compare must read that as not stopped
    r = compare("v 1 2 3\nv 4 5", "v 1 2 3", 8000, 8000)
    assert r["stopped"] is False and r["valid"] is False
