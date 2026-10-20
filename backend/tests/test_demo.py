"""The demo seed (#32): the weak agent, the hidden callers, simulated speech-to-text
and the installed workspace. Scripted models only."""

import asyncio
import json

from agent_builder.validation import validate_agent
from copilot.workspace import Workspace
from demo import generate
from demo.__main__ import install
from demo.weak import AGENT_ID, DEFECTS, EDITS, weak_agent
from eval.mutants import PRIVACY
from simfakes import call, caller, models, say


def node(agent, name):
    return next(n for n in agent["nodes"] if n["name"] == name)


def test_the_weak_agent_is_valid_and_has_every_defect():
    reference = json.loads(generate.AGENT.parent.parent.joinpath("eval", "clinic-a", "reference-agent.json").read_text())
    agent = weak_agent(reference)
    assert validate_agent(agent) == []
    assert {d["id"] for d in DEFECTS} == set(EDITS)
    assert "spell it letter by letter" not in node(agent, "ask_name")["task_messages"][0]["content"]
    assert "Never offer or confirm a time that find_slots did not return" not in node(agent, "offer_times")["task_messages"][0]["content"]
    assert "transfer_to_human" not in node(agent, "collect_reason")["tools"]
    assert "transfer_to_human" not in node(agent, "offer_times")["tools"]
    assert "transfer_to_human" in node(agent, "verify_patient")["tools"]
    assert PRIVACY not in agent["persona"] and "Clinic staff" in agent["persona"]
    assert json.loads(generate.AGENT.read_text()) == agent  # the committed agent is the code's


def test_the_hidden_callers_are_valid_tests_with_distinct_ids():
    callers = generate.load_callers()
    assert generate.problems(callers) == []
    planted = {p for c in callers for p in c["plants"]}
    assert planted == {d["id"] for d in DEFECTS}
    assert sum(not c["plants"] for c in callers) >= 6  # calls with nothing planted, for false alarms


def test_hearing_swaps_names_both_ways_and_leaves_letters():
    hearing = generate.Hearing([["Sarah Burrell", "Sara Boreal"], ["Burrell", "Boreal"]])
    assert hearing.to_agent("It's sarah burrell, Burrell with two Rs.") == "It's Sara Boreal, Boreal with two Rs."
    assert hearing.to_caller("Is that Sara Boreal? B, O, R, E, A, L.") == "Is that Sarah Burrell? B, O, R, E, A, L."
    assert generate.Hearing(None).to_agent("unchanged") == "unchanged"


def test_a_call_is_made_through_simulated_speech_to_text_and_stored(tmp_path, monkeypatch):
    agent = weak_agent()
    monkeypatch.setattr(generate, "AGENT", tmp_path / "agent.json")
    monkeypatch.setattr(generate, "CHECKS", tmp_path / "checks.json")
    generate.AGENT.write_text(json.dumps(agent))
    Workspace(AGENT_ID, root=tmp_path).add_version(agent, "editor")
    fake = models(
        agent=[
            say("Thank you for calling Linden Grove Family Practice. How can I help you today?"),
            call("choose_intent", intent="book"),
            say("Can I have your full name?"),
            call("record_spelling", spelled_name="Sara Boreal"),
            say("Is that Sara Boreal?"),
        ],
        caller=[caller("I'd like to book a visit."), caller("It's Sarah Burrell."), caller("Yes.", hang_up=True)],
    )
    done = asyncio.run(generate.generate(fake, only={"c01"}, root=tmp_path))
    assert done["made"] == ["c01"]
    stored = Workspace(AGENT_ID, root=tmp_path).call("lg-1019-0804")
    assert stored["source"] == "production-mock" and stored["version"] == 1
    assert stored["start"] == "2026-10-19T08:04:00" and stored["end"] > stored["start"]
    assert stored["world"]["clinic"]["now"] == "2026-10-19T08:04"
    spoken = [t["text"] for t in stored["turns"] if t["speaker"] == "caller"]
    assert spoken[1] == "It's Sara Boreal."  # as speech-to-text heard it
    # The caller heard the agent's "Sara Boreal" as its own name.
    assert "Is that Sarah Burrell?" in fake.caller.requests[-1]["messages"][1]["content"]
    assert "usage" not in stored
    checks = json.loads(generate.CHECKS.read_text())["c01"]
    assert checks["call"] == "lg-1019-0804" and checks["checks"][0]["pass"] is False
    # Stored calls are not made again.
    assert asyncio.run(generate.generate(models(), only={"c01"}, root=tmp_path))["made"] == []


def test_install_copies_the_seed_and_refuses_to_overwrite_a_changed_agent(tmp_path, monkeypatch):
    agents, workspaces = tmp_path / "agents", tmp_path / "workspaces"
    assert install(agents_dir=agents, workspaces_dir=workspaces) == []
    assert json.loads((agents / f"{AGENT_ID}.json").read_text()) == json.loads(generate.AGENT.read_text())
    installed = Workspace(AGENT_ID, root=workspaces)
    assert installed.versions()[0]["number"] == 1 and installed.spec()["requirements"]
    (agents / f"{AGENT_ID}.json").write_text("{}")
    assert install(agents_dir=agents, workspaces_dir=workspaces)
    assert install(force=True, agents_dir=agents, workspaces_dir=workspaces) == []


def test_the_seed_judge_results_are_current():
    """Each committed judge result was made with today's judge and requirements, so
    `make demo-seed` gives the inbox without a model call."""
    from detect import judge

    workspace = generate.seed_workspace()
    spec = workspace.spec()
    for row in workspace.calls():
        stored = judge.stored(workspace, row["id"])
        assert stored is not None and stored["key"] == judge.key(workspace.call(row["id"]), spec), row["id"]


def test_the_judge_meets_its_bar_on_the_seed():
    """The numbers in #32's PR, from the committed results: no model calls."""
    from demo import evaluate

    report = evaluate.evaluate(generate.SEED_ROOT)
    assert report["judged"] == report["calls"] == 22
    assert report["planted_found"] / report["planted_total"] >= 0.8
    assert len(report["false_alarms"]) / report["judged"] * 5 <= 1
    assert report["blamed"] / report["planted_found"] >= 0.8
    assert all(t["right"] for t in report["tickets"])


def test_reset_archives_what_it_replaces_and_installs_the_seed(tmp_path):
    """#34: an accepted fix and Act 1's build cost model calls and are not in git."""
    from demo.__main__ import ACT1_ID, reset

    agents, spaces, archive = tmp_path / "agents", tmp_path / "workspaces", tmp_path / "archive"
    assert reset(agents, spaces, archive) is None  # nothing there yet: the seed is installed
    (agents / "linden-grove.json").write_text('{"changed": true}')
    (spaces / "linden-grove" / "fixes").mkdir()
    (spaces / "linden-grove" / "fixes" / "0001.json").write_text("{}")
    (agents / f"{ACT1_ID}.json").write_text("{}")
    (spaces / ACT1_ID).mkdir()
    (spaces / ACT1_ID / "spec.json").write_text("{}")

    kept = reset(agents, spaces, archive)
    assert (kept / "workspaces" / "linden-grove" / "fixes" / "0001.json").is_file()
    assert (kept / "agents" / "linden-grove.json").read_text() == '{"changed": true}'
    assert (kept / "workspaces" / ACT1_ID / "spec.json").is_file()
    assert (agents / "linden-grove.json").read_text() == generate.AGENT.read_text()
    assert not (spaces / "linden-grove" / "fixes").exists() and (spaces / "linden-grove" / "judge").is_dir()
    assert not (agents / f"{ACT1_ID}.json").exists() and not (spaces / ACT1_ID).exists()
