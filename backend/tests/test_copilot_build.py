import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clinic import clinic_ids, load_seed, validate_clinic
from clinic import clinics as clinics_module
from copilot import build
from copilot import config as copilot_config
from copilot import spec as spec_step
from copilot.api import make_router
from copilot.workspace import Workspace
from sim.llm import Completion, Models
from sim.runner import run_suite
from simfakes import Scripted, caller, say, verdict

BACKEND = Path(__file__).parent.parent
TEMPLATE = json.loads((BACKEND / "agents" / "prosper-scheduler.json").read_text())

CONFIGURATION = {
    "clinic": {"name": "Harbor Family Clinic", "now": "2026-10-19T08:00"},
    "providers": [
        {"id": "dr-lee", "name": "Dr. Ann Lee", "specialty": "Family medicine", "slot_minutes": 30,
         "schedule": {"mon": ["09:00-12:00"], "tue": ["09:00-12:00"]}},
    ],
    "patients": [],
    "appointments": [],
    "appointment_types": [{"id": "visit", "name": "Visit", "description": "Any visit.", "patients": "any", "providers": ["dr-lee"]}],
    "insurance_plans": [],
    "registration_fields": [],
    "booking_fields": [],
    "cancellation": {"window_hours": 24, "fee": 40},
    "facts": {"address": "We are on the harbor."},
}

PATIENT = {"id": "pat-1", "full_name": "Rosa Diaz", "date_of_birth": "1985-01-02", "phone": "555-010-2233", "last_visit": "2026-01-05"}


def make_test(id, tier, requirements, checks, facts=None, world=None) -> dict:
    test = {
        "id": id,
        "title": f"The {id} case",
        "tier": tier,
        "requirements": requirements,
        "caller": {"persona": "A caller.", "goal": "Get help.", "facts": facts or {}, "style": "Brief."},
        "max_turns": 10,
        "checks": checks,
        "status": "approved",
    }
    if world:
        test["world"] = world
    return test


def make_spec() -> dict:
    return {
        "requirements": spec_step.BASELINE + [
            {"id": "R1", "text": "Dr. Ann Lee sees patients Mondays and Tuesdays, 9 to 12.", "sources": ["x"], "baseline": False, "question": None},
            {"id": "R2", "text": "Changes inside 24 hours cost $40.", "sources": ["y"], "baseline": False, "question": None},
            {"id": "R3", "text": "New patients are told to bring a photo ID.", "sources": ["z"], "baseline": False, "question": None},
        ],
        "set_aside": [],
        "questions": [],
        "configuration": copy.deepcopy(CONFIGURATION),
        "carriers": {"configuration": {"providers.dr-lee": ["R1"], "cancellation": ["R2"]}, "nodes": {}, "persona": []},
        "tests": [
            make_test("emergency", "safety", ["B1"], [{"type": "judge", "rule": "Sends the caller to 911."}], {"full_name": "Pat Doe"}),
            make_test("photo-id", "core", ["R3"], [{"type": "judge", "rule": "Mentions the photo ID."}],
                      {"full_name": "Rosa Diaz", "date_of_birth": "January 2, 1985", "phone": "555-010-2233"}, {"patients": [PATIENT]}),
            make_test("draft-only", "core", ["R2"], [{"type": "call_ended"}]) | {"status": "draft"},
        ],
    }


# The authoring guide's check: transfer_to_human in every node that is not an end node.
TRANSFER_EVERYWHERE = [
    {"op": "set_tools", "node": n["name"], "tools": n.get("tools", []) + ["transfer_to_human"], "requirements": ["B4"]}
    for n in TEMPLATE["nodes"]
    if not n.get("end") and "transfer_to_human" not in n.get("tools", [])
]

PERSONA = TEMPLATE["persona"] + " If a caller describes an emergency, tell them to hang up and call 911 now. Give no medical advice."


def build_answer(**changes) -> dict:
    data = {
        "outline": ["Safety rules in the persona.", "Tell new patients to bring a photo ID when they register."],
        "operations": [
            {"op": "update_agent", "patch": {"persona": PERSONA}, "requirements": ["B1", "B2", "B3", "B4"]},
            {"op": "update_node", "name": "verify_patient", "patch": {"task_messages": [{"role": "developer", "content": "Look the patient up. Tell new patients to bring ID."}]}, "requirements": ["R3"]},
        ] + TRANSFER_EVERYWHERE,
        "uncarried": [],
    }
    data.update(changes)
    return data


def fix_answer(tests=("photo-id",), link="node_instruction", operations=None, configuration=(), **changes) -> dict:
    data = {
        "diagnoses": [{"test": t, "link": link, "turn": 2, "explanation": "The rule is not where the call was.", "question": None} for t in tests],
        "rationale": "Put the photo ID rule in the persona.",
        "operations": operations if operations is not None else [
            {"op": "update_agent", "patch": {"persona": PERSONA + " Remind new patients to bring a photo ID."}, "requirements": ["R3"]}
        ],
        "configuration": list(configuration),
        "concerns": [],
    }
    data.update(changes)
    return data


def answer(data: dict) -> Completion:
    return Completion(text=json.dumps(data), model="gpt-4.1-2025-04-14", input_tokens=1000, cached_tokens=200, output_tokens=300)


# ---- a fake runner: a test passes when its rule holds for the agent ------------------------------
def result(test: dict, passed: bool, cached: bool = False) -> dict:
    turns = [
        {"turn": 1, "speaker": "agent", "node": "greeting", "text": "Hello.", "calls": [],
         "context": {"system": "x", "messages": [], "tools": [{"type": "function", "function": {"name": "transfer_to_human"}}]}},
        {"turn": 2, "speaker": "caller", "text": "Hi."},
    ]
    checks = [{**c, "pass": passed, "turn": 2, "quote": None, "detail": "Held." if passed else "Did not hold."} for c in test["checks"]]
    run = {"turns": turns, "checks": checks, "passed": passed, "end_reason": "caller_hung_up"}
    return {
        "test_id": test["id"], "title": test["title"], "tier": test["tier"], "status": "pass" if passed else "fail",
        "runs": [run] if passed else [run, run], "cached": cached,
        "usage": {"fake-agent": {"requests": 4, "input": 1000, "cached": 0, "output": 100}},
    }


class Runner:
    """Runs tests by rules on the agent and clinic: {test id: rule(agent, clinic) -> passed}."""

    def __init__(self, **rules):
        self.rules = rules
        self.calls: list[list[str]] = []

    async def __call__(self, agent, tests, clinic):
        self.calls.append([t["id"] for t in tests])
        return [result(t, self.rules.get(t["id"].replace("-", "_"), lambda a, c: True)(agent, clinic)) for t in tests]


def persona_has(text):
    return lambda agent, clinic: text in agent.get("persona", "")


@pytest.fixture
def ws(tmp_path, monkeypatch) -> Workspace:
    monkeypatch.setattr(clinics_module, "WORKSPACES_DIR", tmp_path)
    ws = Workspace("harbor", tmp_path)
    ws.save_spec(make_spec())
    return ws


def run(ws, model, runner):
    events = []
    proposal = asyncio.run(build.run(ws, model, emit=events.append, run_tests=runner))
    return proposal, events


# ---- building from the template --------------------------------------------------------------
def test_the_configuration_becomes_the_agents_clinic(ws):
    assert validate_clinic(CONFIGURATION) == []
    proposal, _ = run(ws, Scripted(answer(build_answer())), Runner())
    assert (ws.dir / "clinic.json").is_file()
    assert "harbor" in clinic_ids() and load_seed("harbor") == CONFIGURATION
    assert proposal["agent"]["clinic"] == "harbor"
    assert proposal["agent"]["name"] == "Harbor Family Clinic Scheduler"


def test_a_clinic_file_wins_over_a_workspace_of_the_same_id(ws, tmp_path, monkeypatch):
    folder = tmp_path / "clinics"
    folder.mkdir()
    (folder / "harbor.json").write_text(json.dumps({**CONFIGURATION, "clinic": {"name": "The other", "now": "2026-10-19T08:00"}}))
    monkeypatch.setattr(clinics_module, "CLINICS_DIR", folder)
    build.write_clinic(ws, CONFIGURATION)
    assert load_seed("harbor")["clinic"]["name"] == "The other"


def test_operations_are_streamed_and_the_proposal_is_a_diff_on_the_template(ws):
    proposal, events = run(ws, Scripted(answer(build_answer())), Runner())
    steps = [e for e in events if e["event"] == "operation"]
    assert [e["index"] for e in steps] == list(range(2 + len(TRANSFER_EVERYWHERE)))
    assert steps[0]["agent"]["persona"] == PERSONA and steps[-1]["agent"] == proposal["agent"]
    assert proposal["status"] == "ready" and proposal["blocked"] == [] and proposal["rounds"] == []
    assert proposal["started_from"]["template"] == "prosper-scheduler"
    assert proposal["operations"] == build_answer()["operations"]
    assert proposal["configuration"] == CONFIGURATION and proposal["configuration_entries"] == 4
    assert proposal["carriers"]["persona"] == ["B1", "B2", "B3", "B4"] and proposal["carriers"]["nodes"]["verify_patient"] == ["R3", "B4"]
    assert proposal["results"]["before"]["passing"] == proposal["results"]["after"]["passing"] == 2
    assert events[-1] == {"event": "done", "proposal": proposal}
    assert ws.last_proposal() == proposal and ws.last_run()["proposal"] == proposal["number"] == 1


def test_without_the_loop_no_test_runs_and_the_proposal_is_blocked(ws):
    runner = Runner()
    proposal = asyncio.run(build.run(ws, Scripted(answer(build_answer())), run_tests=runner, loop=False))
    assert runner.calls == [] and proposal["results"] is None and ws.last_run() is None
    assert proposal["blocked"] == ["The workspace tests were not run (built without the loop)."]


def test_only_approved_tests_run(ws):
    runner = Runner()
    run(ws, Scripted(answer(build_answer())), runner)
    assert runner.calls == [["emergency", "photo-id"]]


def test_every_requirement_is_carried_or_explained(ws):
    lazy = build_answer(operations=build_answer()["operations"][:1] + TRANSFER_EVERYWHERE)  # nothing carries R3
    model = Scripted(answer(lazy), answer(build_answer(operations=lazy["operations"], uncarried=[{"requirement": "R3", "reason": "Not this agent's job."}])))
    proposal, events = run(ws, model, Runner())
    repair = next(e for e in events if e["event"] == "repair")
    assert "Nothing carries R3" in repair["problems"][0]
    assert proposal["uncarried"] == [{"requirement": "R3", "reason": "Not this agent's job."}]


def test_operations_that_do_not_apply_are_sent_back(ws):
    bad = build_answer(operations=[{"op": "delete_node", "name": "nowhere"}])
    model = Scripted(answer(bad), answer(build_answer()))
    proposal, events = run(ws, model, Runner())
    assert "Operation 1 (delete_node): No node 'nowhere'" in next(e for e in events if e["event"] == "repair")["problems"][0]
    assert proposal["status"] == "ready"


def test_every_node_but_the_ends_offers_transfer_to_human(ws):
    partial = build_answer(operations=build_answer()["operations"][:-1])
    proposal, events = run(ws, Scripted(answer(partial), answer(build_answer())), Runner())
    problem = next(e for e in events if e["event"] == "repair")["problems"][0]
    assert problem.startswith("transfer_to_human must be offered in every node that is not an end node; missing in manage_appointment.")
    assert all("transfer_to_human" in n.get("tools", []) for n in proposal["agent"]["nodes"] if not n.get("end"))


def test_the_clinic_and_the_model_stay(ws):
    sneaky = build_answer(operations=build_answer()["operations"] + [{"op": "update_agent", "patch": {"model": "gpt-4o-mini", "clinic": None}}])
    model = Scripted(answer(sneaky), answer(build_answer()))
    _, events = run(ws, model, Runner())
    problems = next(e for e in events if e["event"] == "repair")["problems"]
    assert any("`clinic`" in p for p in problems) and any("`model`" in p for p in problems)


# ---- the loop -----------------------------------------------------------------------------
def test_a_failure_is_diagnosed_fixed_and_kept(ws):
    runner = Runner(photo_id=persona_has("photo ID"))
    model = Scripted(answer(build_answer()), answer(fix_answer()))
    proposal, events = run(ws, model, runner)
    assert runner.calls == [["emergency", "photo-id"], ["photo-id"], ["emergency", "photo-id"]]
    assert proposal["status"] == "ready"
    assert proposal["results"]["before"]["passing"] == 1 and proposal["results"]["after"]["passing"] == 2
    [round_] = proposal["rounds"]
    assert round_["kept"] and round_["diagnoses"][0]["link"] == "node_instruction"
    assert proposal["operations"] == build_answer()["operations"] + fix_answer()["operations"]
    assert proposal["carriers"]["persona"] == ["B1", "B2", "B3", "B4", "R3"]
    assert proposal["diagnoses"] == []  # nothing fails any more
    # The fix call saw the failure's evidence and the failing turn's context.
    request = model.requests[1]["messages"][1]["content"]
    assert "## photo-id\nTier core, fail: The photo-id case" in request and "Mentions the photo ID.: Did not hold." in request
    assert "in node 'greeting' and could call: transfer_to_human" in request


def test_a_test_the_copilot_cannot_pass_ends_blocked_and_unedited(ws):
    before = copy.deepcopy(ws.spec())
    runner = Runner(photo_id=lambda agent, clinic: False)
    model = Scripted(answer(build_answer()), *[answer(fix_answer()) for _ in range(copilot_config.MAX_ROUNDS)])
    proposal, _ = run(ws, model, runner)
    assert len(proposal["rounds"]) == 3 and not any(r["kept"] for r in proposal["rounds"])
    assert all(r["reason"] == "None of the failing tests passed with the change." for r in proposal["rounds"])
    assert runner.calls == [["emergency", "photo-id"]] + [["photo-id"]] * 3  # no full reruns
    assert proposal["status"] == "blocked"
    assert proposal["blocked"] == ["Test photo-id fails (fail). Broken link: node_instruction. The rule is not where the call was."]
    assert proposal["diagnoses"][0]["test"] == "photo-id"
    assert ws.spec() == before  # the tests are as approved


def test_a_failing_safety_test_blocks(ws):
    runner = Runner(emergency=lambda agent, clinic: False)
    model = Scripted(answer(build_answer()), *[answer(fix_answer(tests=("emergency",))) for _ in range(3)])
    proposal, _ = run(ws, model, runner)
    assert proposal["status"] == "blocked" and proposal["blocked"][0].startswith("Safety test emergency fails")


def test_every_failure_needs_its_broken_link(ws):
    runner = Runner(photo_id=persona_has("photo ID"))
    unlinked = fix_answer(diagnoses=[{"test": "photo-id", "link": "bad prompt", "turn": 2, "explanation": "x", "question": None}])
    model = Scripted(answer(build_answer()), answer(fix_answer(diagnoses=[])), answer(unlinked), answer(fix_answer()))
    proposal, events = run(ws, model, runner)
    repairs = [e["problems"] for e in events if e["event"] == "repair"]
    assert "Every failing test needs a diagnosis. Missing: photo-id." in repairs[0]
    assert any("link must be one of configuration, node_instruction" in p for p in repairs[1])
    assert proposal["status"] == "ready"


def test_failures_left_after_a_kept_change_are_diagnosed_again(ws, monkeypatch):
    monkeypatch.setattr(copilot_config, "MAX_ROUNDS", 1)
    ws.save_spec({**ws.spec(), "tests": ws.spec()["tests"] + [make_test("late-fee", "core", ["R2"], [{"type": "judge", "rule": "Says the fee."}])]})
    runner = Runner(photo_id=persona_has("photo ID"), late_fee=lambda agent, clinic: False)
    later = fix_answer(tests=("late-fee",), link="configuration", operations=[])
    model = Scripted(answer(build_answer()), answer(fix_answer(tests=("photo-id", "late-fee"))), answer(later))
    proposal, _ = run(ws, model, runner)
    assert "Only diagnose this time" in model.requests[2]["messages"][0]["content"]
    assert proposal["diagnoses"] == later["diagnoses"]
    assert proposal["blocked"] == ["Test late-fee fails (fail). Broken link: configuration. The rule is not where the call was."]


def test_a_change_that_loses_a_safety_test_is_not_kept(ws):
    runner = Runner(photo_id=persona_has("photo ID"), emergency=lambda agent, clinic: "photo ID" not in agent["persona"])
    model = Scripted(answer(build_answer()), *[answer(fix_answer()) for _ in range(3)])
    proposal, _ = run(ws, model, runner)
    assert proposal["rounds"][0]["reason"] == "Safety test(s) that passed now fail: emergency."
    assert proposal["agent"]["persona"] == PERSONA


def test_a_configuration_edit_is_checked_and_carried(ws):
    facts = {"address": "We are on the harbor.", "parking": "Free parking behind the clinic."}
    runner = Runner(photo_id=lambda agent, clinic: "parking" in clinic["facts"])
    broken = fix_answer(operations=[], configuration=[{"key": "cancellation", "value": {"window_hours": 24, "fee": -5}, "requirements": []}])
    good = fix_answer(operations=[], configuration=[{"key": "facts", "value": facts, "requirements": ["R3"]}])
    model = Scripted(answer(build_answer()), answer(broken), answer(good))
    proposal, events = run(ws, model, runner)
    assert any(p.startswith("Configuration: cancellation.fee") for p in next(e for e in events if e["event"] == "repair")["problems"])
    assert proposal["configuration"]["facts"] == facts and proposal["configuration_changes"] == good["configuration"]
    assert proposal["carriers"]["configuration"]["facts.parking"] == ["R3"]
    assert proposal["configuration_entries"] == 5
    assert load_seed("harbor")["facts"] == CONFIGURATION["facts"]  # written only when accepted


def test_an_unclear_guideline_becomes_a_client_question(ws):
    unclear = fix_answer(link="unclear_guideline", operations=[])
    unclear["diagnoses"][0]["question"] = "Should new patients bring an ID?"
    runner = Runner(photo_id=lambda agent, clinic: False)
    proposal, _ = run(ws, Scripted(answer(build_answer()), answer(unclear)), runner)
    assert proposal["rounds"][0]["reason"] == "No change: every failure is a question for the client."
    assert proposal["questions"] == [{"test": "photo-id", "question": "Should new patients bring an ID?"}]
    assert proposal["status"] == "blocked" and len(runner.calls) == 1


# ---- the leak check ----------------------------------------------------------------------------
def test_leaks_find_names_birth_dates_and_phone_numbers_in_any_form():
    tests = make_spec()["tests"]
    agent = copy.deepcopy(TEMPLATE)
    assert build.leaks(agent, CONFIGURATION, tests) == []
    agent["persona"] += " If the caller is ROSA DÍAZ, book her at once."
    agent["nodes"][0]["task_messages"][0]["content"] += " Born 01/02/1985? Call (555) 010-2233."
    found = build.leaks(agent, CONFIGURATION, tests)
    assert [f.split("'")[1] for f in found] == ["Rosa Diaz", "January 2, 1985", "555-010-2233", "1985-01-02"]


def test_provider_names_are_not_callers():
    test = make_test("x", "core", [], [{"type": "call_ended"}], {"full_name": "Pat Doe", "provider_name": "Dr. Ann Lee"})
    assert build.leaks(TEMPLATE, CONFIGURATION, [test]) == []


def test_the_leak_check_blocks_a_proposal_that_names_a_test_caller(ws):
    named = build_answer()
    named["operations"][0]["patch"]["persona"] += " Rosa Diaz is a VIP."
    proposal, _ = run(ws, Scripted(answer(named)), Runner())
    assert proposal["status"] == "blocked"
    assert proposal["blocked"] == ["Leak: the name 'Rosa Diaz' of test photo-id's caller is in the agent or the configuration."]


def test_a_fix_that_names_a_caller_is_sent_back(ws):
    runner = Runner(photo_id=persona_has("photo ID"))
    special = fix_answer(operations=[{"op": "update_agent", "patch": {"persona": PERSONA + " Tell Rosa Diaz to bring a photo ID."}}])
    model = Scripted(answer(build_answer()), answer(special), answer(fix_answer()))
    proposal, events = run(ws, model, runner)
    assert "Never special-case a test caller" in next(e for e in events if e["event"] == "repair")["problems"][0]
    assert proposal["status"] == "ready" and proposal["leaks"] == []


# ---- accepting -----------------------------------------------------------------------------------
def test_accepting_writes_the_agent_clinic_and_spec(ws, tmp_path):
    facts = {"address": "We are on the harbor.", "parking": "Free parking."}
    good = fix_answer(operations=[], configuration=[{"key": "facts", "value": facts, "requirements": ["R3"]}])
    proposal, _ = run(ws, Scripted(answer(build_answer()), answer(good)), Runner(photo_id=lambda a, c: "parking" in c["facts"]))
    agents = tmp_path / "agents"
    version = build.accept(ws, proposal["number"], agents)
    assert json.loads((agents / "harbor.json").read_text()) == proposal["agent"]
    assert version["source"] == "copilot" and version["number"] == 1
    assert load_seed("harbor")["facts"] == facts and ws.spec()["configuration"]["facts"] == facts
    assert ws.spec()["carriers"] == proposal["carriers"]


def test_a_blocked_proposal_cannot_be_accepted(ws, tmp_path):
    proposal, _ = run(ws, Scripted(answer(build_answer()), *[answer(fix_answer()) for _ in range(3)]), Runner(photo_id=lambda a, c: False))
    with pytest.raises(build.BuildError) as error:
        build.accept(ws, proposal["number"], tmp_path / "agents")
    assert error.value.status == 409 and not (tmp_path / "agents").exists()


def blocked_proposal(ws):
    return run(ws, Scripted(answer(build_answer()), *[answer(fix_answer()) for _ in range(3)]), Runner(photo_id=lambda a, c: False))[0]


def test_a_blocked_proposal_can_be_accepted_anyway(ws, tmp_path):
    proposal = blocked_proposal(ws)
    version = build.accept(ws, proposal["number"], tmp_path / "agents", anyway=True)
    assert version["message"] == f"Proposal {proposal['number']}, accepted while blocked"
    decision = ws.proposal(proposal["number"])["decision"]
    assert decision["status"] == "accepted" and decision["blocked"] and decision["version"] == version["number"]
    with pytest.raises(build.BuildError, match="already accepted"):
        build.accept(ws, proposal["number"], tmp_path / "agents", anyway=True)


def test_a_leak_blocks_for_good(ws, tmp_path):
    proposal = blocked_proposal(ws)
    stored = ws.proposal(proposal["number"])
    ws.update_proposal({**stored, "leaks": ["Rosa Diaz is in the persona."]})
    with pytest.raises(build.BuildError, match="leak check") as error:
        build.accept(ws, proposal["number"], tmp_path / "agents", anyway=True)
    assert error.value.status == 409 and not (tmp_path / "agents").exists()


def test_a_save_after_the_build_started_refuses_the_proposal(ws, tmp_path):
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "harbor.json").write_text(json.dumps(TEMPLATE))
    proposal = asyncio.run(build.run(ws, Scripted(answer(build_answer())), run_tests=Runner(), base=build.saved_hash(agents, "harbor")))
    (agents / "harbor.json").write_text(json.dumps({**TEMPLATE, "persona": "Edited in the editor meanwhile."}))
    with pytest.raises(build.BuildError, match="saved after this build started") as error:
        build.accept(ws, proposal["number"], agents)
    assert error.value.status == 409 and ws.proposal(proposal["number"]).get("decision") is None
    (agents / "harbor.json").write_text(json.dumps(TEMPLATE))  # the save undone: accepted
    assert build.accept(ws, proposal["number"], agents)["number"] == 1


def test_rejecting_changes_nothing_but_the_decision(ws, tmp_path):
    proposal = blocked_proposal(ws)
    spec = ws.spec()
    assert build.reject(ws, proposal["number"])["status"] == "rejected"
    assert ws.spec() == spec and ws.versions() == [] and not (tmp_path / "agents").exists()
    with pytest.raises(build.BuildError, match="already rejected"):
        build.accept(ws, proposal["number"], tmp_path / "agents", anyway=True)


# ---- the API ---------------------------------------------------------------------------------
def client(tmp_path, model, runner) -> TestClient:
    app = FastAPI()
    app.include_router(make_router(tmp_path, model=lambda: model, agents_dir=tmp_path / "agents", run_tests=runner))
    return TestClient(app)


def events_of(response) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_the_api_streams_the_build_and_accepts(ws, tmp_path):
    api = client(tmp_path, Scripted(answer(build_answer())), Runner())
    response = api.post("/copilot/workspaces/harbor/build")
    assert response.status_code == 200 and "event: operation\ndata: " in response.text
    events = events_of(response)
    assert [e["event"] for e in events] == ["part"] + ["operation"] * len(build_answer()["operations"]) + ["part", "tests", "done"]
    number = events[-1]["proposal"]["number"]
    assert api.get("/copilot/workspaces/harbor/proposals/last").json()["number"] == number
    assert api.post(f"/copilot/workspaces/harbor/proposals/{number}/accept").json()["version"]["number"] == 1
    assert api.post("/copilot/workspaces/harbor/proposals/9/accept").status_code == 404


def test_the_api_accepts_anyway_and_rejects(ws, tmp_path):
    api = client(tmp_path, Scripted(answer(build_answer()), *[answer(fix_answer()) for _ in range(3)]), Runner(photo_id=lambda a, c: False))
    number = events_of(api.post("/copilot/workspaces/harbor/build"))[-1]["proposal"]["number"]
    accept = f"/copilot/workspaces/harbor/proposals/{number}/accept"
    assert api.post(accept).status_code == 409
    assert api.post(accept, json={"anyway": True}).json()["version"]["message"].endswith("accepted while blocked")
    assert api.post(f"/copilot/workspaces/harbor/proposals/{number}/reject").status_code == 409  # already decided
    assert api.post("/copilot/workspaces/harbor/proposals/9/reject").status_code == 404


def test_the_api_builds_without_the_loop(ws, tmp_path):
    runner = Runner()
    api = client(tmp_path, Scripted(answer(build_answer())), runner)
    events = events_of(api.post("/copilot/workspaces/harbor/build", json={"loop": False}))
    assert "tests" not in [e["event"] for e in events] and runner.calls == []
    assert events[-1]["proposal"]["blocked"] == ["The workspace tests were not run (built without the loop)."]


def test_the_api_runs_the_tests_on_the_editors_agent(ws, tmp_path):
    runner = Runner(photo_id=persona_has("photo ID"))
    api = client(tmp_path, Scripted(), runner)
    assert api.get("/copilot/workspaces/harbor/runs/last").status_code == 404
    agent = {**TEMPLATE, "persona": "Remind new patients to bring a photo ID."}
    events = events_of(api.post("/copilot/workspaces/harbor/tests/run", json={"agent": agent}))
    assert [e["event"] for e in events] == ["part", "test", "test", "done"]  # the draft test is not run
    assert [e["done"] for e in events if e["event"] == "test"] == [1, 2]
    run = events[-1]["run"]
    assert run["summary"]["passing"] == 2 and run["agent_hash"] == build.agent_hash(agent)
    assert runner.calls == [["emergency", "photo-id"]]
    last = api.get("/copilot/workspaces/harbor/runs/last").json()
    assert last["summary"] == run["summary"] and "results" not in last


def test_the_api_replays_recorded_streams(ws, tmp_path):
    """The stub backend (COPILOT_REPLAY): streams come from recordings and store what the step would."""
    recordings = tmp_path / "recordings"
    api = client(tmp_path, Scripted(answer(build_answer())), Runner())
    events_of(api.post("/copilot/workspaces/harbor/build"))  # a proposal to record from
    from copilot import recording

    recording.write_from_workspace(ws, recordings)
    app = FastAPI()
    app.include_router(make_router(tmp_path, model=lambda: Scripted(), agents_dir=tmp_path / "agents", run_tests=Runner(), replay=recordings))
    stub = TestClient(app)
    ws.save_guidelines("Any guidelines.")
    spec = events_of(stub.post("/copilot/workspaces/harbor/spec", json={"replace_approved": True}))
    assert spec[-1]["event"] == "done" and {t["status"] for t in ws.spec()["tests"]} == {"draft"}
    stub.patch("/copilot/workspaces/harbor/spec/tests", json={"status": "approved"})
    built = events_of(stub.post("/copilot/workspaces/harbor/build"))
    assert [e["event"] for e in built][:2] == ["part", "operation"] and built[-1]["proposal"]["number"] == 2
    assert stub.get("/copilot/workspaces/harbor/proposals/last").json()["number"] == 2
    ran = events_of(stub.post("/copilot/workspaces/harbor/tests/run", json={"agent": TEMPLATE}))
    assert ran[-1]["run"]["agent_hash"] == build.agent_hash(TEMPLATE)
    assert stub.get("/copilot/workspaces/harbor/runs/last").json()["agent_hash"] == build.agent_hash(TEMPLATE)


def test_the_api_records_live_streams(ws, tmp_path):
    recordings = tmp_path / "recordings"
    app = FastAPI()
    app.include_router(make_router(tmp_path, model=lambda: Scripted(answer(build_answer())), agents_dir=tmp_path / "agents", run_tests=Runner(), record=recordings))
    events = events_of(TestClient(app).post("/copilot/workspaces/harbor/build"))
    from copilot import recording

    assert [e["event"] for e in recording.read(recordings / "build.jsonl")] == [e["event"] for e in events]


def test_a_cached_step_replays_the_agents_recording(ws, tmp_path, monkeypatch):
    """#34's switch: `cached` replays recordings/<agent id>/<step>.jsonl on a live server."""
    from copilot import recording

    monkeypatch.setattr(recording, "MAX_GAP", 0)
    recordings = tmp_path / "recordings"
    api = client(tmp_path, Scripted(answer(build_answer())), Runner())
    live = events_of(api.post("/copilot/workspaces/harbor/build"))
    recording.write_from_workspace(ws, recordings / "harbor")
    app = FastAPI()
    app.include_router(make_router(tmp_path, model=lambda: Scripted(), agents_dir=tmp_path / "agents", run_tests=Runner(), recordings=recordings))
    server = TestClient(app)
    assert server.get("/copilot/workspaces/harbor/recordings").json() == {"steps": ["spec", "build", "tests"]}
    assert server.get("/copilot/workspaces/other/recordings").json() == {"steps": []}
    cached = events_of(server.post("/copilot/workspaces/harbor/build", json={"cached": True}))
    assert cached[-1]["proposal"]["number"] == 2 and cached[-1]["proposal"]["agent"]["clinic"] == "harbor"
    assert cached[-1]["proposal"]["operations"] == live[-1]["proposal"]["operations"]
    ws.save_guidelines("Any guidelines.")
    again = events_of(server.post("/copilot/workspaces/harbor/build", json={"cached": True, "loop": False}))
    assert again[-1]["event"] == "done"  # the same recording, loop or not
    (recordings / "harbor" / "spec.jsonl").unlink()
    failed = events_of(server.post("/copilot/workspaces/harbor/spec", json={"cached": True, "replace_approved": True}))
    assert failed[-1]["event"] == "error" and "No recording" in failed[-1]["message"]


def test_a_rehearsal_records_each_agents_live_steps(ws, tmp_path):
    recordings = tmp_path / "recordings"
    app = FastAPI()
    app.include_router(make_router(tmp_path, model=lambda: Scripted(answer(build_answer())), agents_dir=tmp_path / "agents",
                                   run_tests=Runner(), recordings=recordings, rehearse=True))
    events = events_of(TestClient(app).post("/copilot/workspaces/harbor/build"))
    from copilot import recording

    assert [e["event"] for e in recording.read(recordings / "harbor" / "build.jsonl")] == [e["event"] for e in events]


def test_the_api_never_builds_into_the_template(tmp_path, monkeypatch):
    monkeypatch.setattr(clinics_module, "WORKSPACES_DIR", tmp_path)
    ws = Workspace(build.TEMPLATE_ID, tmp_path)
    ws.save_spec(make_spec())
    ws.save_guidelines("Any guidelines.")
    api = client(tmp_path, Scripted(), Runner())
    base = f"/copilot/workspaces/{build.TEMPLATE_ID}"
    for path in ("/spec", "/build", "/proposals/1/accept"):
        response = api.post(base + path)
        assert response.status_code == 409 and "template" in response.json()["detail"], path
    assert api.get(base + "/spec").status_code == 200  # reading it is fine


def test_the_api_needs_approved_tests(tmp_path, monkeypatch):
    monkeypatch.setattr(clinics_module, "WORKSPACES_DIR", tmp_path)
    spec = make_spec()
    for test in spec["tests"]:
        test["status"] = "draft"
    Workspace("harbor", tmp_path).save_spec(spec)
    api = client(tmp_path, Scripted(), Runner())
    assert api.post("/copilot/workspaces/harbor/build").status_code == 400
    assert api.get("/copilot/workspaces/harbor/proposals/last").status_code == 404


# ---- what the Copilot can read --------------------------------------------------------------
OPENED: list[str] = []


def _audit(event, args):
    if event == "open" and OPENED and OPENED[0] == "on" and isinstance(args[0], (str, bytes, Path)):
        OPENED.append(str(Path(args[0] if not isinstance(args[0], bytes) else args[0].decode()).resolve()))


sys.addaudithook(_audit)


class Always(Scripted):
    """Answers every request with the same completion."""

    def __init__(self, completion):
        super().__init__()
        self.completion = completion

    async def complete(self, request):
        self.requests.append(copy.deepcopy(request))
        return self.completion


def test_no_reference_test_reaches_the_copilot(tmp_path, monkeypatch):
    """The build, through the API and the real runner (scripted models), opens nothing under
    backend/eval/ or another clinic's file, and no reference test id, title or judge rule is
    in any request: the Copilot's prompts, or the agent's (which carry the tool results)."""
    monkeypatch.setattr(clinics_module, "WORKSPACES_DIR", tmp_path)
    Workspace("clinic-a", tmp_path).save_spec(make_spec())
    reference = json.loads((BACKEND / "eval" / "clinic-a" / "tests.json").read_text())["tests"]
    copilot = Scripted(answer(build_answer()))
    roles = Models(agent=Always(say("Goodbye.")), caller=Always(caller("Bye.", hang_up=True)), judge=Always(verdict(True)))
    runner = lambda agent, tests, clinic: run_suite(agent, tests, roles, use_cache=False, cache_dir=tmp_path / "cache", clinic=clinic)
    api = client(tmp_path, copilot, runner)

    OPENED[:] = ["on"]
    try:
        events = events_of(api.post("/copilot/workspaces/clinic-a/build"))
    finally:
        opened, OPENED[:] = OPENED[1:], []
    assert events[-1]["event"] == "done" and events[-1]["proposal"]["status"] == "ready", events[-1]
    forbidden = [str((BACKEND / "eval").resolve()), str((BACKEND / "clinic" / "clinics").resolve())]
    assert opened and not [p for p in opened if any(p.startswith(f) for f in forbidden)]

    sent = json.dumps([copilot.requests, roles.agent.requests, roles.judge.requests])
    assert "Harbor Family Clinic" in sent  # the requests are the ones checked
    for test in reference:
        assert test["id"] not in sent and test["title"] not in sent
        for check in test["checks"]:
            assert check.get("rule", "\0") not in sent
