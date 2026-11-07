"""Judge each rung of the mesh proof ladder and recommend the next spending step.

Every rung is scored independently from the report that ``proof_score.py`` writes.
``judge`` turns one report into pass or fail with the measured numbers in the reason;
``decide`` takes the reports found so far and gives the owner one plain sentence.
A rung with no report is never treated as passed: the CLI prints NOT RUN and
``decide`` asks for that rung instead of recommending more spending.

The last two rung thresholds are placeholders to revise once those runs exist.

usage: python scripts/proof_ladder.py --report one=/tmp/proof-one/report.json \
    --report seen=/tmp/proof-seen/report.json
"""
import argparse
import json
from pathlib import Path

THRESHOLDS = {
    "one": {"exact": 1.0, "stopped": 1.0},
    "seen": {"valid": 0.8, "stopped": 0.8},
    "unseen_same_category": {"valid": 0.6},
    "unseen_new_category": {"valid": 0.4},
}
RUNG_ORDER = ("one", "seen", "unseen_same_category", "unseen_new_category")


def _metric(report, name):
    """Measured count and share for one report metric."""
    n = int(report.get("n", 0) or 0)
    count = int(report.get(name, 0) or 0)
    share = (count / n) if n > 0 else 0.0
    return count, n, share


def judge(rung, report):
    """Return (passed, reason) for one rung and its proof_score report.

    A missing or empty report fails with reason "not run"; no rung is ever passed
    on numbers that were not measured.
    """
    if rung not in THRESHOLDS:
        raise ValueError(f"unknown rung {rung!r}; choose one of {', '.join(RUNG_ORDER)}")
    if not report:
        return False, "not run"
    n = int(report.get("n", 0) or 0)
    if n <= 0:
        return False, "not run: report has no scored targets"

    failed = []
    passed = []
    for name, minimum in THRESHOLDS[rung].items():
        count, total, share = _metric(report, name)
        text = f"{name} {count}/{total} ({share:.2f})"
        if share < minimum:
            failed.append(f"{text} < {minimum:.2f}")
        else:
            passed.append(f"{text} >= {minimum:.2f}")

    if failed:
        return False, "failed: " + ", ".join(failed)
    return True, "passed: " + ", ".join(passed)


def decide(reports):
    """Return one plain recommendation from the reports found so far.

    ``reports`` maps a rung name to its proof_score report. Missing rungs are
    named as not run; a missing rung is never described as passed.
    """
    reports = reports or {}
    one = reports.get("one")
    if not one:
        return "Rung one has not run: run the one rung before deciding any spending."
    one_passed, _reason = judge("one", one)
    if not one_passed:
        return ("Rung one failed: the format or hyperparameters are wrong. Fix the learning "
                "rate first (2e-4 diverged from loss 0.78 to 11), then the prompt format and "
                "max sequence length.")

    seen = reports.get("seen")
    if not seen:
        return "Rung one passed. Run the seen rung next before deciding on more spending."
    seen_passed, _reason = judge("seen", seen)
    if not seen_passed:
        return "Rung seen failed: stop Glimmer GPU spending and fix the small-model setup first."
    return "Rung seen passed: growing the data is the next step."


def _report_arg(value):
    """Parse one --report rung=path.json argument."""
    if "=" not in value:
        raise argparse.ArgumentTypeError("use RUNG=PATH, for example one=/tmp/proof/report.json")
    rung, path = value.split("=", 1)
    if rung not in THRESHOLDS:
        raise argparse.ArgumentTypeError(
            f"unknown rung {rung!r}; choose one of {', '.join(RUNG_ORDER)}")
    if not path:
        raise argparse.ArgumentTypeError("report path is empty")
    return rung, path


def main():
    ap = argparse.ArgumentParser(description="Judge the mesh proof ladder and print the verdict.")
    ap.add_argument("--report", action="append", type=_report_arg, default=[],
                    metavar="RUNG=PATH", help="report JSON for one rung; repeat per rung")
    a = ap.parse_args()

    reports = {rung: json.loads(Path(path).read_text()) for rung, path in a.report}

    for rung in RUNG_ORDER:
        if not reports.get(rung):
            print(f"{rung}: NOT RUN - no report")
            continue
        passed, reason = judge(rung, reports[rung])
        print(f"{rung}: {'PASS' if passed else 'FAIL'} - {reason}")

    print(f"recommendation: {decide(reports)}")


if __name__ == "__main__":
    main()
