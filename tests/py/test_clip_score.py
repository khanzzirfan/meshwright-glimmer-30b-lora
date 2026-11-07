import importlib
import math
import re
import sys
from pathlib import Path

import pytest

from clip_score import (
    ClipEmbedder,
    cosine,
    mesh_score,
    recall_at,
    retrieval_ranks,
    score_folder,
)


def _vec_from(text, dim=16):
    """A deterministic unit vector built from the words of a string."""
    vec = [0.0] * dim
    for word in re.findall(r"[a-z0-9]+", str(text).lower()):
        vec[sum(word.encode()) % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


class FakeEmbedder:
    """Image vectors come from the view's parent folder name, text vectors from the caption.

    So an item whose name equals its caption scores 100, without any model.
    """

    def __init__(self, dim=16):
        self.dim = dim
        self.image_calls = []
        self.text_calls = []

    def images(self, paths):
        self.image_calls.append([str(path) for path in paths])
        return [_vec_from(Path(path).parent.name, self.dim) for path in paths]

    def text(self, captions):
        self.text_calls.append([str(caption) for caption in captions])
        return [_vec_from(caption, self.dim) for caption in captions]


def _make_views(root, name, n):
    (root / name).mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (root / name / f"view{i}.png").write_bytes(b"png")


def test_cosine_identical_orthogonal_and_zero():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_ignores_magnitude():
    assert cosine([2.0, 0.0], [5.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 1.0], [1.0, 1.0]) == pytest.approx(1.0)


def test_mesh_score_is_mean_cosine_times_100():
    views = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
    text = [1.0, 0.0]
    expected = sum(cosine(view, text) for view in views) / len(views) * 100
    assert mesh_score(views, text) == pytest.approx(expected)
    assert mesh_score([[1.0, 0.0]], [1.0, 0.0]) == pytest.approx(100.0)
    assert mesh_score([[0.0, 1.0]], [1.0, 0.0]) == pytest.approx(0.0)


def test_mesh_score_with_no_views_is_zero():
    assert mesh_score([], [1.0, 0.0]) == 0.0


def test_retrieval_ranks_hand_made_matrix():
    matrix = [
        [0.9, 0.1, 0.1],
        [0.5, 0.8, 0.5],
        [0.2, 0.2, 0.7],
    ]
    assert retrieval_ranks(matrix) == [1, 1, 1]


def test_retrieval_ranks_tie_ranks_true_caption_below_the_tied_one():
    # mesh 0's true caption scores 0.5, tied with caption 1, so the true caption lands at rank 2
    matrix = [
        [0.5, 0.5, 0.1],
        [0.1, 0.7, 0.2],
        [0.1, 0.2, 0.6],
    ]
    assert retrieval_ranks(matrix)[0] == 2
    assert retrieval_ranks(matrix) == [2, 1, 1]


def test_retrieval_ranks_worst_caption_is_last():
    assert retrieval_ranks([[0.1, 0.9, 0.9]]) == [3]


def test_recall_at_counts_ranks_within_k():
    assert recall_at([1, 2, 3, 4], 1) == pytest.approx(0.25)
    assert recall_at([1, 2, 3, 4], 2) == pytest.approx(0.5)
    assert recall_at([1, 2, 3, 4], 5) == pytest.approx(1.0)
    assert recall_at([], 1) == 0.0


def test_score_folder_scores_present_items_and_skips_a_missing_name(tmp_path):
    views = tmp_path / "views"
    for name in ("cat", "dog"):
        _make_views(views, name, 2)
    items = [
        {"name": "cat", "caption": "cat"},
        {"name": "dog", "caption": "dog"},
        {"name": "fox", "caption": "fox"},
    ]
    embedder = FakeEmbedder()
    scores = score_folder(views, items, embedder, views=2)

    assert set(scores) == {"cat", "dog"}
    assert "fox" not in scores
    assert scores["cat"] == pytest.approx(100.0)
    assert scores["dog"] == pytest.approx(100.0)
    assert embedder.image_calls == [[
        str(views / "cat" / "view0.png"),
        str(views / "cat" / "view1.png"),
        str(views / "dog" / "view0.png"),
        str(views / "dog" / "view1.png"),
    ]]
    assert embedder.text_calls == [["cat", "dog"]]


def test_score_folder_skips_an_item_with_only_some_views(tmp_path):
    views = tmp_path / "views"
    _make_views(views, "full", 3)
    _make_views(views, "partial", 1)
    items = [
        {"name": "full", "caption": "full"},
        {"name": "partial", "caption": "partial"},
    ]
    scores = score_folder(views, items, FakeEmbedder(), views=3)
    assert set(scores) == {"full"}


def test_score_folder_with_nothing_rendered_returns_empty_and_embeds_nothing(tmp_path):
    embedder = FakeEmbedder()
    assert score_folder(tmp_path, [{"name": "x", "caption": "x"}], embedder, views=1) == {}
    assert embedder.image_calls == []
    assert embedder.text_calls == []


def test_importing_clip_score_does_not_import_torch_or_transformers():
    sys.modules.pop("torch", None)
    sys.modules.pop("transformers", None)
    import clip_score

    importlib.reload(clip_score)

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules
    assert callable(clip_score.ClipEmbedder)


def test_clip_embedder_without_torch_raises_runtime_error_naming_the_install(monkeypatch):
    import clip_score

    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.delitem(sys.modules, "transformers", raising=False)
    embedder = clip_score.ClipEmbedder()

    with pytest.raises(RuntimeError) as text_error:
        embedder.text(["a red chair"])
    assert "pip install torch pillow" in str(text_error.value)

    with pytest.raises(RuntimeError) as image_error:
        embedder.images(["view0.png"])
    assert "pip install torch pillow" in str(image_error.value)
