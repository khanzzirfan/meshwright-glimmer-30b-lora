"""Score how well a mesh matches its caption, using CLIP on the rendered views.

This is the automatic stand-in for eyeballing "does this look like the caption":
render each mesh from a few angles (scripts/render_views.mjs), embed the images
and the captions with CLIP, and take the mean cosine between the views and the
text of the true caption. ``retrieval_ranks`` turns a mesh-by-caption score
matrix into the rank of each mesh's own caption, which is the caption-retrieval
metric the local ladder reports.

The pure helpers (``cosine``, ``mesh_score``, ``retrieval_ranks``, ``recall_at``)
have no heavy dependencies and are unit-tested with hand-made vectors.
``ClipEmbedder`` imports torch, Pillow and transformers only inside its methods
and loads the model with ``local_files_only=True``, so importing this module
works in the offline test environment. ``score_folder`` only needs any object
that implements ``images(paths)`` and ``text(captions)``, so tests (and the
rerank/eval tools) inject a fake embedder.

usage: python -c "import clip_score; print(clip_score.__doc__)"
"""
import math
from pathlib import Path

VIEW_NAME = "view{}.png"
INSTALL_HINT = ".venv/bin/pip install torch pillow"


def cosine(a, b):
    """Cosine similarity of two equal-length vectors; 0.0 if either has zero magnitude."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def mesh_score(view_vecs, text_vec):
    """Mean cosine between the caption and each rendered view, times 100."""
    if not view_vecs:
        return 0.0
    return sum(cosine(view, text_vec) for view in view_vecs) / len(view_vecs) * 100


def retrieval_ranks(score_matrix):
    """Rank of each mesh's true caption among all captions, 1-based (higher score is better).

    score_matrix[i][j] is the score of mesh i against caption j and the true
    caption of mesh i is caption i. A tie counts against the mesh: a caption
    that scores the same as the true one is ranked above it.
    """
    ranks = []
    for i, row in enumerate(score_matrix):
        true_score = row[i]
        better_or_tied = sum(1 for j, score in enumerate(row) if j != i and score >= true_score)
        ranks.append(1 + better_or_tied)
    return ranks


def recall_at(ranks, k):
    """Share of meshes whose true caption ranks at or above k."""
    if not ranks:
        return 0.0
    return sum(1 for rank in ranks if rank <= k) / len(ranks)


def _l2(vec):
    """L2-normalise one vector (a zero vector is returned unchanged)."""
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else list(vec)


def score_folder(views_dir, items, embedder, views=4):
    """Score every item whose view files all exist; skip the rest.

    items is [{name, caption}]. The images live at
    views_dir/<name>/view0.png .. view{views-1}.png. Returns {name: score}
    for the items whose views are all present; a name with any missing view is
    left out. embedder may be a ClipEmbedder or any object with
    images(paths) -> vectors and text(captions) -> vectors.
    """
    views_dir = Path(views_dir)
    present = []
    for item in items:
        paths = [views_dir / item["name"] / VIEW_NAME.format(i) for i in range(views)]
        if all(path.exists() for path in paths):
            present.append((item, paths))
    if not present:
        return {}

    flat_paths = [str(path) for _item, paths in present for path in paths]
    view_vecs = embedder.images(flat_paths)
    text_vecs = embedder.text([item["caption"] for item, _paths in present])

    scores = {}
    for index, (item, _paths) in enumerate(present):
        views_for_item = view_vecs[index * views:(index + 1) * views]
        scores[item["name"]] = mesh_score(views_for_item, text_vecs[index])
    return scores


class ClipEmbedder:
    """CLIP image and text embedder backed by transformers, loaded lazily.

    torch, Pillow and transformers are imported only when an embed with
    "images" or "text" is first requested, so importing this module (and using
    score_folder with a fake) never needs them. The checkpoint is loaded from
    the local Hugging Face cache only; download it once with the install gate.
    """

    def __init__(self, model_id="openai/clip-vit-base-patch32", batch_size=8):
        self.model_id = model_id
        self.batch_size = batch_size
        self._torch = None
        self._model = None
        self._processor = None
        self._device = None

    def _load(self):
        if self._model is not None:
            return
        try:
            import torch
            from PIL import Image
            from transformers import CLIPModel, CLIPProcessor
        except ImportError as exc:
            raise RuntimeError(
                "CLIPEmbedder needs PyTorch and Pillow; install the scorer with "
                f"`{INSTALL_HINT}` (and a matching transformers), then download "
                f"{self.model_id} to the Hugging Face cache once."
            ) from exc
        self._torch = torch
        self._Image = Image
        self._device = "mps" if torch.backends.mps.is_available() else "cpu"
        self._model = CLIPModel.from_pretrained(self.model_id, local_files_only=True).to(self._device).eval()
        self._processor = CLIPProcessor.from_pretrained(self.model_id, local_files_only=True)

    def images(self, paths):
        """L2-normalised image vectors, one per path, in order, batched."""
        self._load()
        vectors = []
        for start in range(0, len(paths), self.batch_size):
            batch = [self._Image.open(path).convert("RGB") for path in paths[start:start + self.batch_size]]
            inputs = self._processor(images=batch, return_tensors="pt").to(self._device)
            with self._torch.no_grad():
                features = self._model.get_image_features(**inputs)
            vectors.extend(_l2(row) for row in features.cpu().tolist())
        return vectors

    def text(self, captions):
        """L2-normalised text vectors, one per caption, in order."""
        self._load()
        inputs = self._processor(text=list(captions), return_tensors="pt", padding=True, truncation=True).to(self._device)
        with self._torch.no_grad():
            features = self._model.get_text_features(**inputs)
        return [_l2(row) for row in features.cpu().tolist()]
