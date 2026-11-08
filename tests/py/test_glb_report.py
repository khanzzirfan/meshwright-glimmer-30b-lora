import json
import shutil
from pathlib import Path

import glb_report

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "glb_bench"
BRIEFS = FIXTURES / "briefs.jsonl"
RATINGS = FIXTURES / "rating.csv"
KEY_MAP = FIXTURES / "key_map.json"

IMP = ROOT / "tests" / "fixtures" / "imp" / "report"
IMP_BRIEFS = IMP / "briefs.jsonl"
IMP_RATINGS = IMP / "rating.csv"
IMP_KEY_MAP = IMP / "key_map.json"


def model(name):
    return glb_report.load_model(FIXTURES / name)


def all_metrics():
    briefs = glb_report.load_briefs(BRIEFS)
    return {name: glb_report.metrics(model(name)["rows"], model(name)["raws"], briefs)
            for name in ("m_a", "m_b")}


def test_wilson_known_values():
    low, high = glb_report.wilson(24, 48)
    assert (round(low, 3), round(high, 3)) == (0.364, 0.636)
    assert glb_report.wilson(0, 48)[0] == 0
    assert round(glb_report.wilson(48, 48)[1], 6) == 1
    assert glb_report.wilson(0, 0) == (0.0, 1.0)


def test_load_model_reads_validation_and_raw_usage():
    loaded = model("m_a")
    assert len(loaded["rows"]) == 5
    assert loaded["rows"][0]["id"] == "b1"
    assert loaded["raws"]["b1"]["usage"]["completion_tokens"] == 100
    assert loaded["raws"]["b5"]["usage"]["seconds"] == 5.0


def test_metrics_are_computed_from_rows_and_briefs():
    m = all_metrics()["m_a"]
    assert m["n"] == 6
    assert m["pass"] == 3
    assert round(m["pass_rate"], 3) == 0.5
    assert (round(m["wilson"][0], 3), round(m["wilson"][1], 3)) == (0.188, 0.812)
    assert m["export"] == 4
    assert m["triangles"] == {"median": 200, "max": 300, "share_le_5000": 1.0}
    assert m["cost"] == {
        "median_completion_tokens": 300,
        "median_seconds": 3.0,
        "total_seconds": 15.0,
    }
    assert m["by_domain"]["nature"] == {"pass": 1, "total": 1}


def test_animated_pass_needs_pass_and_more_than_zero_animations():
    m = all_metrics()["m_a"]
    assert m["animated"] == {"pass": 1, "total": 2, "rate": 0.5}
    briefs = glb_report.load_briefs(BRIEFS)
    rows = model("m_a")["rows"]
    b4 = next(row for row in rows if row["id"] == "b4")
    assert b4["ok"] is True
    assert b4["stats"]["glb"]["animations"] == 0
    b3 = next(row for row in rows if row["id"] == "b3")
    assert b3["stats"]["glb"]["animations"] == 1
    kind = {brief["id"]: brief["kind"] for brief in briefs}
    assert kind["b4"] == "animated"


def test_missing_brief_counts_as_failure_with_reason_missing():
    m = all_metrics()["m_a"]
    assert m["failures"] == {"bad_glb": 1, "missing": 1, "no_export_button": 1}
    assert m["pass"] == 3
    assert m["n"] == 6


def test_head_to_head_counts():
    a = {"b1": True, "b2": False, "b3": True, "b4": True, "b5": False, "b6": False}
    b = {"b1": True, "b2": True, "b3": True, "b4": False, "b5": False, "b6": True}
    assert glb_report.head_to_head(a, b) == {"both": 2, "only_a": 1, "only_b": 2, "neither": 1}


def test_recognisable_counts_one_and_two_over_all_briefs():
    import csv

    ratings = list(csv.DictReader(RATINGS.open()))
    key_map = json.loads(KEY_MAP.read_text())
    briefs = glb_report.load_briefs(BRIEFS)
    ids = [brief["id"] for brief in briefs]

    a_map = {key: info for key, info in key_map.items() if info["model"] == "m_a"}
    b_map = {key: info for key, info in key_map.items() if info["model"] == "m_b"}
    assert glb_report.recognisable(ratings, a_map, ids) == 0.5
    assert round(glb_report.recognisable(ratings, b_map, ids), 3) == round(2 / 6, 3)
    assert glb_report.recognisable([], {}, ids) == 0.0


def test_cli_without_ratings_says_not_rated(tmp_path):
    root = tmp_path / "bench"
    shutil.copytree(FIXTURES, root)

    glb_report.main(["--root", str(root), "--briefs", str(BRIEFS)])

    report = json.loads((root / "report.json").read_text())
    markdown = (root / "report.md").read_text()
    assert report["briefs"] == 6
    assert report["models"]["m_a"]["pass"] == 3
    assert "recognisable" not in report["models"]["m_a"]
    assert "not rated" in markdown
    assert "m_a" in markdown and "m_b" in markdown
    assert "50.0% (18.8%-81.2%)" in markdown
    assert "| Reason | m_a | m_b |" in markdown


def test_cli_with_ratings_sets_recognisable(tmp_path):
    root = tmp_path / "bench"
    shutil.copytree(FIXTURES, root)

    glb_report.main(["--root", str(root), "--briefs", str(BRIEFS), "--ratings", str(RATINGS)])

    report = json.loads((root / "report.json").read_text())
    assert report["models"]["m_a"]["recognisable"] == 0.5
    assert round(report["models"]["m_b"]["recognisable"], 3) == round(2 / 6, 3)
    assert "not rated" not in (root / "report.md").read_text()


def test_report_numbers_match_the_inputs(tmp_path):
    root = tmp_path / "bench"
    shutil.copytree(FIXTURES, root)
    briefs = glb_report.load_briefs(BRIEFS)

    report = glb_report.build_report(root, BRIEFS)

    for name in ("m_a", "m_b"):
        loaded = glb_report.load_model(root / name)
        assert report["models"][name] == glb_report.metrics(loaded["rows"], loaded["raws"], briefs)
    assert report["head_to_head"] == {
        "m_a vs m_b": {"both": 2, "only_a": 1, "only_b": 2, "neither": 1}
    }


# --- US-003: assembly columns, secondary good rate, --extra-runs ---------------------------------


def test_old_fixtures_keep_the_existing_columns_and_append_new_ones(tmp_path):
    root = tmp_path / "bench"
    shutil.copytree(FIXTURES, root)

    glb_report.main(["--root", str(root), "--briefs", str(BRIEFS), "--ratings", str(RATINGS)])

    lines = (root / "report.md").read_text().splitlines()
    header = next(line for line in lines if line.startswith("| Model |"))
    old_header = (
        "| Model | Pass (95% Wilson) | Export | Animated pass | Median triangles | "
        "Max triangles | Share <= 5000 tris | Recognisable | Median tokens | Median seconds | "
        "Total seconds |"
    )
    assert header.startswith(old_header)
    assert header.endswith(
        "| Assembled (of valid) | Assembled (of all briefs) | Median parts | "
        "Good (rated 2), secondary |"
    )

    row = next(line for line in lines if line.startswith("| m_a |"))
    old_row = (
        "| m_a | 50.0% (18.8%-81.2%) | 66.7% | 1/2 (50.0%) | 200 | 300 | 100.0% | 50.0% | "
        "300 | 3 | 15 |"
    )
    assert row.startswith(old_row)
    assert row.endswith("| not computed | not computed | not computed | 33.3% |")


def test_assembly_summary_from_assembly_jsonl():
    loaded = glb_report.load_model(IMP / "m_as")
    assert loaded["assembly"] is not None
    briefs = glb_report.load_briefs(IMP_BRIEFS)

    m = glb_report.metrics(loaded["rows"], loaded["raws"], briefs, loaded["assembly"])

    assert m["assembly"] == {"valid": 3, "assembled": 2, "share": 2 / 3, "median_parts": 3}


def test_assembly_summary_is_none_without_assembly_data():
    loaded = glb_report.load_model(IMP / "m_no_assembly")
    assert loaded["assembly"] is None
    briefs = glb_report.load_briefs(IMP_BRIEFS)

    m = glb_report.metrics(loaded["rows"], loaded["raws"], briefs)

    assert m["assembly"] is None


def test_assembly_summary_falls_back_to_row_stats():
    rows = [{"id": "x", "ok": True, "stats": {"glb": {"ok": True,
            "assembly": {"parts": 7, "assembled": True}}}}]
    assert glb_report.assembly_summary(rows) == {
        "valid": 1, "assembled": 1, "share": 1.0, "median_parts": 7
    }


def test_good_rate_counts_only_ratings_of_two():
    ratings = [
        {"key": "k1", "rating": "2"},
        {"key": "k2", "rating": "1"},
        {"key": "k3", "rating": "0"},
        {"key": "k4", "rating": ""},
    ]
    key_map = {f"k{i}": {"id": f"i{i}", "model": "m"} for i in range(1, 5)}
    assert glb_report.good_rate(ratings, key_map, ["i1", "i2", "i3", "i4"]) == 0.25
    assert glb_report.good_rate(ratings, key_map, []) is None
    assert glb_report.good_rate([], {}, ["i1"]) == 0.0
    # recognisable is unchanged: ratings 2 and 1 both count
    assert glb_report.recognisable(ratings, key_map, ["i1", "i2", "i3", "i4"]) == 0.5


def test_report_has_assembled_and_secondary_good_columns():
    report = glb_report.build_report(IMP, IMP_BRIEFS, IMP_RATINGS, IMP_KEY_MAP)

    assert report["models"]["m_as"]["assembly"] == {
        "valid": 3, "assembled": 2, "share": 2 / 3, "median_parts": 3
    }
    assert report["models"]["m_as"]["good_rate"] == 0.25
    assert report["models"]["m_no_assembly"]["assembly"] is None

    markdown = glb_report.render_markdown(report)
    assert (
        "| Assembled (of valid) | Assembled (of all briefs) | Median parts | "
        "Good (rated 2), secondary |" in markdown
    )
    assert "| 2/3 (66.7%) | 2/4 (50.0%) | 3 | 25.0% |" in markdown
    assert "not computed" in markdown


def test_assembly_of_all_briefs_divides_by_every_brief_not_only_valid():
    """The 4-brief fixture is 3 ok and 2 assembled: 2/3 of valid and 2/4 of all briefs."""
    report = glb_report.build_report(IMP, IMP_BRIEFS)
    assembly = report["models"]["m_as"]["assembly"]

    assert report["briefs"] == 4
    assert report["models"]["m_as"]["pass"] == 3
    assert (assembly["assembled"], assembly["valid"], assembly["share"]) == (2, 3, 2 / 3)
    assert assembly["assembled"] / report["briefs"] == 2 / 4
    assert "| 2/3 (66.7%) | 2/4 (50.0%) |" in glb_report.render_markdown(report)


def test_extra_runs_labels_a_repair_row_and_merges_passes():
    report = glb_report.build_report(
        IMP, IMP_BRIEFS, None, None,
        extra_runs=[("repair", IMP / "repair_case" / "glimmer" / "repair")],
    )
    assert "glimmer after 1 repair" in report["models"]
    assert report["models"]["glimmer after 1 repair"]["pass"] == 3
    assert "glimmer after 1 repair" in glb_report.render_markdown(report)


def test_extra_runs_uses_the_given_name_for_a_normal_run():
    report = glb_report.build_report(
        IMP, IMP_BRIEFS, None, None,
        extra_runs=[("best-of-3", IMP / "m_as")],
    )
    assert "best-of-3" in report["models"]
    assert report["models"]["best-of-3"]["pass"] == 3


def test_merge_validation_rows_keeps_originals_and_adds_repairs():
    base = [{"id": "a", "ok": True}, {"id": "b", "ok": False}]
    repair = [{"id": "b", "ok": True}, {"id": "c", "ok": True}]
    merged = glb_report.merge_validation_rows(base, repair)
    assert {row["id"]: row["ok"] for row in merged} == {"a": True, "b": True, "c": True}


def test_cli_extra_runs_writes_the_row(tmp_path):
    root = tmp_path / "report"
    shutil.copytree(IMP, root)

    glb_report.main([
        "--root", str(root), "--briefs", str(IMP_BRIEFS),
        "--extra-runs", f"repair={root / 'repair_case' / 'glimmer' / 'repair'}",
    ])

    report = json.loads((root / "report.json").read_text())
    assert "glimmer after 1 repair" in report["models"]
    assert "glimmer after 1 repair" in (root / "report.md").read_text()


# --- imp-2 US-003: assembled-of-all-briefs column and the repair-asm --extra-runs row ------------

ASM = IMP / "asm_case" / "glimmer" / "repair-asm"


def test_assembly_repair_extra_run_merges_original_and_repaired_rows_by_id():
    report = glb_report.build_report(
        IMP, IMP_BRIEFS, None, None, extra_runs=[("repair-asm", ASM)]
    )
    merged = report["models"]["glimmer after assembly repair"]

    # original glimmer: 3 ok (c1, c2, c4) and 1 assembled (c1); the repaired c2 becomes assembled
    assert merged["pass"] == 3
    assert merged["assembly"] == {"valid": 3, "assembled": 2, "share": 2 / 3, "median_parts": 3}
    assert merged["assembly"]["assembled"] / report["briefs"] == 2 / 4
    assert "glimmer after assembly repair" in glb_report.render_markdown(report)


def test_assembly_repair_merge_takes_the_repaired_row_and_assembly_for_repaired_ids():
    label, loaded = glb_report.load_extra_run("repair-asm", ASM)
    assert label == "glimmer after assembly repair"

    by_id = {row["id"]: row for row in loaded["rows"]}
    assert set(by_id) == {"c1", "c2", "c3", "c4"}
    assert by_id["c2"]["stats"]["glb"]["triangles"] == 210  # the repaired row, not the original 200
    assert by_id["c4"]["stats"]["glb"]["triangles"] == 310  # the repaired row, not the original 300
    assert by_id["c1"]["stats"]["glb"]["triangles"] == 100  # untouched, keeps the original
    assert by_id["c3"]["reasons"] == ["bad_glb"]

    assembly = {line["id"]: line["assembly"] for line in loaded["assembly"]}
    assert assembly["c2"]["assembled"] is True   # repaired false -> true
    assert assembly["c4"]["assembled"] is False  # repaired but still not assembled
    assert assembly["c1"]["assembled"] is True   # untouched original


def test_merge_by_ids_takes_the_repaired_value_where_the_repair_was_applied():
    base = [{"id": "a", "ok": True}, {"id": "b", "ok": True}]
    repair = [{"id": "b", "ok": False}, {"id": "c", "ok": True}]
    # only the id the repair was applied to (b) takes the repaired value; a is untouched
    assert glb_report.merge_by_ids(base, repair, ["b"]) == [{"id": "a", "ok": True}, {"id": "b", "ok": False}]
    # a repaired id not in the base run is still added
    merged = {row["id"]: row["ok"] for row in glb_report.merge_by_ids(base, repair, ["b", "c"])}
    assert merged == {"a": True, "b": False, "c": True}


def test_repaired_ids_reads_the_summary_and_falls_back_to_the_repair_rows(tmp_path):
    (tmp_path / "summary.json").write_text('{"ids_repaired": ["x", "y"]}')
    assert glb_report.repaired_ids(tmp_path, [{"id": "z"}]) == ["x", "y"]
    empty = tmp_path / "none"
    empty.mkdir()
    assert glb_report.repaired_ids(empty, [{"id": "z"}]) == ["z"]


def test_cli_extra_runs_writes_the_assembly_repair_row(tmp_path):
    root = tmp_path / "report"
    shutil.copytree(IMP, root)

    glb_report.main([
        "--root", str(root), "--briefs", str(IMP_BRIEFS),
        "--extra-runs", f"repair-asm={root / 'asm_case' / 'glimmer' / 'repair-asm'}",
    ])

    report = json.loads((root / "report.json").read_text())
    row = report["models"]["glimmer after assembly repair"]
    assert row["pass"] == 3
    assert row["assembly"]["assembled"] == 2
    assert "glimmer after assembly repair" in (root / "report.md").read_text()


# --- imp-3 US-001: repair-asm row falls back to the validation rows' assembly stats ---------------

ASM_FALLBACK = IMP / "asm_fallback" / "glimmer" / "repair-asm"


def test_assembly_lines_from_rows_null_assembly_for_a_not_ok_row():
    rows = [
        {"id": "a", "ok": True, "stats": {"glb": {"assembly": {"parts": 3, "assembled": True}}}},
        {"id": "b", "ok": False, "stats": {"glb": {"assembly": {"parts": 3, "assembled": True}}}},
    ]
    lines = glb_report.assembly_lines_from_rows(rows)
    assert lines[0] == {"id": "a", "kind": None, "assembly": {"parts": 3, "assembled": True}}
    assert lines[1] == {"id": "b", "kind": None, "assembly": None}


def test_assembly_repair_row_reads_repaired_values_when_assembly_jsonl_is_missing():
    """The imp-ops-2 layout: no `repair-asm/assembly.jsonl`, only the validation rows' stats.

    Base glimmer has 4 ok briefs and 2 assembled; the repair makes one id assembled and one stays
    not, so the merged row's assembled count goes from 2 to 3 of 4.
    """
    base = glb_report.load_model(IMP / "asm_fallback" / "glimmer")
    assert glb_report.assembly_summary(base["rows"], base["assembly"])["assembled"] == 2

    report = glb_report.build_report(
        IMP, IMP_BRIEFS, None, None, extra_runs=[("repair-asm", ASM_FALLBACK)]
    )
    merged = report["models"]["glimmer after assembly repair"]

    assert merged["pass"] == 4
    assert merged["assembly"] == {"valid": 4, "assembled": 3, "share": 3 / 4, "median_parts": 3}
    assert merged["assembly"]["assembled"] / report["briefs"] == 3 / 4
    assert "| 3/4 (75.0%) | 3/4 (75.0%) | 3 |" in glb_report.render_markdown(report)
