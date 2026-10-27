import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[2] / "fixtures" / "cases.json"


@pytest.fixture(scope="session")
def cases() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))
