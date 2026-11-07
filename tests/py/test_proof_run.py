import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "proof_run.sh"


def run(*args):
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)


def commands(result):
    return [line[2:] for line in result.stdout.splitlines() if line.startswith("+ ")]


def test_script_calls_the_three_proof_scripts_by_name():
    text = SCRIPT.read_text()
    assert "scripts/proof_data.py" in text
    assert "scripts/proof_score.py" in text
    assert "scripts/proof_ladder.py" in text


def test_dry_run_echoes_five_commands_in_order_and_runs_none(tmp_path):
    workdir = tmp_path / "proof-one"
    result = run("one", "--workdir", str(workdir), "--dry-run")
    assert result.returncode == 0, result.stderr

    lines = commands(result)
    assert len(lines) == 5, lines

    assert lines[0].startswith("mkdir -p ")
    assert "scripts/proof_data.py" in lines[1]
    assert "mlx_lm lora" in lines[2] and "--train" in lines[2]
    assert "scripts/proof_score.py" in lines[3]
    assert "scripts/proof_ladder.py" in lines[4]

    data, train, score, ladder = lines[1], lines[2], lines[3], lines[4]
    assert "--pick median --n 1" in data
    assert "--learning-rate 3e-5" in train
    assert "--batch-size 1" in train
    assert "--temperature 0.0" in score
    assert "--max-tokens 8000" in score
    assert f"--report one={workdir}/report.json" in ladder
    assert not workdir.exists()


def test_dry_run_uses_a_new_tmp_workdir_by_default():
    result = run("one", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "/tmp/proof-one-" in result.stdout


def test_one_defaults_to_the_median_row_and_ten_minutes(tmp_path):
    result = run("one", "--workdir", str(tmp_path), "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "--pick median --n 1" in result.stdout
    assert "roughly 10 minutes" in result.stdout
    assert "--iters 200" in result.stdout


def test_seen_uses_the_spread_pick_and_an_unmeasured_estimate(tmp_path):
    result = run("seen", "--workdir", str(tmp_path), "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "--pick spread --n 15" in result.stdout
    assert "--iters 600" in result.stdout
    assert "not measured" in result.stdout
    assert f"--report seen={tmp_path}/report.json" in result.stdout


def test_lr_2e4_is_refused_with_the_divergence_explanation(tmp_path):
    result = run("one", "--workdir", str(tmp_path), "--lr", "2e-4", "--dry-run")
    assert result.returncode != 0
    assert "2e-4 diverged" in result.stderr
    assert "loss 0.78 to 11" in result.stderr
    assert "3 Nov 2026" in result.stderr


def test_force_lr_lets_lr_2e4_through(tmp_path):
    result = run("one", "--workdir", str(tmp_path), "--lr", "2e-4", "--force-lr", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "--learning-rate 2e-4" in result.stdout


def test_unknown_rung_exits_non_zero(tmp_path):
    for rung in ("two",):
        result = run(rung, "--workdir", str(tmp_path), "--dry-run")
        assert result.returncode != 0
        assert "unknown argument" in result.stderr


def test_missing_rung_exits_non_zero():
    result = run("--dry-run")
    assert result.returncode != 0
    assert "a rung is required" in result.stderr


def test_bash_syntax_check():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
