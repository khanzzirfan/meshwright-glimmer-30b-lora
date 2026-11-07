import json
import subprocess
import sys
from pathlib import Path

from proof_data import completion_text, load_rows, pick, write_mlx

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "proof_data.py"


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def test_load_rows_reads_the_fixture(fixtures):
    rows = load_rows(fixtures / "proof" / "train.jsonl")
    assert len(rows) == 4
    assert [r["id"] for r in rows] == ["m00001_v0", "m00001_v1", "m00002_v0", "m00003_v0"]
    assert rows[0]["source_id"] == rows[1]["source_id"] == "m00001"
    assert rows[0]["prompt"][0]["role"] == "system"
    assert rows[0]["prompt"][1]["role"] == "user"
    assert rows[0]["completion"][0]["role"] == "assistant"
    lengths = [len(completion_text(r)) for r in rows]
    assert lengths == sorted(lengths) and len(set(lengths)) == 4


def test_pick_median_returns_the_median_completion(fixtures):
    rows = load_rows(fixtures / "proof" / "train.jsonl")
    picked = pick(rows, "median", 1)
    ordered = sorted(rows, key=lambda r: len(completion_text(r)))
    assert picked == [ordered[(len(ordered) - 1) // 2]]
    assert [r["id"] for r in picked] == ["m00001_v1"]


def test_pick_smallest_returns_the_shortest_completion(fixtures):
    rows = load_rows(fixtures / "proof" / "train.jsonl")
    picked = pick(rows, "smallest", 1)
    assert [r["id"] for r in picked] == ["m00001_v0"]
    assert completion_text(picked[0]) == min((completion_text(r) for r in rows), key=len)


def test_pick_spread_uses_one_row_per_source_and_spreads_by_length(fixtures):
    rows = load_rows(fixtures / "proof" / "train.jsonl")
    picked = pick(rows, "spread", 3)
    assert [r["id"] for r in picked] == ["m00001_v0", "m00002_v0", "m00003_v0"]
    assert len({r["source_id"] for r in picked}) == len(picked) == 3
    lengths = [len(completion_text(r)) for r in picked]
    assert lengths == sorted(lengths)

    two = pick(rows, "spread", 2)
    assert [r["id"] for r in two] == ["m00001_v0", "m00003_v0"]
    assert len({r["source_id"] for r in two}) == 2

    assert pick(rows, "spread", 10) == pick(rows, "spread", 3)


def test_write_mlx_three_roles_and_exact_targets(tmp_path, fixtures):
    rows = load_rows(fixtures / "proof" / "train.jsonl")
    picked = pick(rows, "median", 1)
    write_mlx(picked, tmp_path, repeat=2)

    train = read_jsonl(tmp_path / "train.jsonl")
    valid = read_jsonl(tmp_path / "valid.jsonl")
    assert len(train) == 2 and len(valid) == 1
    for line in train + valid:
        assert [m["role"] for m in line["messages"]] == ["system", "user", "assistant"]
        assert line["messages"][-1]["content"] == completion_text(picked[0])

    targets = json.loads((tmp_path / "targets.json").read_text())
    assert targets == [{"id": picked[0]["id"], "caption": picked[0]["prompt"][1]["content"],
                        "mesh": completion_text(picked[0])}]
    assert targets[0]["mesh"] == completion_text(picked[0])


def test_cli_writes_to_a_work_folder(tmp_path, fixtures):
    sft = fixtures / "proof" / "train.jsonl"
    out = tmp_path / "mlx"
    result = subprocess.run([sys.executable, str(SCRIPT), "--sft", str(sft), "--pick", "smallest",
                             "--n", "1", "--repeat", "1", "--out-dir", str(out)],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (out / "train.jsonl").is_file() and (out / "valid.jsonl").is_file()
    assert (out / "targets.json").is_file()


def test_cli_refuses_protected_out_dirs(fixtures):
    sft = fixtures / "proof" / "train.jsonl"
    for folder in ("data", "eval", "out"):
        out = ROOT / folder / "_proof_data_must_not_write"
        assert not out.exists()
        result = subprocess.run([sys.executable, str(SCRIPT), "--sft", str(sft), "--out-dir", str(out)],
                                cwd=ROOT, capture_output=True, text=True)
        assert result.returncode != 0
        assert folder in result.stderr
        assert not out.exists()
