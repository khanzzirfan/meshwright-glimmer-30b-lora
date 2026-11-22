import http.server
import json
import struct
import sys
import threading
from pathlib import Path

import pytest

import glb_best_of
import glb_generate

ROOT = Path(__file__).resolve().parents[2]

# The fake validator's markers: what a canned page means for the exported asset.
GOOD = "<html>OK_ASSEMBLED</html>"   # valid and assembled -> the loop stops here
FLAT = "<html>OK_FLAT</html>"        # valid but not assembled
BIG = "<html>OK_BIG</html>"          # valid, not assembled, too many parts (ranking key 2 = 0)
HOVER = "<html>OK_HOVER</html>"      # valid, not assembled; its real GLB hovers, so grounding fixes it
DIRTY = "<html>OK_DIRTY</html>"      # valid and assembled; its GLB has a Blender-unsafe node name
BIGTRI = "<html>OK_BIGTRI</html>"    # valid and assembled, but over the triangle budget
FAIL = "<html>FAIL</html>"           # not valid, a repairable js_error
TRUNC = "<html>TRUNCATED</html>"     # not valid, not repairable (the answer was cut off)
NOHTML = "<html>NO_HTML</html>"      # not valid, not repairable (no page was written)

_MAGIC = 0x46546C67
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942


def make_glb(boxes, node_names=None):
    """A minimal valid GLB: one mesh node per (min, max) box, each a POSITION box with min/max.

    Enough for glb_check.mjs's assembly metric: one primitive per mesh, no indices, one triangle. The
    HOVER fixture needs a *real* GLB (not the fake's b"glTF") so glb_ground.mjs can actually shift it, and
    the DIRTY fixture needs real node names for glb_names.mjs to rewrite. ``node_names`` overrides the
    default ``n<i>`` names.
    """
    bin_data = b""
    buffer_views, accessors, meshes = [], [], []
    for i, (lo, hi) in enumerate(boxes):
        corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        data = struct.pack("<%df" % (len(corners) * 3), *[c for corner in corners for c in corner])
        buffer_views.append({"buffer": 0, "byteOffset": len(bin_data), "byteLength": len(data), "target": 34962})
        bin_data += data + b"\x00" * ((4 - len(data) % 4) % 4)
        accessors.append({"bufferView": len(buffer_views) - 1, "componentType": 5126,
                          "count": len(corners), "type": "VEC3", "min": list(lo), "max": list(hi)})
        meshes.append({"name": f"m{i}", "primitives": [{"attributes": {"POSITION": len(accessors) - 1}}]})
    nodes = [{"mesh": i, "name": (node_names[i] if node_names else f"n{i}")} for i in range(len(meshes))]
    gltf = {"asset": {"version": "2.0", "generator": "test_glb_generate.py"}, "scene": 0,
            "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes,
            "accessors": accessors, "bufferViews": buffer_views,
            "buffers": [{"byteLength": len(bin_data)}]}
    json_bytes = json.dumps(gltf).encode()
    json_chunk = json_bytes + b" " * ((4 - len(json_bytes) % 4) % 4)
    bin_chunk = bin_data + b"\x00" * ((4 - len(bin_data) % 4) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    out = bytearray(total)
    struct.pack_into("<III", out, 0, _MAGIC, 2, total)
    struct.pack_into("<II", out, 12, len(json_chunk), _JSON_CHUNK)
    out[20:20 + len(json_chunk)] = json_chunk
    off = 20 + len(json_chunk)
    struct.pack_into("<II", out, off, len(bin_chunk), _BIN_CHUNK)
    out[off + 8:off + 8 + len(bin_chunk)] = bin_chunk
    return bytes(out)

# A dependency-free stand-in for validate_scenes.mjs that reads the same --mode/--raw/--glb-dir/--report
# flags and decides ok/assembled from a marker in each page. Written to a temp file and pointed at with
# GLB_GENERATE_VALIDATOR, so the tests never launch Chromium.
FAKE_VALIDATOR = '''
import argparse
import json
import os
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--mode")
ap.add_argument("--allow-addons", action="store_true")
ap.add_argument("--raw", required=True)
ap.add_argument("--scenes")
ap.add_argument("--shots")
ap.add_argument("--glb-dir", required=True)
ap.add_argument("--report", required=True)
a = ap.parse_args()

raw_dir = Path(a.raw)
glb_dir = Path(a.glb_dir)
glb_dir.mkdir(parents=True, exist_ok=True)
rows = []
for path in sorted(raw_dir.glob("*.json")):
    raw = json.loads(path.read_text())
    content = raw.get("content") or ""
    brief_id = raw.get("id") or path.stem
    error = None
    triangles = 100
    glb_bytes = b"glTF"
    if "OK_ASSEMBLED" in content:
        ok, assembled, parts, reasons = True, True, 10, []
    elif "OK_HOVER" in content:
        # Valid but not assembled; its GLB really hovers, so glb_ground.mjs lifts it to y = 0.
        ok, assembled, parts, reasons = True, False, 10, []
        glb_bytes = Path(os.environ["FAKE_GLB_HOVER"]).read_bytes()
    elif "OK_DIRTY" in content:
        # Valid and assembled; its GLB has a Blender-unsafe node name, so glb_names.mjs rewrites it.
        ok, assembled, parts, reasons = True, True, 10, []
        glb_bytes = Path(os.environ["FAKE_GLB_DIRTY"]).read_bytes()
    elif "OK_BIGTRI" in content:
        # Valid and assembled, but over the triangle budget, so the stop rule must not stop here.
        ok, assembled, parts, reasons = True, True, 10, []
        triangles = 6000
    elif "OK_FLAT" in content:
        ok, assembled, parts, reasons = True, False, 10, []
    elif "OK_BIG" in content:
        ok, assembled, parts, reasons = True, False, 200, []
    elif "TRUNCATED" in content:
        ok, assembled, parts, reasons = False, False, 0, ["truncated"]
    elif "NO_HTML" in content:
        ok, assembled, parts, reasons = False, False, 0, ["no_html"]
    else:
        ok, assembled, parts, reasons = False, False, 0, ["js_error"]
        error = "ReferenceError: crate is not defined"
    row = {"id": brief_id, "ok": ok, "reasons": reasons, "stats": {}}
    if error:
        row["stats"]["error"] = error
    if ok:
        row["stats"]["glb"] = {"triangles": triangles, "assembly": {
            "parts": parts, "components": 1,
            "largest_share": 1.0 if assembled else 0.5,
            "floaters": 0, "min_y": 0, "ground_gap": 0, "tol": 0.1, "assembled": assembled}}
        (glb_dir / (brief_id + ".glb")).write_bytes(glb_bytes)
    rows.append(row)
Path(a.report).parent.mkdir(parents=True, exist_ok=True)
Path(a.report).write_text(chr(10).join(json.dumps(r) for r in rows) + chr(10))
'''


class Server:
    def __init__(self, contents):
        self.contents = contents
        self.requests = []

    def next_content(self):
        return self.contents[min(len(self.requests) - 1, len(self.contents) - 1)]


@pytest.fixture
def ollama(monkeypatch):
    """A fake Ollama /api/chat on localhost returning canned pages in order, recording requests."""
    servers = []

    def serve(contents):
        state = Server(list(contents))

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                state.requests.append(json.loads(self.rfile.read(length)))
                payload = json.dumps({
                    "message": {"content": state.next_content(), "thinking": None},
                    "done_reason": "stop",
                    "eval_count": 5,
                    "prompt_eval_count": 20,
                    "total_duration": 1_000_000_000,
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}", state

    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    yield serve
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def fake_validator(tmp_path, monkeypatch):
    """Install the fake validator via GLB_GENERATE_VALIDATOR and return its path.

    It also leaves the HOVER marker's real hovering GLB on disk (FAKE_GLB_HOVER), single box at y 1..2,
    so glb_ground.mjs shifts it down by 1 to reach the ground, and the DIRTY marker's real grounded GLB
    (FAKE_GLB_DIRTY), a single box at y 0 with a Blender-unsafe node name for glb_names.mjs to rewrite.
    """
    script = tmp_path / "fake_validator.py"
    script.write_text(FAKE_VALIDATOR)
    hover = tmp_path / "hover.glb"
    hover.write_bytes(make_glb([([0, 1, 0], [1, 2, 1])]))
    dirty = tmp_path / "dirty.glb"
    dirty.write_bytes(make_glb([([0, 0, 0], [1, 1, 1])], node_names=["sack_0.5_1.0499999999999998"]))
    monkeypatch.setenv("GLB_GENERATE_VALIDATOR", str(script))
    monkeypatch.setenv("FAKE_GLB_HOVER", str(hover))
    monkeypatch.setenv("FAKE_GLB_DIRTY", str(dirty))
    return script


def json_of(glb_bytes):
    """The glTF JSON of a GLB buffer (for the name assertions)."""
    json_len = struct.unpack_from("<I", glb_bytes, 12)[0]
    return json.loads(glb_bytes[20:20 + json_len].decode("utf-8"))


def write_models(tmp_path, overrides=None):
    """A models.json with one glimmer-v3 row and its own system file."""
    system_file = tmp_path / "system.txt"
    system_file.write_text("You are the GLB coder.\n")
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


def base_argv(prompt, out, models, url, *extra):
    return [prompt, "--out-dir", str(out), "--model-row", "glimmer-v3",
            "--models", str(models), "--ollama-url", url, *extra]


def read_result(out):
    return json.loads((Path(out) / "result.json").read_text())


# --- the three request-count scenarios (docs/14 US-001 acceptance) -------------------------------


def test_stops_at_the_first_good_candidate(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, state = ollama([GOOD, FLAT, FAIL])

    code = glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url, "--max-samples", "3"))

    assert len(state.requests) == 1
    assert code == 0
    result = read_result(tmp_path / "out")
    assert result["picked_seed"] == 1
    assert result["picked_ok"] is True
    assert result["picked_assembled"] is True
    assert (tmp_path / "out" / "asset.glb").exists()


def test_continues_after_an_unassembled_candidate(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, state = ollama([FLAT, GOOD, FAIL])

    code = glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url, "--max-samples", "3"))

    assert len(state.requests) == 2  # the first was ok but not assembled
    assert code == 0
    result = read_result(tmp_path / "out")
    assert result["picked_seed"] == 2
    assert result["picked_assembled"] is True
    assert result["assembly_repairs_used"] == 0  # the loop stopped at an assembled candidate


def test_uses_all_samples_when_none_is_assembled_and_picks_by_ranking(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, state = ollama([BIG, FLAT, FAIL, FAIL])

    code = glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url, "--max-samples", "3"))

    # imp-5: three samples (nothing assembled, so no early stop), then the one assembly repair turn (the
    # fourth reply is FAIL, so the repair does not recover). Updated from 3 requests for that turn.
    assert len(state.requests) == 4
    assert code == 0
    result = read_result(tmp_path / "out")
    # BIG has 200 parts (out of the 8-60 band), FLAT has 10, so the ranking prefers FLAT at seed 2.
    assert result["picked_seed"] == 2
    assert result["picked_ok"] is True
    assert result["picked_assembled"] is False
    assert result["assembly_repairs_used"] == 1


# --- imp-5: grounding, the triangle budget and the assembly repair --------------------------------


def test_a_hovering_candidate_is_accepted_after_grounding(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, state = ollama([HOVER, GOOD, FAIL])

    code = glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url, "--max-samples", "3"))

    # The validator saw HOVER as valid but not assembled; grounding lifted it, so one request is enough.
    assert len(state.requests) == 1
    assert code == 0
    result = read_result(tmp_path / "out")
    assert result["picked_seed"] == 1
    assert result["picked_assembled"] is True
    attempt = result["attempts"][0]
    assert attempt["assembled"] is True  # the grounding's assembly_after, not the validator's false
    assert attempt["grounded_shift"] == pytest.approx(-1)  # the box hovered at y = 1
    assert result["picked_within_budget"] is True
    grounded = tmp_path / "out" / "attempts" / "1" / "glb" / "asset.grounded.glb"
    assert grounded.exists()
    assert (tmp_path / "out" / "asset.glb").read_bytes() == grounded.read_bytes()


def test_generator_writes_a_sanitized_glb_and_records_renamed_names(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, state = ollama([DIRTY])

    code = glb_generate.main(base_argv("Make a sack.", tmp_path / "out", models, url, "--max-samples", "1"))

    assert len(state.requests) == 1
    assert code == 0
    result = read_result(tmp_path / "out")
    assert result["attempts"][0]["renamed_names"] == 1
    # the attempt's grounded copy and the delivered asset both carry the sanitized name
    grounded = tmp_path / "out" / "attempts" / "1" / "glb" / "asset.grounded.glb"
    assert [n["name"] for n in json_of(grounded.read_bytes())["nodes"]] == ["sack_0.5_1.05"]
    assert (tmp_path / "out" / "asset.glb").read_bytes() == grounded.read_bytes()
    assert [n["name"] for n in json_of((tmp_path / "out" / "asset.glb").read_bytes())["nodes"]] == ["sack_0.5_1.05"]


def test_a_clean_glb_records_zero_renamed_names(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, _ = ollama([HOVER, GOOD, FAIL])

    glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url, "--max-samples", "1"))

    # the HOVER fixture's names (n0, m0) are already safe, so nothing is renamed
    assert read_result(tmp_path / "out")["attempts"][0]["renamed_names"] == 0


def test_an_over_budget_assembled_candidate_does_not_stop_the_loop(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, state = ollama([BIGTRI, GOOD, FAIL])

    code = glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url, "--max-samples", "3"))

    # BIGTRI is valid and assembled but over the budget, so the loop spends one more request and stops.
    assert len(state.requests) == 2
    assert code == 0
    result = read_result(tmp_path / "out")
    assert result["picked_seed"] == 2
    assert result["attempts"][0]["within_budget"] is False
    assert result["attempts"][1]["within_budget"] is True
    assert result["picked_within_budget"] is True


def test_assembly_repair_runs_only_when_nothing_is_assembled(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, state = ollama([FLAT, FLAT, FLAT, GOOD])

    code = glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url, "--max-samples", "3"))

    # Three valid but unassembled samples, then exactly one assembly repair turn (the GOOD reply).
    assert len(state.requests) == 4
    repair = state.requests[3]
    assert [m["role"] for m in repair["messages"]] == ["system", "user", "assistant", "user"]
    assert "not assembled" in repair["messages"][3]["content"]
    assert code == 0
    result = read_result(tmp_path / "out")
    assert result["attempts"][-1]["repair"] == "assembly"
    assert result["assembly_repairs_used"] == 1
    assert result["picked_seed"] == 1  # the repaired sample's seed
    assert result["picked_assembled"] is True
    assert (tmp_path / "out" / "attempts" / "repair-asm" / "raw" / "asset.json").exists()


def test_no_repair_also_disables_the_assembly_repair(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, state = ollama([FLAT, FLAT, FLAT, GOOD])

    code = glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url,
                                       "--max-samples", "3", "--no-repair"))

    assert len(state.requests) == 3  # --no-repair: the GOOD reply is never requested
    assert code == 0  # a valid (unassembled) candidate is still picked
    result = read_result(tmp_path / "out")
    assert result["assembly_repairs_used"] == 0
    assert not any(a.get("repair") for a in result["attempts"])
    assert not (tmp_path / "out" / "attempts" / "repair-asm").exists()


def test_tri_budget_overrides_the_default(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, state = ollama([GOOD, GOOD, GOOD])

    code = glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url,
                                       "--max-samples", "3", "--tri-budget", "50"))

    # Every GOOD has 100 triangles, over the 50 budget, so the loop never stops early.
    assert len(state.requests) == 3
    assert code == 0
    result = read_result(tmp_path / "out")
    assert all(a["within_budget"] is False for a in result["attempts"])
    assert result["picked_within_budget"] is False


# --- result.json and the attempt directory -------------------------------------------------------


def test_result_json_has_the_listed_fields(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, _ = ollama([GOOD])

    glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url))

    result = read_result(tmp_path / "out")
    # imp-5 adds picked_within_budget and assembly_repairs_used beside the imp-4 keys.
    assert set(result) == {"prompt", "kind", "attempts", "picked_seed", "picked_ok",
                           "picked_assembled", "picked_within_budget", "total_seconds",
                           "system_sha256", "assembly_repairs_used"}
    assert result["prompt"] == "Make a crate."
    assert result["kind"] == "static"
    assert result["total_seconds"] == 1.0
    assert len(result["system_sha256"]) == 64
    assert result["assembly_repairs_used"] == 0
    assert len(result["attempts"]) == 1
    # imp-5: every attempt also records grounded_shift and within_budget; promo-1 US-008 adds renamed_names.
    assert set(result["attempts"][0]) == {"seed", "ok", "reasons", "assembled", "parts",
                                          "triangles", "seconds", "grounded_shift", "within_budget",
                                          "renamed_names"}
    attempt = result["attempts"][0]
    assert attempt["seed"] == 1
    assert attempt["ok"] is True and attempt["assembled"] is True
    assert attempt["reasons"] == []
    assert attempt["parts"] == 10 and attempt["triangles"] == 100
    assert attempt["grounded_shift"] is None  # the fake's b"glTF" is not a readable GLB, so no grounding
    assert attempt["within_budget"] is True
    assert attempt["renamed_names"] == 0  # an unreadable GLB has no names to rewrite


def test_attempt_files_are_written_under_the_seed(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, _ = ollama([GOOD])

    glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url))

    attempt = tmp_path / "out" / "attempts" / "1"
    assert json.loads((attempt / "raw" / "asset.json").read_text())["seed"] == 1
    assert (attempt / "page.html").exists()
    assert (attempt / "glb" / "asset.glb").exists()
    assert (attempt / "validation.jsonl").exists()


def test_seed_start_offsets_the_seeds_and_directories(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, _ = ollama([GOOD])

    glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url, "--seed-start", "7"))

    assert (tmp_path / "out" / "attempts" / "7" / "raw" / "asset.json").exists()
    assert read_result(tmp_path / "out")["picked_seed"] == 7


def test_exit_code_2_when_nothing_is_valid(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, state = ollama([FAIL, FAIL, FAIL, FAIL])

    code = glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url, "--max-samples", "3"))

    assert code == 2
    assert len(state.requests) == 4  # three samples, then the one repair turn (which also fails)
    result = read_result(tmp_path / "out")
    assert result["picked_ok"] is False
    assert result["attempts"][0]["reasons"] == ["js_error"]
    assert result["attempts"][-1]["repair"] is True
    assert not (tmp_path / "out" / "asset.glb").exists()


def test_no_validate_skips_the_validator(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, state = ollama([GOOD, GOOD, GOOD])

    code = glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url,
                                       "--max-samples", "3", "--no-validate"))

    assert len(state.requests) == 3  # nothing can be ok without validating, so every sample is spent
    assert code == 2
    result = read_result(tmp_path / "out")
    assert result["attempts"][0]["reasons"] == ["not_validated"]
    assert not (tmp_path / "out" / "attempts" / "1" / "validation.jsonl").exists()


# --- the repair turn (docs/14 US-002) ------------------------------------------------------------


def test_repair_runs_once_after_all_samples_fail(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, state = ollama([FAIL, FAIL, FAIL, GOOD])

    code = glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url, "--max-samples", "3"))

    # the three samples come first, then exactly one repair turn
    assert len(state.requests) == 4
    repair = state.requests[3]
    assert [m["role"] for m in repair["messages"]] == ["system", "user", "assistant", "user"]
    assert repair["messages"][1]["content"] == "Make a crate."
    assert repair["messages"][2]["content"] == FAIL  # the failed answer is fed back
    assert "js_error" in repair["messages"][3]["content"]
    assert "ReferenceError: crate is not defined" in repair["messages"][3]["content"]  # the first error

    assert code == 0
    result = read_result(tmp_path / "out")
    assert len(result["attempts"]) == 4
    assert result["attempts"][-1]["repair"] is True
    assert result["attempts"][-1]["ok"] is True
    assert result["picked_seed"] == 1  # the repaired sample's seed
    assert result["picked_ok"] is True
    assert (tmp_path / "out" / "attempts" / "repair" / "raw" / "asset.json").exists()
    assert (tmp_path / "out" / "asset.glb").exists()


@pytest.mark.parametrize("marker", [TRUNC, NOHTML])
def test_truncated_and_no_html_are_never_repaired(tmp_path, ollama, fake_validator, marker):
    models = write_models(tmp_path)
    url, state = ollama([marker, marker, marker, GOOD])

    code = glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url, "--max-samples", "3"))

    assert len(state.requests) == 3  # not repairable: no repair request is made
    assert code == 2
    result = read_result(tmp_path / "out")
    assert len(result["attempts"]) == 3
    assert not any(attempt.get("repair") for attempt in result["attempts"])


def test_no_repair_disables_the_repair(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    url, state = ollama([FAIL, FAIL, FAIL, GOOD])

    code = glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url,
                                       "--max-samples", "3", "--no-repair"))

    assert len(state.requests) == 3  # --no-repair: the GOOD reply is never requested
    assert code == 2
    assert not any(attempt.get("repair") for attempt in read_result(tmp_path / "out")["attempts"])


# --- the picker is imported, not copied ----------------------------------------------------------


def test_pick_is_imported_from_glb_best_of(tmp_path, ollama, fake_validator, monkeypatch):
    models = write_models(tmp_path)
    url, _ = ollama([BIG, FLAT, FAIL, FAIL])
    calls = []
    real_pick = glb_best_of.pick

    def spy(candidates):
        calls.append(list(candidates))
        return real_pick(candidates)

    monkeypatch.setattr(glb_best_of, "pick", spy)

    glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url, "--max-samples", "3"))

    assert calls  # the imported picker is used
    # imp-5: it is also used once to choose the assembly repair's best ok attempt, so the last call is the
    # final pick over every sampled attempt plus that repair turn (3 samples + 1 repair = 4).
    assert len(calls[-1]) == 4
    assert read_result(tmp_path / "out")["picked_seed"] == 2


# --- refusals and the validator command ----------------------------------------------------------

@pytest.mark.parametrize("sub", ["data/gen", "out/gen", "eval/gen", "data", "out", "eval"])
def test_protected_out_dir_is_refused(tmp_path, sub):
    models = write_models(tmp_path)

    with pytest.raises(SystemExit) as exc:
        glb_generate.main(base_argv("Make a crate.", ROOT / sub, models, "http://127.0.0.1:1"))

    assert exc.value.code != 0


def test_paid_model_row_is_refused_without_allow_paid(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path, {"paid": True})
    url, state = ollama([GOOD])

    with pytest.raises(SystemExit) as exc:
        glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url))

    assert exc.value.code != 0
    assert state.requests == []
    assert not (tmp_path / "out").exists()


def test_unknown_model_row_is_refused(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)

    with pytest.raises(SystemExit) as exc:
        glb_generate.main(["Make a crate.", "--out-dir", str(tmp_path / "out"),
                           "--model-row", "nope", "--models", str(models)])

    assert exc.value.code != 0


def test_validator_command_is_the_glb_bench_layout(tmp_path, monkeypatch):
    monkeypatch.delenv("GLB_GENERATE_VALIDATOR", raising=False)
    attempt = tmp_path / "attempts" / "1"

    cmd = glb_generate.validator_command(attempt)

    assert cmd[:3] == ["node", "scripts/validate_scenes.mjs", "--mode"]
    assert cmd[cmd.index("--mode") + 1] == "glb"
    assert "--allow-addons" in cmd
    assert cmd[cmd.index("--raw") + 1] == str(attempt / "raw")
    assert cmd[cmd.index("--scenes") + 1] == str(attempt / "scenes")
    assert cmd[cmd.index("--shots") + 1] == str(attempt / "shots")
    assert cmd[cmd.index("--glb-dir") + 1] == str(attempt / "glb")
    assert cmd[cmd.index("--report") + 1] == str(attempt / "validation.jsonl")


def test_validator_command_uses_the_env_override(tmp_path, monkeypatch):
    script = tmp_path / "fake.py"
    monkeypatch.setenv("GLB_GENERATE_VALIDATOR", str(script))

    cmd = glb_generate.validator_command(tmp_path)

    assert cmd[:2] == [sys.executable, str(script)]
    assert "--mode" in cmd and "glb" in cmd


# --- batch mode (docs/14 US-003) -----------------------------------------------------------------

BRIEFS = [
    {"id": "b1", "title": "Crate", "brief": "Make a crate.", "kind": "static"},
    {"id": "b2", "title": "Chair", "brief": "Make a chair.", "kind": "static"},
    {"id": "b3", "title": "Lantern", "brief": "Make a lantern.", "kind": "animated"},
]


def write_briefs(tmp_path, briefs=None):
    path = tmp_path / "briefs.jsonl"
    path.write_text("".join(json.dumps(b) + "\n" for b in (briefs or BRIEFS)))
    return path


def batch_argv(briefs, out, models, url, *extra):
    return ["--briefs", str(briefs), "--out-dir", str(out), "--model-row", "glimmer-v3",
            "--models", str(models), "--ollama-url", url, *extra]


def read_summary(out):
    return json.loads((Path(out) / "summary.json").read_text())


def test_batch_writes_summary_and_table(tmp_path, ollama, fake_validator, capsys):
    models = write_models(tmp_path)
    briefs = write_briefs(tmp_path)
    # b1: GOOD (1 request); b2: FLAT then GOOD (2); b3: FAIL x3 then one repair GOOD (4) -> 7 requests
    url, state = ollama([GOOD, FLAT, GOOD, FAIL, FAIL, FAIL, GOOD])

    code = glb_generate.main(batch_argv(briefs, tmp_path / "out", models, url, "--max-samples", "3"))

    assert len(state.requests) == 7
    assert code == 0
    summary = read_summary(tmp_path / "out")
    # mean_samples (1, 2, 3) -> 2.0; mean_seconds (1.0, 2.0, 4.0) -> 2.3333; one repair (b3).
    # imp-5 adds picked_within_budget (all three picked 100 triangles) and assembly_repairs_used (none).
    assert summary == {"briefs": 3, "picked_ok": 3, "picked_assembled": 3, "picked_within_budget": 3,
                       "mean_samples": 2.0, "mean_seconds": 2.3333, "repairs_used": 1,
                       "assembly_repairs_used": 0}
    for brief_id in ("b1", "b2", "b3"):
        assert (tmp_path / "out" / brief_id / "result.json").exists()
    printed = capsys.readouterr().out
    assert "b1" in printed and "b3" in printed and "3/3 ok" in printed


def test_batch_rerun_makes_no_new_requests(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    briefs = write_briefs(tmp_path)
    url, state = ollama([GOOD, FLAT, GOOD, FAIL, FAIL, FAIL, GOOD])

    glb_generate.main(batch_argv(briefs, tmp_path / "out", models, url, "--max-samples", "3"))
    assert len(state.requests) == 7

    code = glb_generate.main(batch_argv(briefs, tmp_path / "out", models, url, "--max-samples", "3"))

    assert len(state.requests) == 7  # every result.json existed, so no sample was requested
    assert code == 0
    assert read_summary(tmp_path / "out")["picked_ok"] == 3


def test_batch_ids_file_restricts_the_briefs(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    briefs = write_briefs(tmp_path)
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("# only the second brief\nb2\n")
    url, state = ollama([GOOD])

    code = glb_generate.main(batch_argv(briefs, tmp_path / "out", models, url, "--ids-file", str(ids_file)))

    assert len(state.requests) == 1
    assert code == 0
    assert (tmp_path / "out" / "b2" / "result.json").exists()
    assert not (tmp_path / "out" / "b1").exists()
    assert not (tmp_path / "out" / "b3").exists()
    assert read_summary(tmp_path / "out")["briefs"] == 1


def test_batch_limit_caps_the_briefs(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    briefs = write_briefs(tmp_path)
    url, state = ollama([GOOD, GOOD])

    code = glb_generate.main(batch_argv(briefs, tmp_path / "out", models, url, "--limit", "2"))

    assert len(state.requests) == 2
    assert code == 0
    assert not (tmp_path / "out" / "b3").exists()
    assert read_summary(tmp_path / "out")["briefs"] == 2


def test_prompt_and_briefs_are_mutually_exclusive(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)
    briefs = write_briefs(tmp_path)
    url, state = ollama([GOOD])

    with pytest.raises(SystemExit) as exc:
        glb_generate.main(base_argv("Make a crate.", tmp_path / "out", models, url,
                                    "--briefs", str(briefs)))

    assert exc.value.code != 0
    assert state.requests == []


def test_neither_prompt_nor_briefs_is_refused(tmp_path, ollama, fake_validator):
    models = write_models(tmp_path)

    with pytest.raises(SystemExit) as exc:
        glb_generate.main(["--out-dir", str(tmp_path / "out"), "--model-row", "glimmer-v3",
                           "--models", str(models)])

    assert exc.value.code != 0
