import json
import os
import subprocess
from pathlib import Path

import pytest

import glb_ops_judge

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "glb_ops.sh"

FAKE_BENCH = """#!/usr/bin/env bash
# stands in for glb_bench.py: parses --out-root and --only, waits a bit, writes two raw answers
while [ $# -gt 0 ]; do case "$1" in --out-root) out="$2"; shift 2 ;; --only) only="$2"; shift 2 ;; *) shift ;; esac; done
sleep "${FAKE_SLEEP:-3}"
mkdir -p "$out/$only/raw"; echo '{}' > "$out/$only/raw/g001.json"; echo '{}' > "$out/$only/raw/g002.json"
"""


@pytest.fixture
def env(tmp_path):
    bench = tmp_path / "fake_bench.sh"
    bench.write_text(FAKE_BENCH)
    bench.chmod(0o755)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("version one")
    e = dict(os.environ, GLB_OPS_RUNS=str(tmp_path / "runs"), GLB_OPS_BENCH=str(bench), GLB_OPS_PROMPT=str(prompt),
             GLB_OPS_POLL="1", GLB_OPS_SKIP_CHECKS="1", FAKE_SLEEP="3")
    e["_prompt"] = str(prompt)
    return e


def ops(env, *args):
    return subprocess.run(["bash", str(OPS), *args], env=env, capture_output=True, text=True, timeout=60)


def test_preflight_records_the_prompt_hash(env):
    r = ops(env, "preflight")
    assert r.returncode == 0 and "PREFLIGHT OK" in r.stdout
    assert "sha256" in (Path(env["GLB_OPS_RUNS"]) / "STATE.md").read_text()


def test_start_wait_still_running_then_finished(env):
    assert ops(env, "start", "dev1").returncode == 0
    r = ops(env, "wait", "dev1", "1")
    assert r.returncode == 2 and "still running" in r.stdout and "/12" in r.stdout
    r = ops(env, "wait", "dev1", "30")
    assert r.returncode == 0 and "finished with exit 0" in r.stdout and "raw 2/12" in r.stdout
    again = ops(env, "start", "dev1")
    assert again.returncode == 0 and "already finished" in again.stdout


def test_wait_on_a_job_that_never_started_fails(env):
    r = ops(env, "wait", "glimmer", "1")
    assert r.returncode == 1 and "never started" in r.stdout


def test_only_one_job_at_a_time(env):
    assert ops(env, "start", "dev1").returncode == 0
    r = ops(env, "start", "glimmer")
    assert r.returncode == 1  # refused: the prompt is not frozen, and dev1 is running
    ops(env, "wait", "dev1", "30")


def test_freeze_needs_a_pass_and_a_matching_prompt_then_locks_the_prompt(env):
    runs = Path(env["GLB_OPS_RUNS"])
    r = ops(env, "start", "glimmer")
    assert r.returncode == 1 and "not frozen" in r.stdout
    assert ops(env, "freeze").returncode == 1  # no verdict yet
    ops(env, "start", "dev1")
    ops(env, "wait", "dev1", "30")
    (runs / "dev1").mkdir(parents=True, exist_ok=True)
    (runs / "dev1" / "judge.json").write_text('{"verdict": "PASS"}')
    frozen = ops(env, "freeze")
    assert frozen.returncode == 0 and "FROZEN" in frozen.stdout
    assert ops(env, "start", "glimmer").returncode == 0
    ops(env, "wait", "glimmer", "30")
    Path(env["_prompt"]).write_text("version two")  # an edit after the freeze is refused
    r = ops(env, "start", "glimmer-think")
    assert r.returncode == 1 and "changed after it was frozen" in r.stdout


def test_freeze_refuses_when_the_prompt_changed_since_dev1(env):
    runs = Path(env["GLB_OPS_RUNS"])
    ops(env, "start", "dev1")
    ops(env, "wait", "dev1", "30")
    (runs / "dev1").mkdir(parents=True, exist_ok=True)
    (runs / "dev1" / "judge.json").write_text('{"verdict": "PASS"}')
    Path(env["_prompt"]).write_text("edited after dev1")
    r = ops(env, "freeze")
    assert r.returncode == 1 and "changed since dev1" in r.stdout


def write_run(folder, valid_ids, animated_ids, total=12):
    d = Path(folder) / "glimmer"
    (d / "raw").mkdir(parents=True)
    rows = []
    for i in range(1, total + 1):
        rid = f"d{i:03d}"
        kind = "animated" if rid in ("d004", "d009", "d012") else "static"
        ok = rid in valid_ids
        glb = {"animations": 1 if rid in animated_ids else 0}
        rows.append({"id": rid, "ok": ok, "reasons": [] if ok else ["js_error"], "stats": {"glb": glb} if ok else {}})
        (d / "raw" / f"{rid}.json").write_text(json.dumps({"brief": {"kind": kind}}))
    (d / "validation.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_judge_dev_passes_and_fails_on_each_side_of_the_rule(tmp_path):
    all_ids = {f"d{i:03d}" for i in range(1, 13)}
    write_run(tmp_path / "pass", all_ids, {"d004", "d009"})
    rows, raws = glb_ops_judge.load(tmp_path / "pass")
    assert glb_ops_judge.judge_dev(rows, raws)["verdict"] == "PASS"
    write_run(tmp_path / "one_anim", all_ids, {"d004"})
    rows, raws = glb_ops_judge.load(tmp_path / "one_anim")
    assert glb_ops_judge.judge_dev(rows, raws)["verdict"] == "FAIL"
    write_run(tmp_path / "nine_valid", set(sorted(all_ids)[:9]) | {"d004", "d009"} - {"d001"}, {"d004", "d009"})
    rows, raws = glb_ops_judge.load(tmp_path / "nine_valid")
    result = glb_ops_judge.judge_dev(rows, raws)
    assert result["valid"] < 10 and result["verdict"] == "FAIL"


def test_judge_main_writes_the_verdict_file_and_exit_code(tmp_path):
    all_ids = {f"d{i:03d}" for i in range(1, 13)}
    write_run(tmp_path / "ok", all_ids, {"d004", "d009", "d012"})
    assert glb_ops_judge.main(["x", "dev", str(tmp_path / "ok")]) == 0
    assert json.loads((tmp_path / "ok" / "judge.json").read_text())["verdict"] == "PASS"
    write_run(tmp_path / "bad", set(), set())
    assert glb_ops_judge.main(["x", "dev", str(tmp_path / "bad")]) == 1
