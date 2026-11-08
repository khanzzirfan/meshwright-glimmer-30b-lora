import hashlib
import http.server
import json
import threading
from pathlib import Path

import pytest

import glb_repair

ROOT = Path(__file__).resolve().parents[2]

FIXED_HTML = "<html><body>fixed</body></html>"
OLLAMA_RESPONSE = {
    "message": {"content": FIXED_HTML, "thinking": None},
    "done_reason": "stop",
    "eval_count": 5,
    "prompt_eval_count": 20,
    "total_duration": 1_000_000_000,
}

# One failing row per reason: the seven repairable ones, then the three the spec never selects.
REPAIRABLE = ["js_error", "load_fail", "no_download", "export_error", "bad_glb", "empty_glb", "no_export_button"]
SKIPPED = ["truncated", "no_html", "external_dep"]


class Recorder:
    def __init__(self, response):
        self.requests = []
        self.response = response


@pytest.fixture
def ollama(monkeypatch):
    """A fake Ollama /api/chat on localhost that records every request body."""
    recorder = Recorder(OLLAMA_RESPONSE)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            recorder.requests.append(json.loads(self.rfile.read(length)))
            payload = json.dumps(recorder.response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", recorder
    finally:
        server.shutdown()
        server.server_close()


def write_run(tmp_path):
    """A run directory with a repairable failure per reason, plus one that already passes."""
    run = tmp_path / "glimmer-v3"
    (run / "raw").mkdir(parents=True)
    rows = []
    ids = []
    for i, reason in enumerate(REPAIRABLE):
        brief_id = f"r{i}"
        stats = {"error": "boom"} if i == 0 else {}
        rows.append({"id": brief_id, "ok": False, "reasons": [reason], "stats": stats})
        write_raw(run, brief_id, f"<html>broken {brief_id}</html>")
        ids.append(brief_id)
    for reason in SKIPPED:
        brief_id = reason[:2] + reason[-1]
        rows.append({"id": brief_id, "ok": False, "reasons": [reason], "stats": {}})
        write_raw(run, brief_id, f"<html>broken {brief_id}</html>")
    rows.append({"id": "ok1", "ok": True, "reasons": [], "stats": {}})
    write_raw(run, "ok1", "<html>fine</html>")
    (run / "validation.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return run, ids


def write_raw(run, brief_id, content):
    row = {
        "id": brief_id,
        "brief": {"id": brief_id, "brief": f"Make a {brief_id}.", "kind": "static"},
        "model": "muse-glimmer:30b-mlx",
        "content": content,
    }
    (run / "raw" / f"{brief_id}.json").write_text(json.dumps(row))


def write_models(tmp_path, system_file, overrides=None):
    row = {
        "name": "glimmer-v3",
        "provider": "ollama",
        "model": "muse-glimmer:30b-mlx",
        "system": str(system_file),
        "temperature": 0.7,
        "top_p": 0.95,
        "top_k": None,
        "min_p": None,
        "think": False,
        "enabled": False,
        "paid": False,
    }
    row.update(overrides or {})
    path = tmp_path / "models.json"
    path.write_text(json.dumps([row]))
    return path


def make_env(tmp_path):
    system_file = tmp_path / "system.txt"
    system_file.write_text("You are the GLB coder.\n")
    run, ids = write_run(tmp_path)
    models = write_models(tmp_path, system_file)
    return run, ids, models, system_file


def run_main(argv):
    return glb_repair.main(argv)


def base_argv(run, models, url, *extra):
    return ["--run", str(run), "--model-row", "glimmer-v3", "--models", str(models),
            "--ollama-url", url, "--no-validate", *extra]


def test_select_ids_keeps_the_seven_and_skips_the_rest(tmp_path):
    run, ids, _, _ = make_env(tmp_path)
    rows = glb_repair.read_rows(run / "validation.jsonl")

    assert glb_repair.select_ids(rows) == ids
    assert set(glb_repair.REPAIRABLE_REASONS) == set(REPAIRABLE)
    assert glb_repair.SKIP_REASONS == set(SKIPPED)


def test_select_ids_skips_a_row_that_also_has_a_skip_reason():
    rows = [
        {"id": "a", "ok": False, "reasons": ["js_error"], "stats": {}},
        {"id": "b", "ok": False, "reasons": ["js_error", "truncated"], "stats": {}},
        {"id": "c", "ok": False, "reasons": ["blank"], "stats": {}},
        {"id": "d", "ok": True, "reasons": [], "stats": {}},
    ]
    assert glb_repair.select_ids(rows) == ["a"]


def test_fix_message_is_the_docs_14_section_5_text():
    row = {"id": "r0", "ok": False, "reasons": ["js_error", "blank"],
           "stats": {"error": "ReferenceError: x is not defined"}}
    assert glb_repair.fix_message(row) == (
        "The page you wrote failed when tested: js_error, blank. "
        "First error: ReferenceError: x is not defined. "
        "Reply with the complete corrected HTML file in one ```html block. "
        "Keep the asset the same and fix only what is broken. "
        "Remember the GLB exporter rules in the system prompt."
    )


def test_fix_message_says_none_recorded_without_stats_error():
    row = {"id": "r1", "ok": False, "reasons": ["load_fail"], "stats": {}}
    assert "First error: none recorded." in glb_repair.fix_message(row)


def test_fake_server_sees_the_four_messages_and_the_row_is_saved(tmp_path, ollama):
    url, recorder = ollama
    run, ids, models, system_file = make_env(tmp_path)

    run_main(base_argv(run, models, url, "--limit", "1"))

    assert len(recorder.requests) == 1
    body = recorder.requests[0]
    assert body["model"] == "muse-glimmer:30b-mlx"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["options"] == {"num_ctx": 49152, "num_predict": 40000, "temperature": 0.7, "top_p": 0.95}
    assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant", "user"]
    assert body["messages"][0]["content"] == system_file.read_text()
    assert body["messages"][1]["content"] == "Make a r0."
    assert body["messages"][2]["content"] == "<html>broken r0</html>"
    assert body["messages"][3]["content"] == (
        "The page you wrote failed when tested: js_error. First error: boom. "
        "Reply with the complete corrected HTML file in one ```html block. "
        "Keep the asset the same and fix only what is broken. "
        "Remember the GLB exporter rules in the system prompt."
    )

    saved = json.loads((run / "repair" / "raw" / "r0.json").read_text())
    assert saved["id"] == "r0"
    assert saved["content"] == FIXED_HTML
    assert saved["repair_of"] == "r0"
    assert saved["fix_message"] == body["messages"][3]["content"]
    assert saved["model"] == "muse-glimmer:30b-mlx"
    assert saved["brief"]["id"] == "r0"


def test_generates_one_request_per_selected_id(tmp_path, ollama):
    url, recorder = ollama
    run, ids, models, _ = make_env(tmp_path)

    run_main(base_argv(run, models, url))

    assert len(recorder.requests) == len(ids) == 7
    for brief_id in ids:
        assert (run / "repair" / "raw" / f"{brief_id}.json").exists()


def test_rerun_makes_no_new_requests_for_written_ids(tmp_path, ollama):
    url, recorder = ollama
    run, ids, models, _ = make_env(tmp_path)

    run_main(base_argv(run, models, url))
    first = len(recorder.requests)
    assert first == 7

    run_main(base_argv(run, models, url))
    assert len(recorder.requests) == first  # every raw file existed, so nothing was re-requested


def test_summary_json_reports_selected_attempted_and_repaired(tmp_path, ollama):
    url, recorder = ollama
    run, ids, models, system_file = make_env(tmp_path)

    run_main(base_argv(run, models, url))

    # The fake reply is fine, so the repair directory validates as a pass.
    repair_rows = [{"id": brief_id, "ok": True, "reasons": [], "stats": {}} for brief_id in ids]
    (run / "repair" / "validation.jsonl").write_text("".join(json.dumps(r) + "\n" for r in repair_rows))
    run_main(base_argv(run, models, url))

    summary = json.loads((run / "repair" / "summary.json").read_text())
    assert summary["selected"] == 7
    assert summary["attempted"] == 0  # nothing new was generated on the second run
    assert summary["repaired"] == 7
    assert summary["ids_repaired"] == ids
    assert summary["model"] == "glimmer-v3"
    assert summary["system_file"] == str(system_file)
    assert summary["system_sha256"] == hashlib.sha256(system_file.read_bytes()).hexdigest()


def test_limit_caps_the_selected_ids(tmp_path, ollama):
    url, recorder = ollama
    run, ids, models, _ = make_env(tmp_path)

    run_main(base_argv(run, models, url, "--limit", "2"))

    assert len(recorder.requests) == 2
    summary = json.loads((run / "repair" / "summary.json").read_text())
    assert summary["selected"] == 2 and summary["attempted"] == 2


def test_validate_command_matches_the_bench_layout(tmp_path):
    repair = tmp_path / "glimmer-v3" / "repair"
    cmd = glb_repair.validate_command(repair)
    assert cmd[:3] == ["node", "scripts/validate_scenes.mjs", "--mode"]
    assert cmd[cmd.index("--mode") + 1] == "glb"
    assert "--allow-addons" in cmd
    assert cmd[cmd.index("--raw") + 1] == str(repair / "raw")
    assert cmd[cmd.index("--scenes") + 1] == str(repair / "scenes")
    assert cmd[cmd.index("--shots") + 1] == str(repair / "shots")
    assert cmd[cmd.index("--glb-dir") + 1] == str(repair / "glb")
    assert cmd[cmd.index("--report") + 1] == str(repair / "validation.jsonl")


def test_validated_repairs_counts_only_selected_ok_rows():
    selected = ["a", "b", "c"]
    repair_rows = [{"id": "a", "ok": True}, {"id": "b", "ok": False}, {"id": "z", "ok": True}]
    assert glb_repair.validated_repairs(selected, repair_rows) == ["a"]


@pytest.mark.parametrize("sub", ["data/repair_run", "out/repair_run", "eval/repair_run", "data", "out", "eval"])
def test_run_inside_data_out_or_eval_is_refused(tmp_path, ollama, sub):
    url, recorder = ollama
    _, _, models, _ = make_env(tmp_path)
    run = ROOT / sub

    with pytest.raises(SystemExit) as exc:
        run_main(base_argv(run, models, url))

    assert exc.value.code != 0
    assert recorder.requests == []


def test_paid_model_row_is_refused_without_allow_paid(tmp_path, ollama):
    url, recorder = ollama
    run, _, _, system_file = make_env(tmp_path)
    models = write_models(tmp_path, system_file, {"name": "spark-open", "paid": True})

    with pytest.raises(SystemExit) as exc:
        run_main(["--run", str(run), "--model-row", "spark-open", "--models", str(models),
                  "--ollama-url", url, "--no-validate"])

    assert exc.value.code != 0
    assert recorder.requests == []


def test_unknown_model_row_is_refused(tmp_path, ollama):
    url, recorder = ollama
    run, _, models, _ = make_env(tmp_path)

    with pytest.raises(SystemExit) as exc:
        run_main(["--run", str(run), "--model-row", "not-a-row", "--models", str(models),
                  "--ollama-url", url, "--no-validate"])

    assert exc.value.code != 0
    assert recorder.requests == []
