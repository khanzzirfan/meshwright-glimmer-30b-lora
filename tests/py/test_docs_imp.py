"""Keep docs/14 in step with the imp-1 tools and the map that links them.

Every tool imp-1 creates is named by path, the doc keeps its 1-10 sections and section 10 stays
'not run', INDEX.md links the doc and ralph/README.md lists both imp PRDs.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "14-glb-improvement.md"

# The six tools imp-1 creates (US-002, US-004, US-005, US-006, US-007, US-008).
IMP_SCRIPTS = [
    "scripts/glb_assembly.mjs",
    "scripts/glb_repair.py",
    "scripts/glb_best_of.py",
    "scripts/ccore_prep.py",
    "scripts/imp_ops.sh",
    "scripts/glb_phase2_estimate.py",
]


def section_numbers(text):
    """Every ``## <n>.`` heading number, in file order."""
    return [m.group(1) for m in re.finditer(r"(?m)^## (\d+)\.", text)]


def section(text, number):
    """One ``## <number>.`` section, up to the next numbered section."""
    match = re.search(rf"(?m)^## {number}\.", text)
    if not match:
        raise AssertionError(f"docs/14 section {number} not found")
    rest = text[match.end():]
    following = re.search(r"(?m)^##\s+\d+\.", rest)
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def test_doc_has_sections_1_to_10():
    numbers = section_numbers(DOC.read_text())
    for n in range(1, 11):
        assert str(n) in numbers, f"docs/14 is missing section {n}"


def test_doc_names_every_new_script():
    text = DOC.read_text()
    for script in IMP_SCRIPTS:
        assert script in text, f"docs/14 does not name {script}"


def test_every_named_script_exists():
    for script in IMP_SCRIPTS:
        assert (ROOT / script).exists(), f"{script} does not exist"


def test_index_links_docs_14():
    assert "docs/14-glb-improvement.md" in (ROOT / "INDEX.md").read_text()


def test_ralph_readme_names_both_imp_prds():
    readme = (ROOT / "ralph" / "README.md").read_text()
    assert "imp-1" in readme
    assert "imp-ops" in readme


def test_results_section_is_still_not_run():
    assert "not run" in section(DOC.read_text(), 10)
