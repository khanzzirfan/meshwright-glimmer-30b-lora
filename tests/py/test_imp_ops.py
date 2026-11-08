import hashlib
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "imp_ops.sh"

FAKE_BENCH = """#!/usr/bin/env bash
# stands in for glb_bench.py: parses --out-root/--only/--run-suffix, waits a bit, writes two raw answers
while [ $# -gt 0 ]; do case "$1" in
  --out-root) out="$2"; shift 2 ;;
  --only) only="$2"; shift 2 ;;
  --run-suffix) suffix="$2"; shift 2 ;;
  --run-suffix=*) suffix="${1#--run-suffix=}"; shift ;;
  *) shift ;;
esac; done
sleep "${FAKE_SLEEP:-1}"
mkdir -p "$out/$only${suffix:-}/raw"
echo '{}' > "$out/$only${suffix:-}/raw/g001.json"
echo '{}' > "$out/$only${suffix:-}/raw/g002.json"
"""


@pytest.fixture
def env(tmp_path):
    bench = tmp_path / "fake_bench.sh"
    bench.write_text(FAKE_BENCH)
    bench.chmod(0o755)
    prompt = tmp_path / "system_glb_v3.txt"
    prompt.write_text("version three")
    runs = tmp_path / "runs" / "glb_v3"
    jobs = tmp_path / "runs" / "imp" / "jobs"
    runs.mkdir(parents=True)
    e = dict(os.environ,
             IMP_OPS_RUNS=str(runs), IMP_OPS_JOBS=str(jobs), IMP_OPS_BENCH=str(bench),
             IMP_OPS_PROMPT=str(prompt), IMP_OPS_POLL="1", IMP_OPS_SKIP_CHECKS="1", FAKE_SLEEP="3")
    e["_prompt"] = str(prompt)
    e["_runs"] = str(runs)
    e["_jobs"] = str(jobs)
    return e


def ops(env, *args):
    return subprocess.run(["bash", str(OPS), *args], env=env, capture_output=True, text=True, timeout=60)


def prompt_sha(env):
    return hashlib.sha256(Path(env["_prompt"]).read_bytes()).hexdigest()


def write_frozen(env, sha):
    (Path(env["_runs"]) / "PROMPT_FROZEN.json").write_text('{"prompt": "x", "sha256": "%s"}' % sha)


def test_start_wait_status_flow(env):
    write_frozen(env, prompt_sha(env))
    started = ops(env, "start", "v3s2")
    assert started.returncode == 0 and "started v3s2" in started.stdout

    status = ops(env, "status")
    assert status.returncode == 0 and "v3s2: running" in status.stdout

    soon = ops(env, "wait", "v3s2", "1")
    assert soon.returncode == 2 and "still running" in soon.stdout

    done = ops(env, "wait", "v3s2", "30")
    assert done.returncode == 0 and "finished with exit 0" in done.stdout and "raw 2/48" in done.stdout

    again = ops(env, "start", "v3s2")
    assert again.returncode == 0 and "already finished" in again.stdout


def test_start_refuses_the_frozen_prompt_when_the_hash_does_not_match(env):
    write_frozen(env, "0" * 64)
    r = ops(env, "start", "v3s2")
    assert r.returncode == 1 and "REFUSED" in r.stdout
    assert not (Path(env["_jobs"]) / "v3s2.pid").exists()


def test_start_refuses_the_assembly_jobs_when_the_hash_does_not_match(env):
    write_frozen(env, "0" * 64)
    for job in ("repair-asm-v3", "repair-asm-v3s3"):
        r = ops(env, "start", job)
        assert r.returncode == 1 and "REFUSED" in r.stdout
        assert not (Path(env["_jobs"]) / f"{job}.pid").exists()


def test_start_refuses_when_there_is_no_frozen_file(env):
    r = ops(env, "start", "v3s2")
    assert r.returncode == 1 and "REFUSED" in r.stdout


def test_only_one_job_at_a_time(env):
    write_frozen(env, prompt_sha(env))
    assert ops(env, "start", "v3s2").returncode == 0
    r = ops(env, "start", "v3s3")
    assert r.returncode == 1 and "one job at a time" in r.stdout
    ops(env, "wait", "v3s2", "30")


def test_unknown_job_name_is_refused(env):
    r = ops(env, "start", "not-a-job")
    assert r.returncode == 1 and "unknown job" in r.stdout


def test_preflight_reports_ollama_running_job_hash_and_imp1(env):
    write_frozen(env, prompt_sha(env))
    r = ops(env, "preflight")
    assert r.returncode == 0
    assert "Ollama up/down: not checked" in r.stdout
    assert "no job running" in r.stdout
    assert "v3 prompt hash: matches" in r.stdout
    assert "imp-1" in r.stdout


def test_wait_on_a_job_that_never_started_fails(env):
    r = ops(env, "wait", "v3s2", "1")
    assert r.returncode == 1 and "never started" in r.stdout


def test_dry_run_prints_the_real_job_commands(tmp_path):
    env = dict(os.environ, IMP_OPS_DRY="1", IMP_OPS_JOBS=str(tmp_path / "jobs"))
    expected = {
        "v3s2": ".venv/bin/python scripts/glb_bench.py --out-root runs/glb_v3 --only glimmer-v3 --seed 2 --run-suffix=-s2",
        "v3s3": ".venv/bin/python scripts/glb_bench.py --out-root runs/glb_v3 --only glimmer-v3 --seed 3 --run-suffix=-s3",
        "ad4": ".venv/bin/python scripts/glb_bench.py --out-root runs/glb_v3 --only glimmer-v3 --seed 4 --run-suffix=-s4",
        "ad5": ".venv/bin/python scripts/glb_bench.py --out-root runs/glb_v3 --only glimmer-v3 --seed 5 --run-suffix=-s5 --ids-file=runs/imp/adaptive/ids_after_s4.txt",
        "ad6": ".venv/bin/python scripts/glb_bench.py --out-root runs/glb_v3 --only glimmer-v3 --seed 6 --run-suffix=-s6 --ids-file=runs/imp/adaptive/ids_after_s5.txt",
        "repair-v3": ".venv/bin/python scripts/glb_repair.py --run runs/glb_v3/glimmer-v3 --model-row glimmer-v3",
        "repair-asm-v3": ".venv/bin/python scripts/glb_repair.py --run runs/glb_v3/glimmer-v3 --model-row glimmer-v3 --mode assembly",
        "repair-asm-v3s3": ".venv/bin/python scripts/glb_repair.py --run runs/glb_v3/glimmer-v3-s3 --model-row glimmer-v3 --mode assembly",
        "distill-smoke": ".venv/bin/python scripts/glb_generate.py --briefs bench/glb/dev_briefs.jsonl --limit 2 --out-dir runs/imp/distill_smoke",
        "distill": ".venv/bin/python scripts/glb_generate.py --briefs bench/distill/briefs.jsonl --out-dir runs/imp/distill",
    }
    for job, command in expected.items():
        r = ops(env, "start", job)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == command
    assert not (tmp_path / "jobs").exists()


def test_dry_run_prints_the_adaptive_jobs_with_their_ids_file(tmp_path):
    # ad4 samples all briefs; ad5/ad6 add the fixed --ids-file the operator pre-computes (imp-ops-3).
    env = dict(os.environ, IMP_OPS_DRY="1", IMP_OPS_JOBS=str(tmp_path / "jobs"))
    ad4 = ops(env, "start", "ad4")
    assert ad4.returncode == 0 and "--ids-file" not in ad4.stdout and "--seed 4" in ad4.stdout
    ad5 = ops(env, "start", "ad5")
    assert ad5.returncode == 0 and "--ids-file=runs/imp/adaptive/ids_after_s4.txt" in ad5.stdout
    ad6 = ops(env, "start", "ad6")
    assert ad6.returncode == 0 and "--ids-file=runs/imp/adaptive/ids_after_s5.txt" in ad6.stdout


def test_start_refuses_an_adaptive_job_when_its_ids_file_is_missing(env, tmp_path):
    write_frozen(env, prompt_sha(env))
    env["IMP_OPS_ADAPTIVE"] = str(tmp_path / "adaptive")  # nothing has been listed yet
    for job, name in (("ad5", "ids_after_s4.txt"), ("ad6", "ids_after_s5.txt")):
        r = ops(env, "start", job)
        assert r.returncode == 1 and "REFUSED" in r.stdout and name in r.stdout
        assert not (Path(env["_jobs"]) / f"{job}.pid").exists()


def test_start_an_adaptive_job_with_an_empty_ids_file_says_nothing_to_do(env, tmp_path):
    write_frozen(env, prompt_sha(env))
    adaptive = tmp_path / "adaptive"
    adaptive.mkdir()
    (adaptive / "ids_after_s4.txt").write_text("")  # every brief already has a good candidate
    env["IMP_OPS_ADAPTIVE"] = str(adaptive)
    r = ops(env, "start", "ad5")
    assert r.returncode == 0 and "nothing to do" in r.stdout
    assert not (Path(env["_jobs"]) / "ad5.pid").exists()


def test_adaptive_job_total_is_the_ids_file_line_count(env, tmp_path):
    write_frozen(env, prompt_sha(env))
    adaptive = tmp_path / "adaptive"
    adaptive.mkdir()
    (adaptive / "ids_after_s4.txt").write_text("g001\ng002\ng003\n")
    env["IMP_OPS_ADAPTIVE"] = str(adaptive)

    started = ops(env, "start", "ad5")
    assert started.returncode == 0 and "started ad5" in started.stdout
    done = ops(env, "wait", "ad5", "30")
    # the fake bench writes 2 raw files; job_total is the 3-line ids file, not the 48 fallback
    assert done.returncode == 0 and "raw 2/3" in done.stdout


def test_distill_jobs_count_result_json_files_and_brief_totals(env, tmp_path):
    # raw progress is one result.json per finished brief (not the whole dir); job_total is the brief count.
    distill = tmp_path / "imp"
    env["IMP_OPS_DISTILL"] = str(distill)
    for name, done in (("distill", 1), ("distill-smoke", 2)):
        run = distill / ("distill_smoke" if name == "distill-smoke" else "distill")
        for i in range(done):
            (run / f"x{i:04d}").mkdir(parents=True)
            (run / f"x{i:04d}" / "result.json").write_text("{}")
        (run / "x9999").mkdir()  # a brief dir without a result.json is not counted yet
    jobs = Path(env["_jobs"])
    jobs.mkdir(parents=True, exist_ok=True)
    for name in ("distill", "distill-smoke"):
        (jobs / f"{name}.started").write_text("2026-01-01T00:00:00Z")

    status = ops(env, "status")
    total = len(ROOT.joinpath("bench/distill/briefs.jsonl").read_text().splitlines())
    assert status.returncode == 0, status.stderr
    assert f"distill: stopped, raw 1/{total}" in status.stdout
    assert "distill-smoke: stopped, raw 2/2" in status.stdout
