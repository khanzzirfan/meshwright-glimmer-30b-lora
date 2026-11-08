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
        "repair-v3": ".venv/bin/python scripts/glb_repair.py --run runs/glb_v3/glimmer-v3 --model-row glimmer-v3",
        "repair-asm-v3": ".venv/bin/python scripts/glb_repair.py --run runs/glb_v3/glimmer-v3 --model-row glimmer-v3 --mode assembly",
        "repair-asm-v3s3": ".venv/bin/python scripts/glb_repair.py --run runs/glb_v3/glimmer-v3-s3 --model-row glimmer-v3 --mode assembly",
    }
    for job, command in expected.items():
        r = ops(env, "start", job)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == command
    assert not (tmp_path / "jobs").exists()
