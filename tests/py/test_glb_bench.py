import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import glb_bench

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "bench" / "glb" / "models.json"
SCRIPT = ROOT / "scripts" / "glb_bench.py"


def args(**overrides):
    base = {
        "out_root": str(ROOT / "_bench_out_tmp"),
        "models": str(MODELS),
        "briefs": "bench/glb/briefs.jsonl",
        "only": None,
        "limit": 0,
        "num_ctx": 49152,
        "max_tokens": 40000,
        "allow_paid": False,
        "dry_run": False,
        "seed": None,
        "run_suffix": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def value_after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def test_models_json_has_seven_rows_and_two_enabled():
    models = glb_bench.load_models(MODELS)
    assert [m["name"] for m in models] == [
        "ccore-q8", "glimmer", "glimmer-think", "qwen35-4b-base", "ccore-ourprompt", "spark-open", "glimmer-v3",
    ]
    assert {m["name"] for m in models if m["enabled"]} == {"ccore-q8", "glimmer"}
    fields = {"name", "provider", "model", "system", "temperature", "top_p", "top_k", "min_p",
              "think", "enabled", "paid"}
    for model in models:
        assert set(model) == fields
        assert model["provider"] in {"ollama", "baseten"}
        assert model["system"].startswith("prompts/")
    assert [m["name"] for m in models if m["paid"]] == ["spark-open"]

    ccore = next(m for m in models if m["name"] == "ccore-q8")
    assert ccore["temperature"] == 0.8
    assert ccore["top_k"] == 40
    assert ccore["top_p"] == 0.95
    assert ccore["min_p"] == 0.0
    assert ccore["think"] is True


def test_plan_emits_generate_then_validate_for_enabled_rows():
    commands = glb_bench.plan(glb_bench.load_models(MODELS), args())

    assert len(commands) == 4
    ccore_gen, ccore_val, glimmer_gen, glimmer_val = commands

    assert Path(ccore_gen[1]).name == "teacher_generate.py"
    assert value_after(ccore_gen, "--model") == "hf.co/ccore/Qwen3.5-4B-GLB-3D-Coder:Q8_0"
    assert "--ollama-native" in ccore_gen
    assert value_after(ccore_gen, "--system") == str(ROOT / "prompts" / "ccore_glb_system.txt")
    assert value_after(ccore_gen, "--temperature") == "0.8"
    assert value_after(ccore_gen, "--top-k") == "40"
    assert value_after(ccore_gen, "--top-p") == "0.95"
    assert value_after(ccore_gen, "--min-p") == "0"
    assert "--think" in ccore_gen
    assert value_after(ccore_gen, "--concurrency") == "1"
    assert value_after(ccore_gen, "--num-ctx") == "49152"
    assert value_after(ccore_gen, "--max-tokens") == "40000"
    assert value_after(ccore_gen, "--out") == str(Path(args().out_root) / "ccore-q8" / "raw")

    assert Path(glimmer_gen[1]).name == "teacher_generate.py"
    assert value_after(glimmer_gen, "--model") == "muse-glimmer:30b-mlx"
    assert value_after(glimmer_gen, "--temperature") == "0.7"
    assert value_after(glimmer_gen, "--top-p") == "0.95"
    assert "--top-k" not in glimmer_gen
    assert "--min-p" not in glimmer_gen
    assert "--think" not in glimmer_gen

    for val, name in ((ccore_val, "ccore-q8"), (glimmer_val, "glimmer")):
        assert val[:2] == ["node", "scripts/validate_scenes.mjs"]
        assert value_after(val, "--mode") == "glb"
        assert value_after(val, "--raw") == str(Path(args().out_root) / name / "raw")
        assert value_after(val, "--scenes") == str(Path(args().out_root) / name / "scenes")
        assert value_after(val, "--shots") == str(Path(args().out_root) / name / "shots")
        assert value_after(val, "--glb-dir") == str(Path(args().out_root) / name / "glb")
        assert value_after(val, "--report") == str(Path(args().out_root) / name / "validation.jsonl")


def test_only_selects_a_disabled_row():
    commands = glb_bench.plan(glb_bench.load_models(MODELS), args(only=["qwen35-4b-base"]))

    assert len(commands) == 2
    gen = commands[0]
    assert value_after(gen, "--model") == "qwen3.5:4b"
    assert value_after(gen, "--temperature") == "0.8"
    assert value_after(gen, "--top-k") == "40"
    assert "--min-p" not in gen
    assert "--think" in gen


def run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["glb_bench.py"] + argv)

    def no_run(*a, **k):
        raise AssertionError("a command was run during a refused invocation")

    monkeypatch.setattr(subprocess, "run", no_run)
    with pytest.raises(SystemExit) as exc:
        glb_bench.main()
    assert exc.value.code != 0


def write_models(tmp_path, mutate):
    models = glb_bench.load_models(MODELS)
    mutate(models)
    path = tmp_path / "models.json"
    path.write_text(json.dumps(models))
    return path


@pytest.mark.parametrize("out_root", ["data/bench_out", "out/bench_out", "data", "out"])
def test_out_root_inside_data_or_out_is_refused(monkeypatch, tmp_path, out_root):
    run_main(monkeypatch, [
        "--out-root", str(ROOT / out_root), "--models", str(MODELS),
        "--only", "glimmer", "--dry-run",
    ])


def test_missing_system_file_is_refused(monkeypatch, tmp_path):
    path = write_models(tmp_path, lambda models: models[0].update(system=str(tmp_path / "missing.txt")))
    run_main(monkeypatch, [
        "--out-root", str(tmp_path / "bench"), "--models", str(path),
        "--only", "ccore-q8", "--dry-run",
    ])


def test_placeholder_system_file_is_refused(monkeypatch, tmp_path):
    placeholder = tmp_path / "ccore_glb_system.txt"
    placeholder.write_text("PASTE_CCORE_SYSTEM_PROMPT_HERE: replace me\n")
    path = write_models(tmp_path, lambda models: models[0].update(system=str(placeholder)))
    run_main(monkeypatch, [
        "--out-root", str(tmp_path / "bench"), "--models", str(path),
        "--only", "ccore-q8", "--dry-run",
    ])


def test_paid_row_without_allow_paid_is_refused(monkeypatch, tmp_path):
    run_main(monkeypatch, [
        "--out-root", str(tmp_path / "bench"), "--models", str(MODELS),
        "--only", "spark-open", "--dry-run",
    ])


def test_unknown_only_name_is_refused(monkeypatch, tmp_path):
    run_main(monkeypatch, [
        "--out-root", str(tmp_path / "bench"), "--models", str(MODELS),
        "--only", "not-a-model", "--dry-run",
    ])


def test_paid_row_runs_with_allow_paid(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", [
        "glb_bench.py", "--out-root", str(tmp_path / "bench"), "--models", str(MODELS),
        "--only", "spark-open", "--allow-paid", "--dry-run",
    ])
    glb_bench.main()
    out = capsys.readouterr().out
    assert "teacher_generate.py" in out
    assert "validate_scenes.mjs" in out
    assert not (tmp_path / "bench").exists()


def test_dry_run_subprocess_writes_nothing(tmp_path):
    out_root = tmp_path / "bench-out"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--out-root", str(out_root), "--models", str(MODELS),
         "--only", "glimmer", "--dry-run"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "teacher_generate.py" in proc.stdout
    assert "validate_scenes.mjs" in proc.stdout
    assert not out_root.exists() or list(out_root.iterdir()) == []


def test_remote_ollama_url_and_concurrency_reach_the_generate_command():
    generate = glb_bench.plan(glb_bench.load_models(MODELS), args(only=["ccore-q8"], ollama_url="http://localhost:11435", concurrency=4))[0]
    assert value_after(generate, "--ollama-url") == "http://localhost:11435"
    assert value_after(generate, "--concurrency") == "4"


def test_defaults_keep_the_local_server_and_one_request_at_a_time():
    generate = glb_bench.plan(glb_bench.load_models(MODELS), args(only=["ccore-q8"]))[0]
    assert "--ollama-url" not in generate
    assert value_after(generate, "--concurrency") == "1"


# --- US-005: --seed and --run-suffix -------------------------------------------------------------


def test_default_plan_without_seed_or_suffix_is_byte_identical():
    out = ROOT / "_bench_out_tmp"
    assert glb_bench.plan(glb_bench.load_models(MODELS), args(only=["glimmer"])) == [
        [sys.executable, "scripts/teacher_generate.py", "--briefs", "bench/glb/briefs.jsonl",
         "--out", str(out / "glimmer" / "raw"), "--model", "muse-glimmer:30b-mlx",
         "--ollama-native", "--system", str(ROOT / "prompts" / "system_glb.txt"),
         "--temperature", "0.7", "--top-p", "0.95",
         "--num-ctx", "49152", "--max-tokens", "40000", "--concurrency", "1"],
        ["node", "scripts/validate_scenes.mjs", "--mode", "glb", "--allow-addons",
         "--raw", str(out / "glimmer" / "raw"), "--scenes", str(out / "glimmer" / "scenes"),
         "--shots", str(out / "glimmer" / "shots"), "--glb-dir", str(out / "glimmer" / "glb"),
         "--report", str(out / "glimmer" / "validation.jsonl")],
    ]


def test_seed_reaches_the_generate_command_only_when_given():
    assert "--seed" not in glb_bench.plan(glb_bench.load_models(MODELS), args(only=["glimmer"]))[0]
    generate = glb_bench.plan(glb_bench.load_models(MODELS), args(only=["glimmer"], seed=42))[0]
    assert value_after(generate, "--seed") == "42"


def test_run_suffix_changes_every_run_directory():
    generate, validate = glb_bench.plan(
        glb_bench.load_models(MODELS), args(only=["glimmer"], run_suffix="-s2")
    )
    run = Path(args().out_root) / "glimmer-s2"
    assert value_after(generate, "--out") == str(run / "raw")
    assert value_after(validate, "--scenes") == str(run / "scenes")
    assert value_after(validate, "--report") == str(run / "validation.jsonl")
