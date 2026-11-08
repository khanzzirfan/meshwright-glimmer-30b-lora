"""Keep docs/14's one-command generator section in step with the imp-4 evidence and the maps.

The section states the imp-ops-3 numbers and the no-blind-rating caveat, and README.md, INDEX.md,
NEXT-STEPS.md and ralph/README.md all name scripts/glb_generate.py (the imp-4 PRD).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "14-glb-improvement.md"
SCRIPT = "scripts/glb_generate.py"

# The imp-ops-3 evidence (fresh seeds 4-6, the 48 eval briefs), as the section reports it.
NUMBERS = ["100%", "93.8%", "1.375", "84.5"]


def section(text, number):
    """One ``## <number>.`` section, up to the next numbered section."""
    match = re.search(rf"(?m)^## {number}\.", text)
    if not match:
        raise AssertionError(f"docs/14 section {number} not found")
    rest = text[match.end():]
    following = re.search(r"(?m)^##\s+\d+\.", rest)
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def test_doc_has_a_one_command_generator_section():
    assert "One-command generator" in DOC.read_text()


def test_generator_section_states_the_numbers_and_the_caveat():
    text = section(DOC.read_text(), 11)
    for number in NUMBERS:
        assert number in text, f"docs/14 section 11 does not state {number}"
    assert "seeds 4-6" in text
    assert "no blind rating" in text
    assert "assembled is the ranking key" in text.lower()


def test_generator_script_exists_and_is_named_by_path():
    assert (ROOT / SCRIPT).exists(), f"{SCRIPT} does not exist"
    assert SCRIPT in DOC.read_text(), f"docs/14 does not name {SCRIPT}"


def test_generator_is_listed_in_the_readme_and_index():
    assert SCRIPT in (ROOT / "README.md").read_text(), "README.md does not list the generator"
    assert SCRIPT in (ROOT / "INDEX.md").read_text(), "INDEX.md does not list the generator"


def test_generator_and_imp4_are_wired_into_the_maps():
    next_steps = (ROOT / "NEXT-STEPS.md").read_text()
    ralph_readme = (ROOT / "ralph" / "README.md").read_text()
    assert SCRIPT in next_steps, "NEXT-STEPS.md does not list the generator"
    assert "imp-4" in next_steps, "NEXT-STEPS.md does not name imp-4"
    assert SCRIPT in ralph_readme, "ralph/README.md does not list the generator"
    assert "imp-4" in ralph_readme, "ralph/README.md does not name imp-4"
