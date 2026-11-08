"""Every command scripts/imp_ops.sh prints must parse with the real script's argparse parser.

The fake bench in tests/py/test_imp_ops.py accepted `--run-suffix -s2`, which the real glb_bench.py
rejects (argparse reads the value as a missing argument). That drift is the bug this test exists for:
it reads the case labels out of imp_ops.sh, gets each job's real command with IMP_OPS_DRY=1, and parses
the arguments with that script's own build_parser(), so the wrapper and the parsers can never disagree
again. One job name produces one parametrized case; adding a job to job_cmd() adds a case here.
"""
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

import glb_bench
import glb_generate
import glb_repair

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "imp_ops.sh"

# script file name -> its real argument parser (exposed as build_parser for exactly this test)
PARSERS = {
    "glb_bench.py": glb_bench.build_parser,
    "glb_repair.py": glb_repair.build_parser,
    "glb_generate.py": glb_generate.build_parser,
}


def _function_body(name):
    """The text of a shell function, up to the first `}` at the start of a line."""
    match = re.search(rf"^{re.escape(name)}\(\) \{{(.*?)^\}}", OPS.read_text(), re.MULTILINE | re.DOTALL)
    assert match, f"{name}() not found in {OPS}"
    return match.group(1)


def job_names():
    """The job names imp_ops.sh can start, read from job_cmd()'s case labels (order kept, no `*`)."""
    labels = re.findall(r"^\s*([a-z][a-z0-9-]*)\)", _function_body("job_cmd"), re.MULTILINE)
    names = list(dict.fromkeys(labels))
    assert names, "no job labels found in job_cmd()"
    return names


def dry_env(tmp_path):
    """A clean environment for a dry run (no inherited IMP_OPS_*), jobs under the temp dir."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("IMP_OPS_")}
    env["IMP_OPS_DRY"] = "1"
    env["IMP_OPS_JOBS"] = str(tmp_path / "jobs")
    return env


def job_command(job, env, script=OPS):
    """The command imp_ops.sh prints for a job with IMP_OPS_DRY=1."""
    result = subprocess.run(["bash", str(script), "start", job],
                            capture_output=True, text=True, env=env, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def parse_command(command):
    """Parse a job command's arguments with the target script's real build_parser()."""
    parts = shlex.split(command)
    tokens = [part for part in parts if Path(part).name in PARSERS]
    assert len(tokens) == 1, f"expected exactly one known script in the command: {command}"
    token = tokens[0]
    parser = PARSERS[Path(token).name]()
    return parser.parse_args(parts[parts.index(token) + 1:])


@pytest.mark.parametrize("job", job_names())
def test_every_job_command_parses_with_the_real_parser(job, tmp_path):
    parse_command(job_command(job, dry_env(tmp_path)))  # SystemExit on any argparse error


def test_the_distill_jobs_are_covered(tmp_path):
    # the parametrize above only covers what job_names() finds, so assert the imp-5 jobs are in it
    # (a renamed or removed distill job cannot silently drop out of the parser guard)
    assert {"distill", "distill-smoke"} <= set(job_names())


def test_run_suffix_with_a_space_fails_to_parse(tmp_path):
    # The regression that motivated this file: `--run-suffix -s2` is not a value argparse will accept,
    # so it must fail. The fake bench used to accept it; the real parser does not. Broken in a temp copy.
    text = OPS.read_text()
    broken = text.replace("--run-suffix=-s2", "--run-suffix -s2")
    assert broken != text, "expected the v3s2 job to use --run-suffix=-s2"
    broken_script = tmp_path / "imp_ops_broken.sh"
    broken_script.write_text(broken)

    command = job_command("v3s2", dry_env(tmp_path), script=broken_script)
    assert "--run-suffix -s2" in command
    with pytest.raises(SystemExit):
        parse_command(command)
