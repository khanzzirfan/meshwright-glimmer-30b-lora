import hashlib
import json
import sys
import urllib.request

import teacher_generate


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()


BRIEF = {"id": "b000", "brief": "Make a slowly spinning cube with soft lighting."}

OLLAMA_BODY = {
    "message": {"content": "<html>cube</html>", "thinking": "spin it"},
    "done_reason": "stop",
    "eval_count": 12,
    "prompt_eval_count": 34,
    "total_duration": 2_000_000_000,
}


def run_main(monkeypatch, tmp_path, extra_args):
    briefs = tmp_path / "briefs.jsonl"
    briefs.write_text(json.dumps(BRIEF) + "\n")
    out = tmp_path / "raw"
    requests = []

    def fake_urlopen(req, timeout=None):
        requests.append(json.loads(req.data.decode()))
        return FakeResponse(OLLAMA_BODY)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    argv = [
        "teacher_generate.py",
        "--briefs", str(briefs),
        "--out", str(out),
        "--model", "test-model",
        "--ollama-native",
    ] + extra_args
    monkeypatch.setattr(sys, "argv", argv)
    teacher_generate.main()
    return requests, out


def test_default_request_is_unchanged_and_row_has_system_metadata(monkeypatch, tmp_path):
    requests, out = run_main(monkeypatch, tmp_path, [])

    system_text = teacher_generate.system_prompt()
    assert len(requests) == 1
    body = requests[0]
    assert body["model"] == "test-model"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["options"] == {
        "temperature": 0.7,
        "top_p": 0.95,
        "num_ctx": 16384,
        "num_predict": 12000,
    }
    assert body["messages"] == [
        {"role": "system", "content": system_text},
        {"role": "user", "content": BRIEF["brief"]},
    ]

    row = json.loads((out / "b000.json").read_text())
    assert row["system_file"] == "prompts/system.txt"
    assert row["system_sha256"] == hashlib.sha256(system_text.encode()).hexdigest()


def test_system_file_and_sampling_reach_the_request_exactly(monkeypatch, tmp_path):
    system_file = tmp_path / "ccore_system.txt"
    system_text = "You are ccore's asset coder.\nKeep thinking on.\n"
    system_file.write_text(system_text)

    requests, out = run_main(
        monkeypatch,
        tmp_path,
        ["--system", str(system_file), "--top-k", "40", "--min-p", "0", "--repeat-penalty", "1.0"],
    )

    assert len(requests) == 1
    body = requests[0]
    assert body["messages"] == [
        {"role": "system", "content": system_text},
        {"role": "user", "content": BRIEF["brief"]},
    ]
    assert body["options"]["top_k"] == 40
    assert "min_p" in body["options"]
    assert body["options"]["min_p"] == 0.0
    assert body["options"]["repeat_penalty"] == 1.0

    row = json.loads((out / "b000.json").read_text())
    assert row["system_file"] == str(system_file)
    assert row["system_sha256"] == hashlib.sha256(system_text.encode()).hexdigest()


def test_rerun_skips_briefs_already_saved(monkeypatch, tmp_path):
    requests, out = run_main(monkeypatch, tmp_path, [])
    assert len(requests) == 1

    saved = json.loads((out / "b000.json").read_text())
    requests, _ = run_main(monkeypatch, tmp_path, [])
    assert requests == []
    assert json.loads((out / "b000.json").read_text()) == saved
