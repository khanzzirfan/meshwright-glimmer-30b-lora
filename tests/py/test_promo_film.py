"""The launch film script (docs/15 section 7, Ralph promo-1 US-005).

``scripts/promo_film.sh`` strings the cover, the two diorama orbits, slides 2-5 (slow zoom), the turntable and
an end card into one 25-30 s 1920x1080 MP4 (plus a 1080x1080 square) with ffmpeg. These tests exercise only
``--dry-run``, so they are offline, fast and write nothing: a temp promo tree of dummy PNGs is enough. The
plan must print the nine parts in order, chain them with eight 0.4 s crossfades and never reference a network.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "promo_film.sh"

# The film's part clips, in the order the story lists them.
PARTS = [
    "01_title", "02_village_orbit", "03_slide_market", "04_slide_farmhouse",
    "05_slide_walker", "06_slide_octopus", "07_harbour_orbit", "08_turntable", "09_endcard",
]
CROSSFADES = len(PARTS) - 1


@pytest.fixture
def promo(tmp_path):
    """A temp promo tree with the dummy inputs the plan refers to."""
    for rel in ("out/slides", "scenes_out/village_orbit", "scenes_out/harbour_orbit"):
        (tmp_path / rel).mkdir(parents=True)
    (tmp_path / "out" / "cover_1280x640.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "out" / "turntable_1200.mp4").write_bytes(b"\x00\x00\x00\x18ftypisom")
    for name in ("01_world", "02_market", "03_farmhouse", "04_walker", "05_octopus", "06_harbour"):
        (tmp_path / "out" / "slides" / f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    for i in range(96):
        (tmp_path / "scenes_out" / "village_orbit" / f"{i:04d}.png").write_bytes(b"")
        (tmp_path / "scenes_out" / "harbour_orbit" / f"{i:04d}.png").write_bytes(b"")
    return tmp_path


def dry_run(promo):
    return subprocess.run(
        ["bash", str(SCRIPT), "--dry-run", "--promo", str(promo)],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )


def test_dry_run_prints_the_parts_in_order_with_crossfades(promo):
    res = dry_run(promo)
    assert res.returncode == 0, res.stderr
    out = res.stdout

    positions = [out.index(part) for part in PARTS]          # ValueError if a part is missing
    assert positions == sorted(positions), f"parts are out of order:\n{out}"

    # Eight 0.4 s crossfades chain the nine parts (one per cut).
    assert out.count("xfade=") == CROSSFADES
    assert out.count("duration=0.4") == CROSSFADES
    assert f"{CROSSFADES} crossfades of 0.4s" in out

    # The plan writes both deliverables, and a dry run must not create the output dir.
    assert "meshwright_v1_film.mp4" in out and "meshwright_v1_film_square.mp4" in out
    assert not (promo / "out" / "film").exists()


def test_dry_run_keeps_everything_local(promo):
    res = dry_run(promo)
    assert res.returncode == 0, res.stderr
    assert not re.search(r"https?://|ftp://", res.stdout), "the plan references a network URL"


def test_usage_and_bad_argument():
    good = subprocess.run(["bash", str(SCRIPT), "--help"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert good.returncode == 0 and "--dry-run" in good.stdout and "--promo" in good.stdout
    bad = subprocess.run(["bash", str(SCRIPT), "--nope"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert bad.returncode == 2 and "unknown argument" in bad.stderr
