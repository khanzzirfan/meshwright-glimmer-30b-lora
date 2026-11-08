"""Tests for scripts/glb_distill_briefs.py (docs/14, imp-5 US-005/US-006).

A tiny fixture pins the leak (phrase and title), duplicate and id rules and the row field set. Two tests
read the real files: bench/distill/subjects.json (all 12 domains, 45 entries each, 27/11/7) and the built
bench/distill/briefs.jsonl (>= 480 rows, contiguous x ids, no eval id, title or subject phrase).
"""
import collections
import json
from pathlib import Path

import pytest

import glb_distill_briefs

ROOT = Path(__file__).resolve().parents[2]
SUBJECTS = ROOT / "bench" / "distill" / "subjects.json"
BRIEFS = ROOT / "bench" / "distill" / "briefs.jsonl"
EVAL_BRIEFS = ROOT / "bench" / "glb" / "briefs.jsonl"
LEAK_FILE = ROOT / "bench" / "glb" / "eval_subjects.json"
DOMAINS = ["buildings", "characters", "creatures", "fantasy_medieval", "food", "furniture",
           "modular_kits", "nature", "props_and_tools", "sci_fi", "vehicles", "weapons_and_armour"]
KINDS = {"static": 27, "animated": 11, "set": 7}


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def eval_field_set():
    return set(read_rows(EVAL_BRIEFS)[0])


@pytest.fixture
def fixture_files(tmp_path):
    eval_briefs = tmp_path / "eval_briefs.jsonl"
    eval_rows = [
        {"id": "g001", "title": "Wooden crate", "brief": "A crate.", "domain": "props_and_tools",
         "level": 1, "style": "low-poly", "kind": "static"},
        {"id": "g900", "title": "Floating Nimbus", "brief": "A drifting cloud.", "domain": "buildings",
         "level": 2, "style": "low-poly", "kind": "set"},
    ]
    eval_briefs.write_text("".join(json.dumps(row) + "\n" for row in eval_rows))

    leak = tmp_path / "eval_subjects.json"
    leak.write_text(json.dumps({"_comment": "fixture", "g001": ["crate"]}))

    subjects = tmp_path / "subjects.json"
    subjects.write_text(json.dumps({
        "buildings": [
            {"title": "Timber cabin", "brief": "A timber cabin with a steep roof.", "kind": "static"},
            {"title": "Crate tower", "brief": "A tower of stacked boxes.", "kind": "static"},
            {"title": "Stone bridge", "brief": "A long stone bridge beside a wooden crate.", "kind": "static"},
            {"title": "Floating Nimbus", "brief": "A drifting cloud shape.", "kind": "set"},
        ],
        "furniture": [
            {"title": "Oak table", "brief": "A sturdy oak table with four turned legs and a long plank top.", "kind": "static"},
            {"title": "timber CABIN", "brief": "A second cabin.", "kind": "animated"},
            {"title": "Dining table", "brief": "A long dining table with six matching seats tucked around it and a runner down the middle.", "kind": "static"},
            {"title": "Long couch", "brief": "A long upholstered couch with rolled arms, a tall backrest, loose cushions along the seat, a small round side table beside it and a woven rug spread out underneath.", "kind": "animated"},
        ],
    }))
    return subjects, eval_briefs, leak


def run_main(out, subjects, eval_briefs, leak):
    glb_distill_briefs.main(["--subjects", str(subjects), "--eval-briefs", str(eval_briefs),
                             "--leak-file", str(leak), "--out", str(out)])


def test_fixture_drops_leaks_and_duplicates_and_assigns_ids_in_domain_order(tmp_path, fixture_files, capsys):
    subjects, eval_briefs, leak = fixture_files
    out = tmp_path / "briefs.jsonl"
    run_main(out, subjects, eval_briefs, leak)

    rows = read_rows(out)
    assert [row["id"] for row in rows] == ["x0001", "x0002", "x0003", "x0004"]
    assert [row["title"] for row in rows] == ["Timber cabin", "Oak table", "Dining table", "Long couch"]
    assert [row["domain"] for row in rows] == ["buildings", "furniture", "furniture", "furniture"]

    printed = capsys.readouterr().out
    assert "kept 4" in printed
    assert "leak_phrase 2" in printed  # 'Crate tower' by title, 'Stone bridge' by brief
    assert "leak_title 1" in printed   # 'Floating Nimbus' equals the g900 eval title
    assert "duplicate 1" in printed    # 'timber CABIN' repeats 'Timber cabin'


def test_fixture_rows_use_the_eval_field_set_and_levels_by_length(tmp_path, fixture_files):
    subjects, eval_briefs, leak = fixture_files
    out = tmp_path / "briefs.jsonl"
    run_main(out, subjects, eval_briefs, leak)

    rows = read_rows(out)
    for row in rows:
        assert set(row) == eval_field_set()
        assert row["style"] == "low-poly"
        assert row["level"] == glb_distill_briefs.level_for(row["brief"])
    assert [row["level"] for row in rows] == [1, 1, 2, 3]
    assert [row["kind"] for row in rows] == ["static", "static", "static", "animated"]


def test_level_for_bounds():
    assert glb_distill_briefs.level_for("x" * 70) == 1
    assert glb_distill_briefs.level_for("x" * 71) == 2
    assert glb_distill_briefs.level_for("x" * 120) == 2
    assert glb_distill_briefs.level_for("x" * 121) == 3


def test_check_subjects_rejects_a_bad_entry():
    with pytest.raises(ValueError):
        glb_distill_briefs.check_subjects({"buildings": [{"title": "A", "brief": "B"}]})


@pytest.mark.parametrize("sub", ["data/distill", "out/distill", "eval/distill", "data", "out", "eval"])
def test_out_inside_protected_roots_is_refused(tmp_path, fixture_files, sub):
    subjects, eval_briefs, leak = fixture_files
    with pytest.raises(SystemExit) as exc:
        glb_distill_briefs.main(["--subjects", str(subjects), "--eval-briefs", str(eval_briefs),
                                 "--leak-file", str(leak), "--out", str(ROOT / sub / "briefs.jsonl")])
    assert exc.value.code != 0


def test_real_subjects_has_twelve_domains_of_45_with_the_kind_split():
    subjects = json.loads(SUBJECTS.read_text())
    assert list(subjects) == DOMAINS
    for domain in DOMAINS:
        entries = subjects[domain]
        assert len(entries) == 45, domain
        assert collections.Counter(entry["kind"] for entry in entries) == KINDS
        for entry in entries:
            assert set(entry) == {"title", "brief", "kind"}
            assert entry["title"].strip() and entry["brief"].strip()


def test_real_briefs_file_has_480_rows_and_no_eval_leak():
    rows = read_rows(BRIEFS)
    assert len(rows) >= 480

    eval_rows = read_rows(EVAL_BRIEFS)
    eval_ids = {row["id"] for row in eval_rows}
    eval_titles = {row["title"].strip().casefold() for row in eval_rows}
    phrases = glb_distill_briefs.load_leak_phrases(LEAK_FILE)

    assert {row["id"] for row in rows} == {f"x{i:04d}" for i in range(1, len(rows) + 1)}
    assert {row["domain"] for row in rows} == set(DOMAINS)
    for row in rows:
        assert set(row) == eval_field_set()
        assert row["id"] not in eval_ids
        assert row["title"].strip().casefold() not in eval_titles
        assert not glb_distill_briefs.title_is_eval_subject(row["title"], phrases)
        assert not glb_distill_briefs.title_is_eval_subject(row["brief"], phrases)


def test_real_subjects_run_writes_eval_format_rows_with_unique_x_ids(tmp_path):
    out = tmp_path / "briefs.jsonl"
    glb_distill_briefs.main(["--subjects", str(SUBJECTS), "--eval-briefs", str(EVAL_BRIEFS),
                             "--leak-file", str(LEAK_FILE), "--out", str(out)])

    rows = read_rows(out)
    assert rows, "the real subjects file produced no rows"
    assert len({row["id"] for row in rows}) == len(rows)
    assert all(row["id"].startswith("x") for row in rows)
    assert all(set(row) == eval_field_set() for row in rows)
    assert all(row["style"] == "low-poly" for row in rows)
    assert all(1 <= row["level"] <= 3 for row in rows)
