import json
from pathlib import Path

import glb_phase2_estimate


def row(row_id, chars):
    return {
        "id": row_id,
        "domain": "props_and_tools",
        "title": f"Widget {row_id}",
        "prompt": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        "completion": [{"role": "assistant", "content": "x" * chars}],
    }


def write_split(path, count, chars):
    path.write_text("".join(json.dumps(row(f"r{i}", chars)) + "\n" for i in range(count)))


def dataset(tmp_path):
    """5 train rows and 2 val rows, every completion 33 characters (231 chars total, 70 tokens at 3.3)."""
    data = tmp_path / "phase2"
    data.mkdir()
    write_split(data / "train.jsonl", 5, 33)
    write_split(data / "val.jsonl", 2, 33)
    return data


def test_estimate_arithmetic_on_a_tiny_dir(tmp_path):
    data = dataset(tmp_path)
    info = glb_phase2_estimate.estimate(str(data), epochs=2, grad_accum=2, batch=1, sec_per_step=600, price_per_hour=4.0)

    assert info["train_rows"] == 5 and info["val_rows"] == 2
    assert info["chars"] == 231
    assert info["tokens"] == 70
    assert info["steps_per_epoch"] == 3   # ceil(5 / (1 x 2))
    assert info["total_steps"] == 6       # 3 x 2 epochs
    assert info["hours"] == 1.0           # 6 x 600 / 3600
    assert info["cost"] == 4.0            # 1.0 x 4.0


def test_main_prints_steps_hours_and_cost(tmp_path, capsys):
    data = dataset(tmp_path)
    glb_phase2_estimate.main(["--data", str(data), "--batch", "1", "--grad-accum", "2",
                              "--epochs", "2", "--sec-per-step", "600", "--price-per-hour", "4.0"])
    out = capsys.readouterr().out
    assert "rows: 5 train, 2 val" in out
    assert "completion chars: 231" in out
    assert "estimated tokens: 70 (estimate, chars/token = 3.3)" in out
    assert "steps per epoch: 3" in out
    assert "total steps: 6" in out
    assert "hours: 1.00" in out
    assert "cost: $4.00" in out


def test_without_sec_per_step_it_says_not_measured(tmp_path, capsys):
    data = dataset(tmp_path)
    glb_phase2_estimate.main(["--data", str(data)])
    out = capsys.readouterr().out
    assert glb_phase2_estimate.NOT_MEASURED in out
    assert "cost:" not in out
    assert "hours:" not in out


def test_sec_per_step_without_price_is_refused(tmp_path):
    data = dataset(tmp_path)
    try:
        glb_phase2_estimate.main(["--data", str(data), "--sec-per-step", "600"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("expected SystemExit")


def test_chars_per_token_changes_the_token_estimate(tmp_path):
    data = dataset(tmp_path)
    info = glb_phase2_estimate.estimate(str(data), chars_per_token=3.0)
    assert info["tokens"] == 77  # 231 / 3.0


def test_helpers_count_chars_and_steps():
    rows = [row("a", 4), row("b", 6)]
    assert glb_phase2_estimate.completion_chars(rows) == 10
    assert glb_phase2_estimate.steps_per_epoch(9, 1, 8) == 2
    assert glb_phase2_estimate.steps_per_epoch(0, 1, 8) == 0
