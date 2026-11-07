"""Tests for scripts/build_dataset.py: the join, the reasoning wrap and the split."""
import json
import subprocess
import sys
from pathlib import Path

import build_dataset
from tags import THINK_CLOSE, THINK_OPEN


def _run(fixtures, tmp_path, **kw):
    return build_dataset.build(
        str(fixtures / "briefs.jsonl"),
        str(fixtures / "raw"),
        str(fixtures / "validation.jsonl"),
        str(tmp_path / "sft"),
        **kw,
    )


def test_only_ok_rows_are_kept(fixtures, tmp_path):
    counts = _run(fixtures, tmp_path)
    assert counts["kept"] == 4
    assert counts["total"] == 6
    train = (tmp_path / "sft" / "train.jsonl").read_text().splitlines()
    val = (tmp_path / "sft" / "val.jsonl").read_text().splitlines()
    kept_ids = {json.loads(l)["id"] for l in train + val}
    assert kept_ids == {"b000", "b001", "b002", "b004"}
    assert "b003" not in kept_ids and "b005" not in kept_ids


def test_reasoning_is_wrapped_unless_disabled(fixtures, tmp_path):
    counts = _run(fixtures, tmp_path)
    rows = {json.loads(l)["id"]: json.loads(l) for l in (tmp_path / "sft" / "train.jsonl").read_text().splitlines()}
    val_rows = {json.loads(l)["id"]: json.loads(l) for l in (tmp_path / "sft" / "val.jsonl").read_text().splitlines()}
    by_id = {**rows, **val_rows}
    b000 = by_id["b000"]["completion"][0]["content"]
    assert b000.startswith(THINK_OPEN + "\n")
    assert "\n" + THINK_CLOSE + "\n\n" in b000
    assert "spinning cube" in b000
    plain = by_id["b002"]["completion"][0]["content"]
    assert THINK_OPEN not in plain

    off = _run(fixtures, tmp_path / "off", no_reasoning=True)
    assert off["kept"] == counts["kept"]
    off_rows = [json.loads(l) for l in (tmp_path / "off" / "sft" / "train.jsonl").read_text().splitlines()]
    off_rows += [json.loads(l) for l in (tmp_path / "off" / "sft" / "val.jsonl").read_text().splitlines()]
    assert all(THINK_OPEN not in r["completion"][0]["content"] for r in off_rows)


def test_split_is_stratified_and_deterministic(fixtures, tmp_path):
    first = _run(fixtures, tmp_path / "a")
    assert first["by_level"] == {1: 2, 2: 1, 3: 1}
    assert first["train"] == 3 and first["val"] == 1
    assert first["train_ids"] == ["b000", "b002", "b004"]
    assert first["val_ids"] == ["b001"]

    again = _run(fixtures, tmp_path / "b")
    assert again["train_ids"] == first["train_ids"]
    assert again["val_ids"] == first["val_ids"]

    other = build_dataset.build(
        str(fixtures / "briefs.jsonl"),
        str(fixtures / "raw"),
        str(fixtures / "validation.jsonl"),
        str(tmp_path / "c"),
        seed=99,
    )
    assert sorted(other["train_ids"] + other["val_ids"]) == sorted(first["train_ids"] + first["val_ids"])


def test_prompt_and_completion_roles(fixtures, tmp_path):
    _run(fixtures, tmp_path)
    rows = [json.loads(l) for l in (tmp_path / "sft" / "train.jsonl").read_text().splitlines()]
    rows += [json.loads(l) for l in (tmp_path / "sft" / "val.jsonl").read_text().splitlines()]
    assert rows
    for r in rows:
        roles = [m["role"] for m in r["prompt"]]
        assert roles == ["system", "user"]
        assert r["prompt"][0]["content"] == build_dataset.system_prompt()
        assert [m["role"] for m in r["completion"]] == ["assistant"]
        assert r["prompt"][1]["content"]
        assert r["completion"][0]["content"]
        assert r["level"] in (1, 2, 3)
        assert r["domain"] in ("abstract", "nature")


def test_main_reports_unchanged_fixture_counts(fixtures, tmp_path, monkeypatch, capsys):
    out = tmp_path / "cli"
    monkeypatch.setattr(sys, "argv", [
        "build_dataset.py",
        "--briefs", str(fixtures / "briefs.jsonl"),
        "--raw", str(fixtures / "raw"),
        "--report", str(fixtures / "validation.jsonl"),
        "--out", str(out),
    ])
    build_dataset.main()
    assert "kept 4 of 6 briefs; train 3, val 1" in capsys.readouterr().out
    train_ids = [json.loads(l)["id"] for l in (out / "train.jsonl").read_text().splitlines()]
    val_ids = [json.loads(l)["id"] for l in (out / "val.jsonl").read_text().splitlines()]
    assert train_ids == ["b000", "b002", "b004"]
    assert val_ids == ["b001"]


def test_import_has_no_heavy_side_effects():
    root = Path(__file__).resolve().parent.parent.parent
    code = (
        "import sys; sys.path.insert(0, 'scripts'); import build_dataset; "
        "assert 'openai' not in sys.modules and 'dotenv' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
