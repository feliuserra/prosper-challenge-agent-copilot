import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from composer_api import make_router


@pytest.fixture
def agents_dir(tmp_path, agent):
    (tmp_path / "prosper-scheduler.json").write_text(json.dumps(agent))
    return tmp_path


@pytest.fixture
def client(agents_dir):
    app = FastAPI()
    app.include_router(make_router(agents_dir))
    return TestClient(app)


def test_list_agents(client):
    assert client.get("/composer/agents").json() == {
        "agents": [{"id": "prosper-scheduler", "name": "Prosper Scheduler"}]
    }


def test_get_agent(client, agent):
    assert client.get("/composer/agents/prosper-scheduler").json() == agent


def test_get_missing_agent(client):
    assert client.get("/composer/agents/nope").status_code == 404


def test_save_round_trips_unknown_keys(client, agent, agents_dir):
    agent["nodes"][0]["ui"] = {"x": 1.5, "y": -2}
    agent["notes"] = "kept"
    response = client.put("/composer/agents/copy", json=agent)
    assert response.status_code == 200
    assert response.json() == {"id": "copy", "name": "Prosper Scheduler"}
    assert client.get("/composer/agents/copy").json() == agent
    assert not list(agents_dir.glob("*.tmp"))  # no temp files left behind


def test_save_invalid_agent_returns_422_with_every_error(client, agent, agents_dir):
    del agent["name"]
    agent["nodes"][0]["edges"][0]["target"] = "missing"
    response = client.put("/composer/agents/prosper-scheduler", json=agent)
    assert response.status_code == 422
    assert response.json()["errors"] == [
        {"message": "Agent needs a name.", "node": None, "edge": None},
        {
            "message": "Edge targets unknown node 'missing'.",
            "node": "greeting",
            "edge": "choose_intent",
        },
    ]
    # The file on disk is untouched.
    assert json.loads((agents_dir / "prosper-scheduler.json").read_text())["name"] == "Prosper Scheduler"


@pytest.mark.parametrize("agent_id", ["..", "..%2Fsecrets", "Upper", "has space", "-lead", "a" * 65])
def test_agent_ids_are_sanitised(client, agent, agent_id):
    assert client.put(f"/composer/agents/{agent_id}", json=agent).status_code in (400, 404)
    assert client.get(f"/composer/agents/{agent_id}").status_code in (400, 404)


def test_validate(client, agent):
    assert client.post("/composer/validate", json=agent).json() == {"errors": []}
    agent["initial_node"] = "nowhere"
    response = client.post("/composer/validate", json=agent)
    assert response.status_code == 200
    assert response.json()["errors"][0]["message"] == "initial_node 'nowhere' is not a defined node."


def test_health_lists_missing_keys(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert client.get("/composer/health").json() == {
        "ok": False,
        "missing_keys": ["ELEVENLABS_API_KEY"],
    }
    monkeypatch.setenv("ELEVENLABS_API_KEY", "y")
    assert client.get("/composer/health").json() == {"ok": True, "missing_keys": []}
