import copy
import json
from pathlib import Path

import pytest

EXAMPLE = json.loads((Path(__file__).parent.parent / "agents" / "prosper-scheduler.json").read_text())


@pytest.fixture
def agent() -> dict:
    """A fresh copy of the example agent, safe to mutate."""
    return copy.deepcopy(EXAMPLE)
