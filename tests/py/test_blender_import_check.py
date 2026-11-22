"""The Blender headless import proof (docs/15 section 7, Ralph promo-1 US-006).

``scripts/blender_import_check.py`` runs inside Blender, imports GLBs and writes a report. The offline
tests cover the argument parser, the parts-image name and the name-safe copy (``scripts/glb_names.mjs``),
and the crashed-worker reporting, and need no Blender. The import tests write a tiny two-box, one-animation
GLB and run Blender on it; when Blender is not on PATH they are skipped with a clear message so the gate
still passes (US-006 acceptance criteria).
"""
import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

import blender_import_check
from blender_import_check import build_parser, parts_path_for, sanitize_glb_copy, split_glbs

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "blender_import_check.py"
BLENDER = shutil.which("blender")

MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def _pad4(n):
    return (4 - (n % 4)) % 4


def tiny_glb(meshes=2, animations=1, node_names=None):
    """A two-box, one-animation GLB equivalent to tests/js/glb_util.mjs makeGlb."""
    bin_parts = []
    bin_len = 0
    buffer_views = []
    accessors = []

    def add_view(data, target=None):
        nonlocal bin_len
        view = {"buffer": 0, "byteOffset": bin_len, "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        buffer_views.append(view)
        bin_parts.append(data + b"\x00" * _pad4(len(data)))
        bin_len += len(data) + _pad4(len(data))
        return len(buffer_views) - 1

    gltf_meshes = []
    for m in range(meshes):
        corners = [(m * 4.0 + dx, dy, dz) for dx in (0.0, 1.0) for dy in (0.0, 1.0) for dz in (0.0, 1.0)]
        positions = b"".join(struct.pack("<3f", *corners[k % 8]) for k in range(36))
        pos_accessor = len(accessors)
        accessors.append({"bufferView": add_view(positions, 34962), "componentType": 5126, "count": 36,
                          "type": "VEC3", "min": [m * 4.0, 0.0, 0.0], "max": [m * 4.0 + 1.0, 1.0, 1.0]})
        indices = b"".join(struct.pack("<H", k % 36) for k in range(36))
        idx_accessor = len(accessors)
        accessors.append({"bufferView": add_view(indices, 34963), "componentType": 5123, "count": 36,
                          "type": "SCALAR"})
        gltf_meshes.append({"name": f"mesh{m}", "primitives": [
            {"attributes": {"POSITION": pos_accessor}, "indices": idx_accessor, "material": 0, "mode": 4}]})

    gltf_animations = []
    for a in range(animations):
        times = struct.pack("<2f", 0.0, 1.0)
        time_accessor = len(accessors)
        accessors.append({"bufferView": add_view(times), "componentType": 5126, "count": 2,
                          "type": "SCALAR", "min": [0.0], "max": [1.0]})
        values = struct.pack("<6f", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        value_accessor = len(accessors)
        accessors.append({"bufferView": add_view(values), "componentType": 5126, "count": 2,
                          "type": "VEC3", "min": [0, 0, 0], "max": [0, 0, 0]})
        gltf_animations.append({"name": f"anim{a}", "samplers": [
            {"input": time_accessor, "output": value_accessor, "interpolation": "LINEAR"}],
            "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}]})

    gltf = {
        "asset": {"version": "2.0", "generator": "tests/py/test_blender_import_check.py"},
        "scene": 0,
        "scenes": [{"nodes": list(range(meshes))}],
        "nodes": [{"mesh": i, "name": (node_names or {}).get(i, f"node{i}")} for i in range(meshes)],
        "meshes": gltf_meshes,
        "materials": [{"name": "mat", "pbrMetallicRoughness": {"baseColorFactor": [0.7, 0.7, 0.7, 1.0]}}]
        if meshes else [],
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": bin_len}],
        "animations": gltf_animations,
    }
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_chunk = json_bytes + b" " * _pad4(len(json_bytes))
    bin_blob = b"".join(bin_parts)
    bin_chunk = bin_blob + b"\x00" * _pad4(len(bin_blob))
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    return (struct.pack("<III", MAGIC, 2, total)
            + struct.pack("<II", len(json_chunk), JSON_CHUNK) + json_chunk
            + struct.pack("<II", len(bin_chunk), BIN_CHUNK) + bin_chunk)


def glb_json(path):
    data = Path(path).read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20:20 + length].decode("utf-8"))


def run_blender(*args):
    return subprocess.run(
        ["blender", "-b", "--factory-startup", "--python", str(SCRIPT), "--", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )


def test_parser_reads_the_documented_flags():
    args = build_parser().parse_args(["--glbs", "a.glb,b.glb", "--report", "r.json",
                                      "--render", "v.png", "--layout", "l.json", "--width", "640"])
    assert args.glbs == "a.glb,b.glb"
    assert args.report == "r.json"
    assert args.render == "v.png"
    assert args.layout == "l.json"
    assert (args.width, args.height) == (640, 1080)
    assert args.render_parts is None


def test_parts_path_replaces_eevee_and_falls_back():
    assert parts_path_for("/out/blender_village_eevee.png") == "/out/blender_village_parts.png"
    assert parts_path_for("/out/village.png") == "/out/village_parts.png"


def test_split_glbs_skips_blanks():
    assert split_glbs("a.glb, b.glb ,,c.glb") == ["a.glb", "b.glb", "c.glb"]
    assert split_glbs("") == []


def test_sanitize_glb_copy_renames_a_crashing_name(tmp_path):
    # A long fractional name makes Blender 5.2 abort; the copy must have it made safe, geometry untouched.
    crash = tmp_path / "crash.glb"
    crash.write_bytes(tiny_glb(meshes=2, animations=0, node_names={0: "plank_0.020000000000000018"}))
    copy, renamed = sanitize_glb_copy(str(crash), str(tmp_path), "0")
    assert renamed == 1
    assert Path(copy) != crash and Path(copy).exists()
    assert glb_json(copy)["nodes"][0]["name"] == "plank_0.02"
    assert glb_json(crash)["nodes"][0]["name"] == "plank_0.020000000000000018"
    assert len(glb_json(copy)["meshes"]) == 2  # geometry (meshes) unchanged


def test_sanitize_glb_copy_keeps_a_clean_glb_unchanged(tmp_path):
    clean = tmp_path / "clean.glb"
    clean.write_bytes(tiny_glb(meshes=2, animations=0))
    copy, renamed = sanitize_glb_copy(str(clean), str(tmp_path), "1")
    assert renamed == 0
    assert Path(copy).read_bytes() == clean.read_bytes()  # byte-identical copy


def test_a_crashed_worker_is_reported_with_the_signal(tmp_path, monkeypatch):
    # No report file and a negative exit status: the row must name the signal, never hide the crash.
    monkeypatch.setattr(blender_import_check, "_run_worker",
                        lambda cmd: (-6, "", "libc++abi: terminating: std::out_of_range: stoi: out of range"))
    row = blender_import_check._worker_row("safe.glb", "orig.glb", str(SCRIPT), str(tmp_path), 0)
    assert row["ok"] is False
    assert row["file"] == "orig.glb"
    assert "signal 6" in row["error"]
    assert "stoi" in row["error"]


@pytest.mark.skipif(BLENDER is None, reason="blender is not on PATH; the import proof is skipped")
def test_import_reports_two_meshes_and_one_action(tmp_path):
    glb = tmp_path / "tiny.glb"
    glb.write_bytes(tiny_glb(meshes=2, animations=1))
    report_path = tmp_path / "report.json"

    res = run_blender("--glbs", str(glb), "--report", str(report_path))
    assert res.returncode == 0, res.stderr

    report = json.loads(report_path.read_text())
    assert report["totals"]["count"] == 1 and report["totals"]["ok"] == 1
    row = report["glbs"][0]
    assert row["ok"] is True, row
    assert row["meshes"] == 2
    assert row["actions"] == 1
    assert row["triangles"] == 24
    assert row["materials"] >= 1
    assert row["raw_names_crash_risk"] is False


@pytest.mark.skipif(BLENDER is None, reason="blender is not on PATH; the import proof is skipped")
def test_a_broken_glb_is_reported_not_hidden(tmp_path):
    broken = tmp_path / "broken.glb"
    broken.write_bytes(b"this is not a glb file")
    report_path = tmp_path / "report.json"

    res = run_blender("--glbs", str(broken), "--report", str(report_path))
    # The bad file is a row with an error; the script still writes its report.
    report = json.loads(report_path.read_text())
    assert report["totals"]["failed"] == 1
    row = report["glbs"][0]
    assert row["ok"] is False
    assert row["error"]
    assert row["raw_names_crash_risk"] is False


@pytest.mark.skipif(BLENDER is None, reason="blender is not on PATH; the import proof is skipped")
def test_a_name_crash_glb_imports_from_a_sanitized_copy(tmp_path):
    # Blender 5.2 aborts on a node name whose fraction has ten or more digits; the driver imports a
    # name-safe copy instead, so this becomes an ok row flagged with raw_names_crash_risk, beside the good one.
    good = tmp_path / "good.glb"
    good.write_bytes(tiny_glb(meshes=2, animations=0))
    crash = tmp_path / "crash.glb"
    crash.write_bytes(tiny_glb(meshes=2, animations=0, node_names={0: "plank_0.020000000000000018"}))
    report_path = tmp_path / "report.json"

    res = run_blender("--glbs", f"{good},{crash}", "--report", str(report_path))
    assert res.returncode == 0, res.stderr

    report = json.loads(report_path.read_text())
    assert report["totals"] == {"count": 2, "ok": 2, "failed": 0, "triangles": 48}
    by_file = {row["file"]: row for row in report["glbs"]}
    assert by_file[str(good)]["ok"] is True
    assert by_file[str(good)]["raw_names_crash_risk"] is False
    assert by_file[str(crash)]["ok"] is True
    assert by_file[str(crash)]["raw_names_crash_risk"] is True


@pytest.mark.skipif(BLENDER is None, reason="blender is not on PATH; the import proof is skipped")
def test_render_writes_both_images_at_the_stated_size(tmp_path):
    glb = tmp_path / "tiny.glb"
    glb.write_bytes(tiny_glb(meshes=2, animations=0))
    (tmp_path / "scene.json").write_text(json.dumps({
        "plinth": {"shape": "round", "size_m": 10, "top": "0x9ccf7a", "side": "0x8a5a3c"},
        "camera": {"yaw": 30, "pitch": 28, "fov": 30, "zoom": 2},
        "items": [{"id": "a", "glb": str(glb), "x": 0, "z": 0, "rot_y_deg": 0}],
    }))

    report_path = tmp_path / "report.json"
    render = tmp_path / "blender_village_eevee.png"
    res = run_blender("--glbs", str(glb), "--report", str(report_path),
                      "--render", str(render), "--layout", str(tmp_path / "scene.json"),
                      "--width", "320", "--height", "180")
    assert res.returncode == 0, res.stderr

    parts = tmp_path / "blender_village_parts.png"
    assert render.exists() and parts.exists()
    for image in (render, parts):
        width, height = struct.unpack(">II", image.read_bytes()[16:24])  # PNG IHDR
        assert (width, height) == (320, 180)
