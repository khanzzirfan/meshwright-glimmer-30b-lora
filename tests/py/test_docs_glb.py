"""Keep the docs/13 section 6 runbook in step with the scripts it names.

Every command in the fenced bash block that runs scripts/<name>.py or scripts/<name>.mjs must point at a file
that exists, and every --flag it passes must appear in that script's source.
"""
import re
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "13-glb-code-track.md"
SCRIPT_RE = re.compile(r"(?:^|/)scripts/([A-Za-z0-9_]+\.(?:py|mjs))$")


def section(text, number):
    """Return one ``## <number>.`` section, up to the next numbered section."""
    match = re.search(rf"(?m)^## {number}\.", text)
    if not match:
        raise AssertionError(f"docs/13 section {number} not found")
    rest = text[match.end():]
    following = re.search(r"(?m)^##\s+\d+\.", rest)
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def bash_block(text):
    """Return the body of the first ```bash fenced block, or fail."""
    match = re.search(r"```bash\n(.*?)```", text, re.S)
    if not match:
        raise AssertionError("docs/13 section has no ```bash block")
    return match.group(1)


def logical_commands(block):
    """Join backslash continuations and drop blank lines."""
    commands = []
    current = ""
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.endswith("\\"):
            current += line[:-1] + " "
            continue
        current += line
        commands.append(current)
        current = ""
    if current.strip():
        commands.append(current)
    return commands


def script_commands(text):
    """Yield (script token, script filename, [flags]) for every command that runs a script."""
    block = bash_block(section(text, 6))
    found = []
    for line in logical_commands(block):
        tokens = shlex.split(line, comments=True)
        for index, token in enumerate(tokens):
            match = SCRIPT_RE.search(token)
            if not match:
                continue
            flags = [t.split("=", 1)[0] for t in tokens[index + 1:] if t.startswith("--")]
            found.append((token, match.group(1), flags))
            break
    return found


def check_doc(text):
    """Return a list of problems; empty means the runbook matches the scripts."""
    errors = []
    for token, name, flags in script_commands(text):
        path = ROOT / "scripts" / name
        if not path.exists():
            errors.append(f"{token}: script does not exist")
            continue
        source = path.read_text()
        for flag in flags:
            if flag not in source:
                errors.append(f"{name}: {flag} is not in the script source")
    return errors


def test_runbook_flags_match_scripts():
    assert check_doc(DOC.read_text()) == []


def test_checker_catches_a_renamed_flag():
    text = DOC.read_text()
    block = bash_block(section(text, 6))
    changed = block.replace("--ratings", "--ratings-renamed", 1)
    assert changed != block, "section 6 no longer passes --ratings; update this test"
    errors = check_doc(text.replace(block, changed))
    assert any("--ratings-renamed" in error for error in errors), errors


def test_results_section_is_still_not_run():
    assert "not run" in section(DOC.read_text(), 10)
