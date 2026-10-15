import asyncio
import copy
import json

import pytest

import simfakes
from simfakes import BOOKING_AGENT, BOOKING_CALLER, TEST, call, caller, say, verdict
from sim.caller import recorded_answers
from sim.conversation import Conversation, ReplayError
from sim.replay import as_record, continue_from, replay_turn
from sim.runner import simulate


@pytest.fixture
def booked(example) -> dict:
    """A scripted booking, round-tripped through JSON like a cached result."""
    models = simfakes.models(agent=copy.deepcopy(BOOKING_AGENT), caller=copy.deepcopy(BOOKING_CALLER))
    record = asyncio.run(simulate(example, TEST, models))
    return json.loads(json.dumps(record))


def model_turns(record):
    return [t for t in record["turns"] if t["speaker"] == "agent" and "context" in t]


# ---- rebuilding (acceptance: the same agent rebuilds exactly the recorded messages) ------------
def test_the_same_agent_rebuilds_every_turn_exactly(example, booked):
    for turn in model_turns(booked):
        conversation = Conversation.rebuild(booked, example, turn["turn"], simfakes.models())
        assert conversation.context() == turn["context"], f"turn {turn['turn']}"
        assert conversation.node == turn["node"]


def test_the_rebuild_brings_the_clinic_to_that_turn(example, booked):
    last = model_turns(booked)[-1]
    conversation = Conversation.rebuild(booked, example, last["turn"], simfakes.models())
    # Patel's 9:00 was booked earlier in the call, so it is taken now.
    args = {"patient_id": "pat-001", "slot_id": "dr-patel-2026-10-12-0900", "reason": "x", "appointment_type": "checkup", "interpreter": "none"}
    assert conversation.world.call("book_appointment", args) == {
        "error": "That slot is no longer free. Call find_slots again."
    }


def test_another_agent_keeps_the_history_and_brings_its_own_prompts(example, booked):
    changed = copy.deepcopy(example)
    offer_times = next(n for n in changed["nodes"] if n["name"] == "offer_times")
    offer_times["task_messages"][0]["content"] = "Offer only afternoon slots."
    changed["persona"] = "You are terse."
    turn = next(t for t in model_turns(booked) if t["node"] == "offer_times")
    conversation = Conversation.rebuild(booked, changed, turn["turn"], simfakes.models())
    recorded = turn["context"]
    assert conversation.context()["messages"][-1] == {"role": "developer", "content": "Offer only afternoon slots."}
    assert conversation.system.startswith("You are terse.")
    # The words and calls before the turn are the record's.
    spoken = lambda messages: [m for m in messages if m["role"] in ("user", "assistant")]  # noqa: E731
    assert spoken(conversation.context()["messages"]) == spoken(recorded["messages"])


def test_a_missing_node_cannot_be_rebuilt(example, booked):
    changed = copy.deepcopy(example)
    changed["nodes"] = [n for n in changed["nodes"] if n["name"] != "verify_patient"]
    for node in changed["nodes"]:
        for edge in node.get("edges", []):
            if edge["target"] == "verify_patient":
                edge["target"] = "collect_reason"
    last = model_turns(booked)[-1]
    with pytest.raises(ReplayError, match="verify_patient"):
        Conversation.rebuild(booked, changed, last["turn"], simfakes.models())


# ---- replay_turn ----------------------------------------------------------------------------
def test_replay_turn_samples_k_times_on_the_recorded_context(example, booked):
    turn = next(t for t in model_turns(booked) if t["node"] == "offer_times")  # where find_slots was called
    samples = [call("find_slots"), call("find_slots", date_from="2026-10-13"), say("Any day?"), call("find_slots"), say("Morning?")]
    models = simfakes.models(agent=samples)
    result = asyncio.run(replay_turn(booked, turn["turn"], example, {"type": "tool_called", "tool": "find_slots"}, models, k=5))
    assert result["rate"] == "3/5" and result["passed"] == 3 and result["node"] == "offer_times"
    assert len(models.agent.requests) == 5
    expected = {"model": example["model"], "messages": [{"role": "system", "content": turn["context"]["system"]}] + turn["context"]["messages"], "tools": turn["context"]["tools"]}
    assert all(request == expected for request in models.agent.requests)
    assert models.caller.requests == []  # no simulated caller


def test_replay_turn_with_a_judge_rule(example, booked):
    turn = model_turns(booked)[2]
    models = simfakes.models(agent=[say("Spell it?")] * 2, judge=[verdict(True), verdict(False)])
    result = asyncio.run(replay_turn(booked, turn["turn"], example, {"type": "judge", "rule": "Asks one thing at a time."}, models, k=2))
    assert result["rate"] == "1/2"


def test_replay_turn_takes_a_test_result_and_rejects_caller_turns(example, booked):
    result = {"runs": [{**booked, "passed": True}]}
    assert as_record(result)["turns"] == booked["turns"]
    caller_turn = next(t for t in booked["turns"] if t["speaker"] == "caller")
    with pytest.raises(ValueError, match="not a model turn"):
        asyncio.run(replay_turn(result, caller_turn["turn"], example, {"type": "transferred"}, simfakes.models()))


# ---- continue_from (acceptance: recorded words up to the divergence) ---------------------------
def test_continue_from_reuses_recorded_words_until_the_first_divergence(example, booked):
    start = model_turns(booked)[2]  # ask_name: "What is your full name...?"
    recorded = recorded_answers(booked["turns"], from_turn=start["turn"])
    assert recorded[0] == {"question": "Sure. What is your full name, and could you spell it for me?", "answer": "Ana Lopez. A, N, A, L, O, P, E, Z."}
    agent = [
        say("Your full name, spelled please?"),
        call("record_spelling", spelled_name="Ana Lopez"),
        say("Ana Lopez, A N A L O P E Z, right?"),
        call("name_confirmed", full_name="Ana Lopez"),
        say("Do you have insurance with us?"),  # a new question: the call diverges here
    ]
    callers = [
        caller("(ignored)", use_recorded=0),
        caller("(ignored)", use_recorded=1),
        caller("No, I pay myself. Bye.", hang_up=True),
    ]
    models = simfakes.models(agent=agent, caller=callers)
    result = asyncio.run(continue_from(booked, start["turn"], example, TEST["caller"], models, k=1))
    [run] = result["runs"]
    spoken = [t for t in run["turns"] if t["speaker"] == "caller" and t["turn"] > start["turn"]]
    assert [t["text"] for t in spoken] == [recorded[0]["answer"], recorded[1]["answer"], "No, I pay myself. Bye."]
    assert [t.get("replayed") for t in spoken] == [0, 1, None]
    assert run["divergence_turn"] == spoken[2]["turn"] and result["divergence_turns"] == [spoken[2]["turn"]]
    # The turns before the start are the record's, word for word.
    assert run["turns"][: start["turn"] - 1] == booked["turns"][: start["turn"] - 1]
    # Strict: only the next recorded answer is offered, and none after the divergence.
    offered = [r["messages"][0]["content"] for r in models.caller.requests]
    assert recorded[0]["answer"] in offered[0] and recorded[1]["answer"] not in offered[0]
    assert recorded[1]["answer"] in offered[1]
    assert run["end_reason"] == "caller_hung_up"


def test_continue_from_runs_k_times_and_grades(example, booked):
    last = model_turns(booked)[-1]  # the goodbye in the end node
    models = simfakes.models(agent=[say("Booked, goodbye!")] * 3)
    checks = [{"type": "tool_called", "tool": "book_appointment"}]
    result = asyncio.run(continue_from(booked, last["turn"], example, TEST["caller"], models, k=3, checks=checks))
    assert result["rate"] == "3/3" and result["end_reasons"] == ["end_node"] * 3
    assert result["divergence_turns"] == [None] * 3  # the call ended before any caller turn


def test_replay_turn_takes_only_turn_checks(example, booked):
    turn = model_turns(booked)[0]["turn"]
    for check in (
        {"type": "tool_order", "tools": ["find_slots", "book_appointment"]},
        {"type": "tool_called"},
        {"type": "tool_called", "tool": "book_appointment", "result": {"appointment": {}}},  # sampled calls do not run
    ):
        with pytest.raises(ValueError, match="turn check"):
            asyncio.run(replay_turn(booked, turn, example, check, simfakes.models()))
