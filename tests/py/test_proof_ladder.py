import json
import subprocess
import sys
from pathlib import Path

from proof_ladder import RUNG_ORDER, decide, judge

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "proof_ladder.py"


def report(n, exact=0, valid=0, stopped=0):
    return {"n": n, "exact": exact, "valid": valid, "stopped": stopped}


def test_judge_one_passes_only_at_a_full_exact_and_stopped_share():
    passed, reason = judge("one", report(20, exact=20, valid=20, stopped=20))
    assert passed is True
    assert "exact 20/20 (1.00) >= 1.00" in reason
    assert "stopped 20/20 (1.00) >= 1.00" in reason

    passed, reason = judge("one", report(20, exact=19, valid=20, stopped=20))
    assert passed is False
    assert "exact 19/20 (0.95) < 1.00" in reason

    passed, reason = judge("one", report(20, exact=20, valid=20, stopped=19))
    assert passed is False
    assert "stopped 19/20 (0.95) < 1.00" in reason


def test_judge_seen_valid_boundary():
    assert judge("seen", report(20, exact=0, valid=15, stopped=20))[0] is False
    assert judge("seen", report(20, exact=0, valid=16, stopped=20))[0] is True
    assert judge("seen", report(20, exact=0, valid=17, stopped=20))[0] is True


def test_judge_seen_stopped_boundary():
    assert judge("seen", report(20, exact=0, valid=20, stopped=15))[0] is False
    assert judge("seen", report(20, exact=0, valid=20, stopped=16))[0] is True
    assert judge("seen", report(20, exact=0, valid=20, stopped=17))[0] is True


def test_judge_unseen_same_category_valid_boundary():
    assert judge("unseen_same_category", report(20, valid=11))[0] is False
    assert judge("unseen_same_category", report(20, valid=12))[0] is True
    assert judge("unseen_same_category", report(20, valid=13))[0] is True


def test_judge_unseen_new_category_valid_boundary():
    assert judge("unseen_new_category", report(20, valid=7))[0] is False
    assert judge("unseen_new_category", report(20, valid=8))[0] is True
    assert judge("unseen_new_category", report(20, valid=9))[0] is True


def test_judge_missing_report_is_not_run_and_never_passes():
    for value in (None, {}, report(0)):
        passed, reason = judge("one", value)
        assert passed is False
        assert "not run" in reason


def test_judge_rejects_an_unknown_rung():
    try:
        judge("two", report(1, exact=1, stopped=1))
    except ValueError as error:
        assert "unknown rung" in str(error)
    else:
        raise AssertionError("judge accepted an unknown rung")


def test_decide_does_not_pass_a_rung_with_no_report():
    text = decide({})
    assert "not run" in text.lower()
    assert "passed" not in text.lower()

    passing_seen = report(20, valid=20, stopped=20)
    text = decide({"seen": passing_seen})
    assert "Rung one has not run" in text
    assert "seen passed" not in text.lower()


def test_decide_failed_one_names_the_learning_rate_and_format():
    text = decide({"one": report(1, exact=0, stopped=1)})
    assert "Rung one failed" in text
    assert "format" in text.lower()
    assert "learning rate" in text.lower()
    assert "seen passed" not in text.lower()


def test_decide_passed_one_asks_for_the_seen_rung():
    text = decide({"one": report(1, exact=1, valid=1, stopped=1)})
    assert "Rung one passed" in text
    assert "Run the seen rung" in text
    assert "seen passed" not in text.lower()


def test_decide_treats_an_empty_seen_report_as_missing():
    text = decide({"one": report(1, exact=1, valid=1, stopped=1), "seen": {}})
    assert "Run the seen rung" in text
    assert "seen passed" not in text.lower()


def test_decide_failed_seen_stops_glimmer_spending():
    text = decide({"one": report(1, exact=1, valid=1, stopped=1),
                   "seen": report(20, valid=10, stopped=20)})
    assert "stop Glimmer GPU spending" in text
    assert "small-model setup" in text


def test_decide_passed_seen_says_grow_the_data():
    text = decide({"one": report(1, exact=1, valid=1, stopped=1),
                   "seen": report(20, valid=20, stopped=20)})
    assert "growing the data is the next step" in text


def write_report(path, **values):
    path.write_text(json.dumps(report(**values)))
    return f"{path.name}"


def run_cli(*specs):
    args = [sys.executable, str(SCRIPT)]
    for spec in specs:
        args.extend(["--report", spec])
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True)


def test_cli_prints_pass_and_exits_zero(tmp_path):
    path = tmp_path / "one.json"
    write_report(path, n=1, exact=1, valid=1, stopped=1)
    result = run_cli(f"one={path}")
    assert result.returncode == 0, result.stderr
    assert "one: PASS" in result.stdout
    assert "recommendation:" in result.stdout


def test_cli_prints_fail_and_exits_zero(tmp_path):
    path = tmp_path / "one.json"
    write_report(path, n=1, exact=0, valid=0, stopped=1)
    result = run_cli(f"one={path}")
    assert result.returncode == 0, result.stderr
    assert "one: FAIL" in result.stdout
    assert "recommendation:" in result.stdout


def test_cli_prints_not_run_for_missing_reports_and_exits_zero(tmp_path):
    result = run_cli()
    assert result.returncode == 0, result.stderr
    for rung in RUNG_ORDER:
        assert f"{rung}: NOT RUN" in result.stdout
    assert "recommendation:" in result.stdout


def test_cli_prints_one_line_per_rung_with_seen_also_supplied(tmp_path):
    one = tmp_path / "one.json"
    seen = tmp_path / "seen.json"
    write_report(one, n=1, exact=1, valid=1, stopped=1)
    write_report(seen, n=20, valid=20, stopped=20)
    result = run_cli(f"one={one}", f"seen={seen}")
    assert result.returncode == 0, result.stderr
    assert "one: PASS" in result.stdout
    assert "seen: PASS" in result.stdout
    assert "unseen_same_category: NOT RUN" in result.stdout
    assert "unseen_new_category: NOT RUN" in result.stdout
    assert "growing the data is the next step" in result.stdout
