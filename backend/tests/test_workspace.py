import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import simfakes
import storage
from composer_api import make_router as make_agents_router
from copilot.api import make_router
from copilot.workspace import EMPTY_SPEC, Workspace, agent_hash
from detect.summary import from_sim_record
from sim.replay import agent_turn
from sim.runner import simulate


@pytest.fixture
def ws(tmp_path):
    return Workspace("prosper-scheduler", tmp_path)


# ---- the store --------------------------------------------------------------------------
def test_a_missing_workspace_reads_empty_and_creates_nothing(ws, tmp_path):
    assert ws.guidelines() == ""
    assert ws.spec() == EMPTY_SPEC and ws.spec() is not EMPTY_SPEC
    assert ws.versions() == [] and ws.version(1) is None and ws.version_of({"name": "x"}) is None
    assert ws.last_run() is None and ws.last_proposal() is None
    assert ws.calls() == [] and ws.call("nope") is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("agent_id", ["..", "../x", "Upper", "has space", "-lead", "a" * 65, ""])
def test_ids_are_sanitised(tmp_path, agent_id):
    with pytest.raises(ValueError):
        Workspace(agent_id, tmp_path)


def test_guidelines_and_spec_round_trip(ws):
    ws.save_guidelines("Linden Grove Family Practice\n\nWe open at 8.\n")
    ws.save_spec({**EMPTY_SPEC, "requirements": [{"id": "R1", "text": "Greet the caller."}]})
    assert ws.guidelines() == "Linden Grove Family Practice\n\nWe open at 8.\n"
    assert ws.spec()["requirements"] == [{"id": "R1", "text": "Greet the caller."}]


def test_a_failed_write_keeps_the_old_file_and_leaves_no_temp_file(ws, monkeypatch):
    ws.save_guidelines("old")

    def broken_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(storage.os, "replace", broken_replace)
    with pytest.raises(OSError):
        ws.save_guidelines("new")
    assert ws.guidelines() == "old"
    assert [p.name for p in ws.dir.iterdir()] == ["guidelines.md"]


# ---- versions ---------------------------------------------------------------------------
def test_saving_an_unchanged_agent_adds_no_version(ws, example):
    first, added = ws.add_version(example, "editor")
    assert added and first["number"] == 1 and first["source"] == "editor" and "agent" not in first
    again, added = ws.add_version(example, "editor")
    assert not added and again == first
    assert [v["number"] for v in ws.versions()] == [1]


def test_moving_cards_or_stages_adds_no_version(ws, example):
    ws.add_version(example, "editor")
    example["nodes"][0]["ui"] = {"x": 120, "y": -40}
    example["nodes"][0]["stage"] = "Somewhere else"
    _, added = ws.add_version(example, "editor")
    assert not added


def test_a_changed_prompt_adds_a_version(ws, example):
    ws.add_version(example, "editor")
    changed = json.loads(json.dumps(example))
    changed["nodes"][0]["task_messages"][0]["content"] += " Be brief."
    summary, added = ws.add_version(changed, "copilot", "Accepted: shorter greeting")
    assert added and summary["number"] == 2 and summary["source"] == "copilot"
    assert summary["message"] == "Accepted: shorter greeting"
    assert ws.version(2)["agent"] == changed and ws.version(1)["agent"] == example
    assert [v["number"] for v in ws.versions()] == [1, 2]
    assert sorted(p.name for p in (ws.dir / "versions").iterdir()) == ["0001.json", "0002.json"]


def test_reverting_adds_a_version_and_version_of_finds_the_newest_match(ws, example):
    changed = json.loads(json.dumps(example))
    changed["persona"] = "Terse."
    ws.add_version(example, "editor")
    ws.add_version(changed, "editor")
    _, added = ws.add_version(example, "editor")
    assert added  # history, not deduplication: only the newest version is compared
    assert ws.version_of(example) == 3 and ws.version_of(changed) == 2
    assert ws.version_of({**example, "persona": "Unsaved."}) is None


def test_an_unknown_version_source_is_refused(ws, example):
    with pytest.raises(ValueError):
        ws.add_version(example, "someone")


def test_the_hash_ignores_layout_only(example):
    moved = json.loads(json.dumps(example))
    moved["nodes"][0]["ui"] = {"x": 1, "y": 2}
    assert agent_hash(moved) == agent_hash(example)
    assert agent_hash({**example, "persona": "Different."}) != agent_hash(example)


# ---- runs and proposals -----------------------------------------------------------------
def test_the_newest_run_and_proposal_are_the_last(ws):
    assert ws.save_run({"results": "first"}) == 1
    assert ws.save_run({"results": "second"}) == 2
    assert ws.last_run() == {"results": "second"}
    assert ws.save_proposal({"rationale": "only"}) == 1
    assert ws.last_proposal() == {"rationale": "only"}


# ---- call records -----------------------------------------------------------------------
@pytest.fixture
def booking(example):
    """A real runner record: the scripted booking at Riverside."""
    models = simfakes.models(agent=simfakes.BOOKING_AGENT, caller=simfakes.BOOKING_CALLER)
    return asyncio.run(simulate(example, simfakes.TEST, models))


def test_a_runner_record_reads_back_as_a_call_record(ws, example, booking):
    ws.add_version(example, "editor")
    saved = ws.save_call(booking, example, "simulated", id="sim-1", start="2026-10-12T09:00:00", end="2026-10-12T09:03:10")
    call = ws.call("sim-1")
    assert call == saved
    assert call["version"] == 1 and call["agent_hash"] == agent_hash(example) and call["agent"] == example
    assert call["source"] == "simulated" and call["turns"] == booking["turns"] and call["end_reason"] == booking["end_reason"]
    assert ws.calls() == [
        {
            "id": "sim-1",
            "source": "simulated",
            "version": 1,
            "agent_hash": agent_hash(example),
            "start": "2026-10-12T09:00:00",
            "end": "2026-10-12T09:03:10",
            "end_reason": "end_node",
        }
    ]


def test_a_call_record_works_where_a_runner_record_does(ws, example, booking):
    call = ws.save_call(booking, example, "production-mock")
    first_agent_turn = next(t["turn"] for t in call["turns"] if t["speaker"] == "agent" and "context" in t)
    assert agent_turn(call, first_agent_turn)["context"] == agent_turn(booking, first_agent_turn)["context"]
    summary = from_sim_record(call, id=call["id"], clinic="riverside", version=1, start="s", end="e", caller="+1")
    assert summary["ended"] == "completed" and summary["path"][0][0] == booking["start_node"]


def test_a_call_from_an_unsaved_draft_has_no_version(ws, example, booking):
    call = ws.save_call(booking, example, "live")
    assert call["version"] is None
    assert call["id"].startswith("live-")


def test_call_sources_and_ids_are_checked(ws, example, booking):
    with pytest.raises(ValueError):
        ws.save_call(booking, example, "phone")
    with pytest.raises(ValueError):
        ws.save_call(booking, example, "live", id="../escape")
    assert ws.call("../escape") is None


# ---- the API ----------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, agent):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "prosper-scheduler.json").write_text(json.dumps(agent))
    app = FastAPI()
    app.include_router(make_agents_router(agents_dir, workspaces_dir=tmp_path / "workspaces"))
    app.include_router(make_router(tmp_path / "workspaces"))
    return TestClient(app)


def test_api_guidelines_round_trip(client):
    assert client.get("/copilot/workspaces/prosper-scheduler/guidelines").json() == {"text": ""}
    assert client.put("/copilot/workspaces/prosper-scheduler/guidelines", json={"text": "Open at 8."}).status_code == 200
    assert client.get("/copilot/workspaces/prosper-scheduler/guidelines").json() == {"text": "Open at 8."}


def test_api_spec_of_a_missing_workspace_is_empty(client):
    assert client.get("/copilot/workspaces/prosper-scheduler/spec").json() == {**EMPTY_SPEC, "gaps": {"uncarried": [], "untested": []}}


def test_api_saves_from_the_editor_add_versions(client, agent):
    assert client.put("/composer/agents/prosper-scheduler", json=agent).json()["version"] == 1
    assert client.put("/composer/agents/prosper-scheduler", json=agent).json()["version"] == 1
    agent["nodes"][0]["ui"] = {"x": 5, "y": 5}
    assert client.put("/composer/agents/prosper-scheduler", json=agent).json()["version"] == 1
    agent["persona"] = "Warm and brief."
    assert client.put("/composer/agents/prosper-scheduler", json=agent).json()["version"] == 2
    versions = client.get("/copilot/workspaces/prosper-scheduler/versions").json()["versions"]
    assert [(v["number"], v["source"]) for v in versions] == [(1, "editor"), (2, "editor")]
    assert client.get("/copilot/workspaces/prosper-scheduler/versions/2").json()["agent"] == agent


def test_api_an_invalid_save_adds_no_version(client, agent):
    del agent["name"]
    assert client.put("/composer/agents/prosper-scheduler", json=agent).status_code == 422
    assert client.get("/copilot/workspaces/prosper-scheduler/versions").json() == {"versions": []}


@pytest.mark.parametrize("number", [0, 1, 99])
def test_api_missing_versions_are_404(client, number):
    assert client.get(f"/copilot/workspaces/prosper-scheduler/versions/{number}").status_code == 404


@pytest.mark.parametrize("agent_id", ["Upper", "has%20space", "-lead", "a" * 65])
def test_api_ids_are_sanitised(client, agent_id):
    assert client.get(f"/copilot/workspaces/{agent_id}/guidelines").status_code == 400
    assert client.put(f"/copilot/workspaces/{agent_id}/guidelines", json={"text": "x"}).status_code == 400
