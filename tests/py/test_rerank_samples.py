import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import mesh_validate
from rerank_samples import load_jsonl, prepare, score

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "rerank_samples.py"


def onehot(index, dim=8):
    vec = [0.0] * dim
    vec[index] = 1.0
    return vec


class FakeEmbedder:
    """Image vectors come from the candidate's folder name, text vectors from the caption.

    Any name or caption not in the maps becomes a zero vector, so its cosine is 0.
    """

    def __init__(self, image_vecs, text_vecs, dim=8):
        self.image_vecs = image_vecs
        self.text_vecs = text_vecs
        self.dim = dim
        self.image_calls = []
        self.text_calls = []

    def images(self, paths):
        self.image_calls.append([str(path) for path in paths])
        return [self.image_vecs.get(Path(path).parent.name, [0.0] * self.dim) for path in paths]

    def text(self, captions):
        self.text_calls.append([str(caption) for caption in captions])
        return [self.text_vecs.get(caption, [0.0] * self.dim) for caption in captions]


def _make_views(views_dir, names, n=4):
    for name in names:
        folder = views_dir / name
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (folder / f"view{i}.png").write_bytes(b"png")


def test_prepare_keeps_only_valid_answers_and_counts_them(fixtures, tmp_path):
    out = tmp_path / "out"
    candidates, prompts = prepare(fixtures / "local" / "samples.jsonl", out)

    names = [c["name"] for c in candidates]
    assert names == ["p000_0", "p000_1", "p000_2", "p001_0", "p001_1"]
    assert all(re.match(r"^p\d{3}_\d+$", name) for name in names)
    assert [p["n_valid"] for p in prompts] == [3, 2, 0]

    written = json.loads((out / "prompts.json").read_text())
    assert written == prompts
    for candidate in load_jsonl(out / "candidates.jsonl"):
        assert candidate["name"] in names
        assert mesh_validate.validate(candidate["text"])[0] is True


def test_score_clip_pick_can_differ_from_the_medoid_pick(fixtures, tmp_path):
    out = tmp_path / "out"
    prepare(fixtures / "local" / "samples.jsonl", out)
    views = tmp_path / "views"
    _make_views(views, ["p000_0", "p000_1", "p000_2", "p001_0", "p001_1"])

    embedder = FakeEmbedder(
        image_vecs={"p000_0": onehot(3), "p000_1": onehot(4), "p000_2": onehot(0),
                    "p001_0": onehot(5), "p001_1": onehot(6)},
        text_vecs={"a green apple": onehot(0), "a blue chair": onehot(1), "a red car": onehot(2)},
    )
    report = score(out, views, embedder=embedder)

    for rule in ("first", "medoid", "clip"):
        assert {"valid", "mean_clip", "r_at_1", "r_at_5"} <= set(report[rule])

    assert report["n_prompts"] == 3
    assert report["clip"]["valid"] == 2
    assert report["medoid"]["valid"] == 2
    assert report["first"]["valid"] == 2

    assert report["picks"]["clip"]["p000"] == "p000_2"
    assert report["picks"]["medoid"]["p000"] == "p000_0"
    assert report["picks"]["clip"]["p000"] != report["picks"]["medoid"]["p000"]

    assert report["clip"]["mean_clip"] == pytest.approx(50.0)
    assert report["medoid"]["mean_clip"] == pytest.approx(0.0)
    assert report["clip"]["r_at_1"] == pytest.approx(1 / 3, abs=1e-3)
    assert report["medoid"]["r_at_1"] == pytest.approx(0.0)
    assert report["clip"]["r_at_5"] == pytest.approx(1.0)

    assert json.loads((out / "rerank_report.json").read_text())["clip"] == report["clip"]
    assert (out / "rerank_report.md").exists()
    assert [r["name"] for r in load_jsonl(out / "sheet_clip.jsonl")] == ["p000_2", "p001_0"]
    assert [r["name"] for r in load_jsonl(out / "sheet_medoid.jsonl")] == ["p000_0", "p001_0"]


def test_miss_lowers_valid_for_every_rule(fixtures, tmp_path):
    out = tmp_path / "out"
    prepare(fixtures / "local" / "samples.jsonl", out)
    views = tmp_path / "views"
    _make_views(views, ["p000_0", "p000_1", "p000_2", "p001_0", "p001_1"])
    report = score(out, views, embedder=FakeEmbedder(
        image_vecs={name: onehot(0) for name in
                    ["p000_0", "p000_1", "p000_2", "p001_0", "p001_1"]},
        text_vecs={"a green apple": onehot(0), "a blue chair": onehot(1), "a red car": onehot(2)},
    ))
    for rule in ("first", "medoid", "clip"):
        assert report["picks"][rule]["p002"] is None
        assert report[rule]["valid"] == 2


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


@pytest.mark.parametrize("folder", ["data", "out", "eval"])
def test_prepare_refuses_a_protected_out_dir(fixtures, folder):
    target = ROOT / folder / "rerank-nope"
    result = _run("prepare", "--samples", str(fixtures / "local" / "samples.jsonl"),
                  "--out-dir", str(target))
    assert result.returncode != 0
    assert "refusing to write" in result.stderr
    assert not target.exists()


def test_score_refuses_a_protected_out_dir(tmp_path):
    target = ROOT / "out" / "rerank-nope"
    result = _run("score", "--out-dir", str(target), "--views-dir", str(tmp_path))
    assert result.returncode != 0
    assert "refusing to write" in result.stderr
    assert not target.exists()
