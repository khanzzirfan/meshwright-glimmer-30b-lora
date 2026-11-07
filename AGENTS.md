# Agent notes for muse-threejs

Read ralph/README.md and INDEX.md for the project. Rules that bite:

- **Reasoning tags:** never type the literal think open or close tag in code, tests or fixtures. Tool output may hide them and you will chase a phantom diff. Import `THINK_OPEN` and `THINK_CLOSE` from `scripts/tags.py` (tests: `from tags import THINK_OPEN, THINK_CLOSE`; scripts/ is on sys.path via tests/py/conftest.py). A completion with reasoning is `THINK_OPEN + "\n" + reasoning + "\n" + THINK_CLOSE + "\n\n" + answer`.
- **Gate:** `bash scripts/check.sh` must pass before a story is done. Python is `.venv/bin/python`.
- **Never touch** `data/`, `out/`, `eval/`, `.env`, `.venv`. Tests use temp dirs and tests/fixtures.
- **No network, no commits, no long jobs.** See the guardrails in the PRD metadata.
- If you are stuck on one assertion for more than a few attempts, write down what you tried in the story `notes` and move on to the rest of the story instead of looping.
