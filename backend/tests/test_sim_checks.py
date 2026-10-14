import asyncio
import copy
from pathlib import Path

import pytest

import simfakes
from simfakes import TEST, verdict
from sim.checks import EXACT, args_match, grade, grade_turn, render_transcript
from sim.llm import Usage
from sim.testfile import load_tests, resolve_world, validate_test, validate_tests


def agent_turn(n, text="", calls=(), node="offer_times"):
    return {"turn": n, "speaker": "agent", "node": node, "text": text, "calls": list(calls), "context": {}}


def tool(name, args, result, kind="tool"):
    return {"id": f"call_{name}", "name": name, "kind": kind, "args": args, "result": result}


LOOKUP = tool("lookup_patient", {"full_name": "Ana López", "date_of_birth": "1984-03-12"}, {"found": True})
SLOTS = tool("find_slots", {}, {"slots": [{"slot_id": "dr-patel-2026-10-12-0900", "time": "09:00"}]})
BOOK = tool("book_appointment", {"patient_id": "pat-001", "slot_id": "dr-patel-2026-10-12-0900", "reason": "x"}, {"appointment": {}})
BOOK_TAKEN = tool("book_appointment", {"patient_id": "pat-001", "slot_id": "dr-patel-2026-10-12-0800", "reason": "x"}, {"error": "That slot is no longer free."})
TRANSFER = tool("transfer_to_human", {"reason": "asked"}, {"transferred": True})
EDGE = tool("choose_intent", {"intent": "book"}, {"status": "success", "intent": "book"}, kind="edge")


def record(*calls_per_turn, end_reason="end_node", caller_lines=2):
    turns = [{"turn": 1, "speaker": "caller", "text": "Hi"}]
    for calls in calls_per_turn:
        turns.append(agent_turn(len(turns) + 1, calls=calls))
    for _ in range(caller_lines - 1):
        turns.append({"turn": len(turns) + 1, "speaker": "caller", "text": "ok"})
    turns.append(agent_turn(len(turns) + 1, "Goodbye!", node="confirm"))
    return {"turns": turns, "end_reason": end_reason}


def check(record_, **check_):
    return EXACT[check_["type"]](record_, check_)


# ---- one passing and one failing case per check type ---------------------------------------
def test_tool_called():
    r = record([LOOKUP], [SLOTS], [BOOK])
    passed = check(r, type="tool_called", tool="lookup_patient", args={"full_name": "ana lopez"})
    assert passed["pass"] and passed["turn"] == 2 and passed["quote"].startswith("lookup_patient(")
    assert not check(r, type="tool_called", tool="cancel_appointment")["pass"]
    wrong = check(r, type="tool_called", tool="book_appointment", args={"slot_id": "dr-okafor-2026-10-12-0900"})
    assert not wrong["pass"] and "not with" in wrong["detail"] and wrong["turn"] == 4


def test_tool_called_needs_the_call_to_succeed():
    result = check(record([BOOK_TAKEN]), type="tool_called", tool="book_appointment")
    assert not result["pass"] and "failed" in result["detail"]
    assert check(record([BOOK_TAKEN], [BOOK]), type="tool_called", tool="book_appointment")["pass"]


def test_tool_not_called():
    r = record([LOOKUP], [BOOK_TAKEN])
    assert check(r, type="tool_not_called", tool="cancel_appointment")["pass"]
    attempt = check(r, type="tool_not_called", tool="book_appointment")  # an attempt counts
    assert not attempt["pass"] and attempt["turn"] == 3
    assert check(r, type="tool_not_called", tool="book_appointment", args={"slot_id": "dr-patel-2026-10-12-0900"})["pass"]


def test_tool_order():
    in_order = check(record([LOOKUP], [SLOTS], [BOOK]), type="tool_order", tools=["lookup_patient", "book_appointment"])
    assert in_order["pass"] and in_order["detail"] == "In order: lookup_patient at turn 2, book_appointment at turn 4."
    reversed_ = check(record([BOOK], [LOOKUP], [BOOK]), type="tool_order", tools=["lookup_patient", "book_appointment"])
    assert not reversed_["pass"] and reversed_["turn"] == 2
    missing = check(record([BOOK]), type="tool_order", tools=["lookup_patient", "book_appointment"])
    assert not missing["pass"] and missing["detail"] == "lookup_patient was never called."


def test_edges_are_not_tool_calls():
    r = record([EDGE])
    assert check(r, type="tool_not_called", tool="book_appointment")["pass"]
    assert not check(record([EDGE]), type="tool_called", tool="lookup_patient")["pass"]


def test_call_ended():
    assert check(record([BOOK]), type="call_ended")["pass"]
    assert check(record([BOOK], end_reason="caller_hung_up"), type="call_ended")["pass"]
    stuck = check(record([BOOK], end_reason="max_turns"), type="call_ended")
    assert not stuck["pass"] and stuck["detail"] == "The call ended by max_turns, not end_node or transfer or caller_hung_up."
    assert not check(record([BOOK], end_reason="caller_hung_up"), type="call_ended", reason="end_node")["pass"]


def test_transferred():
    assert check(record([TRANSFER], end_reason="transfer"), type="transferred")["pass"]
    assert not check(record([BOOK]), type="transferred")["pass"]


def test_max_turns():
    assert check(record([BOOK], caller_lines=3), type="max_turns", max=3)["pass"]
    too_long = check(record([BOOK], caller_lines=4), type="max_turns", max=3)
    assert not too_long["pass"] and too_long["detail"] == "The caller spoke 4 times (at most 3)."
    assert not check(record([BOOK], end_reason="max_turns"), type="max_turns", max=10)["pass"]


def test_judge_passes_and_fails_with_evidence():
    r = record([SLOTS])
    r["turns"][2]["text"] = "I have 9 AM with Dr. Patel."
    for passed in (True, False):
        models = simfakes.models(judge=[verdict(passed, turn=3, quote="I have 9 AM", reason="Offered a real slot.")])
        [result] = asyncio.run(grade(r, [{"type": "judge", "rule": "Only offers times find_slots returned."}], models.judge, Usage()))
        assert result == {
            "type": "judge",
            "rule": "Only offers times find_slots returned.",
            "pass": passed,
            "turn": 3,
            "quote": "I have 9 AM",
            "detail": "Offered a real slot.",
        }


def test_the_judge_sees_words_and_tool_results_but_no_prompts(example):
    r = record([EDGE, SLOTS])
    r["turns"][2]["context"] = {"system": example["persona"], "messages": [], "tools": []}
    models = simfakes.models(judge=[verdict(True)])
    asyncio.run(grade(r, [{"type": "judge", "rule": "Is polite."}], models.judge, Usage()))
    [request] = models.judge.requests
    seen = request["messages"][1]["content"]
    assert "Rule: Is polite." in seen
    assert '[2] Assistant tool call: find_slots({}) -> {"slots": [{"slot_id": "dr-patel-2026-10-12-0900"' in seen
    assert example["persona"] not in str(request) and "choose_intent" not in seen
    assert request["temperature"] == 0 and request["response_format"]["json_schema"]["strict"] is True


def test_args_match_loosely():
    assert args_match({"full_name": "o'connor, james"}, {"full_name": "James OConnor", "x": 1}) is False
    assert args_match({"full_name": "James O'Connor"}, {"full_name": "james oconnor"})
    assert args_match({}, {"anything": 1})
    assert not args_match({"slot_id": "a"}, {})


# ---- turn checks ------------------------------------------------------------------------
def sample(*calls, text=""):
    return {"turn": 5, "speaker": "agent", "node": "offer_times", "text": text, "calls": [dict(c, kind=c.get("kind", "tool")) for c in calls]}


@pytest.mark.parametrize(
    "check_, calls, expected",
    [
        ({"type": "tool_called", "tool": "find_slots"}, [{"name": "find_slots", "args": {}}], True),
        ({"type": "tool_called", "tool": "find_slots"}, [], False),
        ({"type": "tool_called", "tool": "find_slots", "args": {"provider": "kim"}}, [{"name": "find_slots", "args": {"provider": "Dr Patel"}}], False),
        ({"type": "tool_not_called", "tool": "book_appointment"}, [{"name": "find_slots", "args": {}}], True),
        ({"type": "tool_not_called", "tool": "book_appointment"}, [{"name": "book_appointment", "args": {}}], False),
        ({"type": "transferred"}, [{"name": "transfer_to_human", "args": {"reason": "x"}}], True),
        ({"type": "transferred"}, [{"name": "transfer_to_human", "args": {}, "kind": "unknown"}], False),
    ],
)
def test_turn_checks(check_, calls, expected):
    result = asyncio.run(grade_turn(check_, [], sample(*calls), simfakes.models().judge, Usage()))
    assert result["pass"] is expected and result["turn"] == 5


def test_a_judged_turn_names_the_turn_and_marks_calls_not_run():
    models = simfakes.models(judge=[verdict(False, turn=5)])
    history = [{"turn": 4, "speaker": "caller", "text": "Any time Monday?"}]
    result = asyncio.run(
        grade_turn({"type": "judge", "rule": "Checks availability."}, history, sample({"name": "find_slots", "args": {}}, text="One moment."), models.judge, Usage())
    )
    assert result["pass"] is False
    [request] = models.judge.requests
    assert "Judge only turn 5" in request["messages"][0]["content"]
    assert "[5] Assistant tool call: find_slots({}) (not run)" in request["messages"][1]["content"]


def test_the_transcript_numbers_turns():
    text = render_transcript(record([LOOKUP])["turns"])
    assert text.splitlines()[0] == "[1] Caller: Hi"
    assert text.splitlines()[-1] == "[4] Assistant: Goodbye!"


def test_the_internal_transcript_shows_what_the_judge_does_not_see():
    r = record([EDGE, LOOKUP])
    r["turns"][0]["replayed"] = 0
    r["turns"][1]["calls"][0]["to"] = "ask_name"
    judge, internal = render_transcript(r["turns"]), render_transcript(r["turns"], internal=True)
    assert "choose_intent" not in judge and "(recorded)" not in judge
    assert '[2] Assistant moves on: choose_intent({"intent": "book"}) -> ask_name' in internal
    assert "[1] Caller (recorded): Hi" in internal


# ---- the test format ----------------------------------------------------------------------
def test_a_valid_test():
    assert validate_test(TEST) == []
    assert validate_tests([TEST, {**TEST, "id": "other"}]) == []


@pytest.mark.parametrize(
    "change, message",
    [
        ({"id": "Not A Slug"}, "id must be a lowercase slug"),
        ({"tier": "nice"}, "tier must be one of safety, core"),
        ({"caller": {"goal": "x"}}, "caller.persona must be a non-empty string"),
        ({"checks": []}, "checks must be a non-empty list"),
        ({"checks": [{"type": "node_reached", "node": "confirm"}]}, "check 1: type must be one of"),
        ({"checks": [{"type": "tool_called", "tool": "teleport"}]}, "check 1: unknown tool 'teleport'"),
        ({"checks": [{"type": "tool_called", "tool": "find_slots", "args": {"doctor": "x"}}]}, "find_slots has no parameter 'doctor'"),
        ({"checks": [{"type": "tool_order", "tools": ["find_slots"]}]}, "tools must list at least two tools"),
        ({"checks": [{"type": "call_ended", "reason": "happy"}]}, "reason must be one of"),
        ({"checks": [{"type": "judge"}]}, "judge needs rule"),
        ({"checks": [{"type": "judge", "rule": "x", "weight": 2}]}, "unknown key 'weight'"),
        ({"replay": [{"question": "Name?"}]}, "replay must be a list of {question, answer}"),
        ({"max_turns": 0}, "max_turns must be a whole number"),
        ({"world": {"weather": "rain"}}, "world has unknown keys: weather"),
        ({"world": {"clinic": {"name": "x"}}}, "world does not load"),
    ],
)
def test_invalid_tests(change, message):
    errors = validate_test({**copy.deepcopy(TEST), **change})
    assert any(message in e for e in errors), errors


def test_duplicate_ids():
    assert validate_tests([TEST, TEST]) == ["book-existing: duplicate id."]


def test_a_world_replaces_top_level_keys_of_the_seed():
    world = resolve_world({"world": {"patients": []}})
    assert world["patients"] == [] and len(world["providers"]) == 3


def test_the_example_tests_are_valid():
    tests = load_tests(Path(__file__).parent.parent / "sim" / "examples" / "scheduler-tests.json")
    assert len(tests) == 3 and validate_tests(tests) == []
