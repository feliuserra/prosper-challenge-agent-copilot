import copy
import json
from pathlib import Path

import pytest

TESTS = Path(__file__).parent
EXAMPLE = json.loads((TESTS.parent / "agents" / "prosper-scheduler.json").read_text())
# The original four-node example, frozen so the tests do not change with the example agent.
LINEAR = json.loads((TESTS / "fixtures" / "linear-agent.json").read_text())


@pytest.fixture
def agent() -> dict:
    """A fresh copy of the linear fixture agent, safe to mutate."""
    return copy.deepcopy(LINEAR)


@pytest.fixture
def example() -> dict:
    """A fresh copy of the example agent that ships in agents/."""
    return copy.deepcopy(EXAMPLE)
