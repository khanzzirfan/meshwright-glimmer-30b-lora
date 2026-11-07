import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pytest


@pytest.fixture
def fixtures():
    return ROOT / "tests" / "fixtures"
