import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clinic import clinics as clinics_module
from clinic import load_seed
from composer_api import VoiceListError, http_error_message, make_router


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


def voices_client(agents_dir, fetch_voices):
    app = FastAPI()
    app.include_router(make_router(agents_dir, fetch_voices=fetch_voices))
    return TestClient(app)


def test_voices_are_fetched_once_with_the_key(agents_dir, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    calls = []

    async def fetch(api_key):
        calls.append(api_key)
        return [{"id": "v1", "name": "Voice One", "category": "premade"}]

    client = voices_client(agents_dir, fetch)
    expected = {"voices": [{"id": "v1", "name": "Voice One", "category": "premade"}]}
    assert client.get("/composer/voices").json() == expected
    assert client.get("/composer/voices").json() == expected
    assert calls == ["test-key"]


def test_voices_without_a_key(agents_dir, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    async def fetch(api_key):
        raise AssertionError("must not be called without a key")

    body = voices_client(agents_dir, fetch).get("/composer/voices").json()
    assert body["voices"] == [] and "ELEVENLABS_API_KEY" in body["error"]


def test_voices_failure_is_reported_and_retried(agents_dir, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    results = [RuntimeError("down"), [{"id": "v1", "name": "Voice One", "category": None}]]

    async def fetch(api_key):
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    client = voices_client(agents_dir, fetch)
    first = client.get("/composer/voices").json()
    assert first["voices"] == [] and first["error"]
    assert client.get("/composer/voices").json()["voices"][0]["id"] == "v1"


def test_voices_error_message_comes_from_status_and_body_only(agents_dir, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "secret-key")
    body = json.dumps({"detail": {"status": "missing_permissions", "message": "Missing voices_read."}})

    async def fetch(api_key):
        raise VoiceListError(http_error_message(401, body))

    error = voices_client(agents_dir, fetch).get("/composer/voices").json()["error"]
    assert error == "ElevenLabs answered HTTP 401: Missing voices_read."
    assert http_error_message(500, "not json") == "ElevenLabs answered HTTP 500."


def test_unexpected_voice_errors_report_only_the_type(agents_dir, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "secret-key")

    async def fetch(api_key):
        raise RuntimeError(f"headers: xi-api-key={api_key}")

    error = voices_client(agents_dir, fetch).get("/composer/voices").json()["error"]
    assert "secret-key" not in error and "RuntimeError" in error


def test_tools_catalog(client):
    tools = client.get("/composer/tools").json()["tools"]
    assert [t["name"] for t in tools][:3] == ["lookup_patient", "register_patient", "list_appointment_types"]
    assert tools[0]["required"] == ["full_name", "date_of_birth"]
    assert "date_of_birth" in tools[0]["properties"]


@pytest.fixture
def clinics_dir(tmp_path, monkeypatch):
    """Riverside, a clinic with two configuration errors and a file that is not JSON."""
    folder = tmp_path / "clinics"
    folder.mkdir()
    riverside = load_seed("riverside")
    (folder / "riverside.json").write_text(json.dumps(riverside))
    broken = {**riverside, "clinic": {**riverside["clinic"], "name": "Broken Clinic"}}
    broken["insurance_plans"] = [{"id": "aetna-hmo", "name": "Aetna HMO", "covers": ["dental"]}]
    broken["cancellation"] = {"window_hours": 24, "fee": -5}
    (folder / "broken.json").write_text(json.dumps(broken))
    (folder / "garbled.json").write_text("{not json")
    monkeypatch.setattr(clinics_module, "CLINICS_DIR", folder)
    return folder


def test_list_clinics(client, clinics_dir):
    assert client.get("/composer/clinics").json() == {
        "clinics": [
            {"id": "broken", "name": "Broken Clinic"},
            {"id": "garbled", "name": None},
            {"id": "riverside", "name": "Riverside Family Clinic"},
        ]
    }


def test_get_clinic_returns_the_file_and_no_problems(client, clinics_dir):
    body = client.get("/composer/clinics/riverside").json()
    assert body["id"] == "riverside"
    assert body["clinic"] == json.loads((clinics_dir / "riverside.json").read_text())
    assert body["problems"] == []


def test_get_clinic_lists_the_loader_problems_with_their_path(client, clinics_dir):
    body = client.get("/composer/clinics/broken").json()
    assert body["clinic"]["clinic"]["name"] == "Broken Clinic"
    assert body["problems"] == [
        {"path": "insurance_plans[0].covers[0]", "message": "Unknown appointment type 'dental'."},
        {"path": "cancellation.fee", "message": "Must be a number of 0 or more."},
    ]


def test_get_clinic_that_is_not_json(client, clinics_dir):
    body = client.get("/composer/clinics/garbled").json()
    assert body["clinic"] is None
    assert body["problems"][0]["path"] == ""
    assert body["problems"][0]["message"].startswith("Not valid JSON")


@pytest.mark.parametrize("clinic_id", ["nowhere", "..", "Riverside"])
def test_get_unknown_clinic(client, clinics_dir, clinic_id):
    assert client.get(f"/composer/clinics/{clinic_id}").status_code == 404
