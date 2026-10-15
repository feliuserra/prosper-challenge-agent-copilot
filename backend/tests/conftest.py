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


@pytest.fixture(autouse=True)
def no_model_calls(monkeypatch):
    """`make test` makes no model calls: without a key a real OpenAI client cannot be built,
    so a test that reached one would fail instead of spending."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def no_workspace_clinics(tmp_path_factory, monkeypatch):
    """The clinic loader also reads workspaces' clinic.json (#30): tests see none of the real ones."""
    from clinic import clinics

    monkeypatch.setattr(clinics, "WORKSPACES_DIR", tmp_path_factory.mktemp("no-workspaces"))


@pytest.fixture(scope="session")
def demo_logs():
    """The synthetic demo logs (#57): calls, records and labels. About 4 s, once per run."""
    from detect import synth

    return synth.generate()
