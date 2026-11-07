import json
import shutil
from pathlib import Path

import glb_report

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "glb_bench"
BRIEFS = FIXTURES / "briefs.jsonl"
RATINGS = FIXTURES / "rating.csv"
KEY_MAP = FIXTURES / "key_map.json"


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
