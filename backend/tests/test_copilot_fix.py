"""Fix from an issue (#33): hearing in tests and continuations, the reproduction from a
ticket, the candidates, the choice, the proposal and its accept. Scripted models; the
continuations, turn replays and suite runs are replaced where a whole fix runs."""

import asyncio
import copy
import json
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import simfakes
from copilot import api as copilot_api
from copilot import build, fix
from copilot.workspace import Workspace
from demo import generate
from detect import api as detect_api
from sim.hearing import Hearing, word_pairs
from sim.llm import Completion
from sim.replay import continue_from
from sim.runner import simulate
from simfakes import BOOKING_AGENT, TEST, call, caller, say
from simfakes import Scripted

CALL = "lg-1019-0804"  # c01: Sarah Burrell, registered as "Sara Boreal"; decided at turn 4 in ask_name
TURN = 4
NAME_RULE = "The assistant asks the caller to spell their name letter by letter."


@pytest.fixture
def seed(tmp_path):
    """A copy of the demo's seed workspace, judge results included, and its agent saved."""
    shutil.copytree(generate.SEED_ROOT, tmp_path / "workspaces", dirs_exist_ok=True)
    agents = tmp_path / "agents"
    agents.mkdir()
    shutil.copy(generate.AGENT, agents / "linden-grove.json")
    return Workspace("linden-grove", root=tmp_path / "workspaces")


@pytest.fixture
def weak() -> dict:
    return json.loads(generate.AGENT.read_text())


def answer(data: dict) -> Completion:
    return Completion(text=json.dumps(data), model="gpt-4.1-2025-04-14", input_tokens=1000, output_tokens=300)


def reproduction(**changes) -> dict:
    data = {
        "title": "A new patient whose name speech-to-text mishears is registered under the name she spells.",
        "corrections": [{"said": "Sarah Burrell", "heard": "Sara Boreal", "ticket": "T1"}],
        "checks": [{"type": "tool_called", "tool": "register_patient", "args": {"full_name": "Sarah Burrell"},
                    "result": None, "tools": None, "reason": None, "max": None, "rule": None}],
        "turn_check": {"type": "judge", "rule": NAME_RULE, "tool": None, "args": None},
        "max_turns": 24,
    }
    return {**data, **changes}


def ask_name(text: str) -> list[dict]:
    return [{"op": "update_node", "name": "ask_name", "patch": {"task_messages": [{"role": "developer", "content": text}]}}]


def candidates(**changes) -> dict:
    data = {
        "link": "node_instruction",
        "turn": TURN,
        "explanation": "ask_name never asks for the spelling, so the name is taken as heard.",
        "question": None,
        "candidates": [
            {"rationale": "Ask for the spelling in ask_name.", "operations": ask_name("Ask for the caller's full name, then ask them to spell it letter by letter.")},
            {"rationale": "Ask for name and spelling in one question.", "operations": ask_name("Ask for the caller's full name and its spelling, letter by letter, in one question.")},
            {"rationale": "The edge needs the letters.", "operations": [{"op": "update_edge", "node": "ask_name", "function": "record_spelling",
                                                                          "patch": {"description": "Call once the caller has spelled their full name letter by letter."}}]},
        ],
    }
    return {**data, **changes}


# ---- hearing ---------------------------------------------------------------------------------
def test_word_pairs_add_each_misheard_word():
    assert word_pairs("Sarah Burrell", "Sara Boreal") == [["Sarah Burrell", "Sara Boreal"], ["Sarah", "Sara"], ["Burrell", "Boreal"]]
    assert word_pairs("Kim", "Tim") == [["Kim", "Tim"]]


def test_hearing_swaps_whole_words_only():
    hearing = Hearing([["Sarah", "Sara"]])
    assert hearing.to_caller("Sara from Saratoga") == "Sarah from Saratoga"
    assert hearing.to_agent("S, A, R, A, H") == "S, A, R, A, H"


def test_a_test_with_hearing_is_misheard_by_the_agent(example):
    test = {**TEST, "hearing": [["Ana Lopez", "Anna Lopes"]]}
    models = simfakes.models(agent=copy.deepcopy(BOOKING_AGENT), caller=copy.deepcopy(simfakes.BOOKING_CALLER))
    record = asyncio.run(simulate(example, test, models))
    said = [t["text"] for t in record["turns"] if t["speaker"] == "caller"]
    assert said[1] == "Anna Lopes. A, N, A, L, O, P, E, Z."  # the letters get through
    # The caller remembers what it said, not what speech-to-text wrote down.
    heard = models.caller.requests[2]["messages"][1]["content"]
    assert "Anna Lopes" not in heard and "You: Ana Lopez. A, N" in heard


def test_continue_from_hears_improvised_words_through_the_pairs(example):
    models = simfakes.models(agent=copy.deepcopy(BOOKING_AGENT), caller=copy.deepcopy(simfakes.BOOKING_CALLER))
    record = json.loads(json.dumps(asyncio.run(simulate(example, TEST, models))))
    agent = [say("Hello! Book, reschedule or cancel?"), call("choose_intent", intent="book"), say("Your full name?")]
    models = simfakes.models(agent=agent, caller=[caller("Book, please."), caller("Ana Lopez.", hang_up=True)])
    result = asyncio.run(continue_from(record, 1, example, TEST["caller"], models, k=1, hearing=[["Ana Lopez", "Anna Lopes"]]))
    spoken = [t["text"] for t in result["runs"][0]["turns"] if t["speaker"] == "caller"]
    assert spoken[-1] == "Anna Lopes."


def test_the_test_format_checks_hearing():
    from sim.testfile import validate_test

    base = {k: v for k, v in TEST.items()}
    assert validate_test({**base, "hearing": [["Ana", "Anna"]]}, "riverside") == []
    assert "hearing must be a list" in " ".join(validate_test({**base, "hearing": [["Ana"]]}, "riverside"))


# ---- the reproduction --------------------------------------------------------------------------
def checked(seed, data):
    call_, issue, judged = fix.find_issue(seed, CALL, TURN)
    tickets = fix.call_tickets(seed, call_)
    return fix.check_reproduction(data, call_, judged["card"], tickets, seed.spec()["configuration"], issue)


def test_the_ticket_matched_to_the_call_has_the_true_name(seed):
    call_, issue, judged = fix.find_issue(seed, CALL, TURN)
    assert issue["node"] == "ask_name" and issue["kind"] == "wrong_patient"
    assert [t["id"] for t in fix.call_tickets(seed, call_)] == ["T1"]
    assert "Sara Boreal" in judged["card"]["facts"]["full_name"]  # the card only knows what was heard


def test_the_reproduction_corrects_the_card_and_mishears_it_again(seed):
    value, problems = checked(seed, reproduction())
    assert problems == []
    test = value["test"]
    assert test["id"] == f"repro-{CALL}-t{TURN}" and test["requirements"] == ["B3"]
    assert test["caller"]["facts"]["full_name"] == "Sarah Burrell"
    assert "Sarah Burrell" in test["caller"]["persona"] and "Boreal" not in json.dumps(test["caller"])
    assert ["Burrell", "Boreal"] in test["hearing"]
    assert test["replay"][1]["answer"] == "Sara Boreal."  # recorded words stay as heard
    assert test["world"]["clinic"]["now"] == "2026-10-19T08:04"  # the clinic as it was during the call
    assert test["checks"] == [{"type": "tool_called", "tool": "register_patient", "args": {"full_name": "Sarah Burrell"}}]
    assert value["turn_check"] == {"type": "judge", "rule": NAME_RULE}


def test_corrections_must_come_from_the_ticket_and_the_recorded_words(seed):
    _, problems = checked(seed, reproduction(corrections=[{"said": "Sarah Burrell", "heard": "Sarah Burrel", "ticket": "T1"}]))
    assert any("not in the caller's words" in p for p in problems)
    _, problems = checked(seed, reproduction(corrections=[{"said": "Sarah Burnell", "heard": "Sara Boreal", "ticket": "T1"}]))
    assert any("is in no ticket" in p for p in problems)


def test_a_check_cannot_ask_for_a_null_argument(seed):
    checks = [{"type": "tool_called", "tool": "book_appointment", "args": {"patient_id": None}}]
    _, problems = checked(seed, reproduction(checks=checks))
    assert any("args.patient_id is null" in p for p in problems)


def test_a_turn_check_cannot_need_the_rest_of_the_call(seed):
    _, problems = checked(seed, reproduction(turn_check={"type": "call_ended"}))
    assert any("turn_check" in p for p in problems)
    _, problems = checked(seed, reproduction(turn_check={"type": "tool_called", "tool": "register_patient", "result": {"patient": "x"}}))
    assert any("cannot have a `result`" in p for p in problems)


# ---- candidates, the choice and the agreement -------------------------------------------------
def test_candidates_apply_and_differ(weak):
    value, problems = fix.check_candidates(candidates(), weak, {}, ["B3"], [])
    assert problems == [] and len(value["candidates"]) == 3
    assert "spell it letter by letter" in json.dumps(value["candidates"][0]["agent"])


def test_candidates_are_not_refused_for_the_agents_other_defects(weak):
    # The weak agent has no transfer_to_human in collect_reason and offer_times (a planted
    # defect): a fix of the name is not this fix's business, and is not refused for it.
    assert build.guide_problems(weak)
    _, problems = fix.check_candidates(candidates(), weak, {}, ["B3"], [])
    assert problems == []
    removed = candidates()
    removed["candidates"][2]["operations"] = [{"op": "set_tools", "node": "ask_name", "tools": []}]
    _, problems = fix.check_candidates(removed, weak, {}, ["B3"], [])
    assert any("missing in ask_name" in p for p in problems)


def test_candidates_must_be_three_different_and_never_name_the_caller(weak):
    same = candidates()
    same["candidates"][1] = copy.deepcopy(same["candidates"][0])
    _, problems = fix.check_candidates(same, weak, {}, ["B3"], [])
    assert any("does what candidate 1 does" in p for p in problems)
    _, problems = fix.check_candidates(candidates(candidates=candidates()["candidates"][:2]), weak, {}, ["B3"], [])
    assert any("exactly 3" in p for p in problems)
    named = candidates()
    named["candidates"][0]["operations"] = ask_name("If the caller is Sarah Burrell, spell it S-A-R-A-H.")
    test = {"id": "repro", "caller": {"facts": {"full_name": "Sarah Burrell"}}}
    _, problems = fix.check_candidates(named, weak, {}, ["B3"], [test])
    assert any("Sarah Burrell" in p for p in problems)


def entry(number, turn, full=0, ops=1):
    return {"number": number, "operations": [{}] * ops, "turn": {"passed": turn}, "full": {"passed": full}}


def test_the_best_full_reproduction_wins_and_the_turn_breaks_ties():
    # #33's real run: the turn replay ranked the candidates in reverse of the full reproduction.
    assert fix.choose([entry(1, 5, full=1), entry(2, 2, full=4), entry(3, 0, full=5)]) == 3
    assert fix.choose([entry(1, 3, full=5), entry(2, 5, full=5), entry(3, 5, full=5, ops=2)]) == 2
    assert fix.choose([entry(1, 0), entry(2, None)]) is None


def test_agreement_is_reported_per_candidate():
    report = fix.agreement([entry(1, 5, full=5), entry(2, 4, full=1), entry(3, None, full=0)], 5)
    assert report["rows"] == [{"candidate": 1, "turn": 5, "full": 5, "agree": True}, {"candidate": 2, "turn": 4, "full": 1, "agree": False}]
    assert (report["agreed"], report["of"], report["best_turn_is_best_full"]) == (1, 2, True)


# ---- a whole fix -------------------------------------------------------------------------------
def rollout(passed: int, k: int = 5) -> dict:
    runs = [{"passed": i < passed, "end_reason": "end_node", "divergence_turn": 7, "turns": [],
             "checks": [{"type": "tool_called", "tool": "register_patient", "pass": i < passed, "detail": "x"}]} for i in range(k)]
    return {"k": k, "passed": passed, "rate": f"{passed}/{k}", "runs": runs, "usage": {}}


def suite_result(test: dict, passed: bool, status: str | None = None) -> dict:
    status = status or ("pass" if passed else "fail")
    return {"test_id": test["id"], "title": test["title"], "tier": test["tier"], "status": status, "cached": False,
            "runs": [{"passed": passed, "turns": [], "checks": [], "end_reason": "end_node"}], "usage": {}}


class Fakes:
    """The continuations, turn replays and suite runs, scripted by what the agent says in ask_name."""

    def __init__(self, backcasts, turns, breaks=(), failing=(), flaky=()):
        self.backcasts, self.turns, self.breaks, self.failing = list(backcasts), dict(turns), set(breaks), set(failing)
        self.flaky = set(flaky)
        self.suites, self.sizes = [], []

    async def backcast(self, call_, agent, test, models, k):
        return rollout(self.backcasts.pop(0), k)

    async def turn_rate(self, call_, turn, agent, check, models, k):
        passed = next((p for text, p in self.turns.items() if text in json.dumps(agent)), 0)
        return {"passed": passed, "rate": f"{passed}/{k}", "samples": [], "usage": {}}

    async def run_suite(self, agent, tests, models, use_cache=True, clinic=None):
        fixed = "letter by letter" in json.dumps(next(n for n in agent["nodes"] if n["name"] == "ask_name"))
        self.suites.append(fixed)
        self.sizes.append(len(tests))
        passes = lambda t: (fixed or not t["id"].startswith("repro")) and not (fixed and t["id"] in self.breaks) and t["id"] not in self.failing  # noqa: E731
        flaky = lambda t: not fixed and t["id"] in self.flaky  # noqa: E731
        return [suite_result(t, passes(t), "flaky" if flaky(t) else None) for t in tests]


def run_fix(seed, weak, monkeypatch, fakes, *answers):
    for name in ("backcast", "turn_rate", "run_suite"):
        monkeypatch.setattr(fix, name, getattr(fakes, name))
    events = []
    base = build.saved_hash(seed.dir.parent.parent / "agents", "linden-grove")
    report = asyncio.run(fix.run(seed, CALL, TURN, weak, Scripted(*answers), simfakes.models(), events.append, base=base))
    return report, events


def test_an_issue_that_does_not_come_back_stops_before_any_candidate(seed, weak, monkeypatch):
    fakes = Fakes(backcasts=[5], turns={})
    report, events = run_fix(seed, weak, monkeypatch, fakes, answer(reproduction()))
    assert report["outcome"] == "not_reproduced" and "candidates" not in report
    assert seed.last_proposal() is None and seed.last_fix()["outcome"] == "not_reproduced"
    assert events[-1]["event"] == "done"


def test_no_candidate_that_changes_the_turn_stops_the_fix(seed, weak, monkeypatch):
    fakes = Fakes(backcasts=[0, 0, 0, 0], turns={})
    report, _ = run_fix(seed, weak, monkeypatch, fakes, answer(reproduction()), answer(candidates()))
    assert report["outcome"] == "no_candidate" and fakes.suites == []
    assert [c["full"]["passed"] for c in report["candidates"]] == [0, 0, 0]


def test_a_fix_goes_from_failing_to_passing_and_is_accepted(seed, weak, monkeypatch, tmp_path):
    fakes = Fakes(backcasts=[0, 5, 4, 1], turns={"then ask them to spell it": 5, "in one question": 4})
    report, events = run_fix(seed, weak, monkeypatch, fakes, answer(reproduction()), answer(candidates()))
    assert report["outcome"] == "proposal"
    proposal = seed.proposal(report["proposal"])
    assert proposal["kind"] == "fix" and proposal["status"] == "ready", proposal["blocked"]
    assert proposal["chosen"] == 1 and proposal["reproduction"]["before"]["failed"] == 5
    assert proposal["reproduction"]["after"]["rate"] == "5/5"  # the winner's full reproduction: no round changed it
    assert [c["turn"]["passed"] for c in proposal["candidates"]] == [5, 4, 0]
    assert [c["full"]["passed"] for c in proposal["candidates"]] == [5, 4, 1]
    assert proposal["agreement"]["agreed"] == 3
    before, after = proposal["results"]["before"], proposal["results"]["after"]
    assert after["passing"] == before["passing"] + 1 == after["total"]
    assert fakes.suites == [False, True]  # the current agent, then the winner; no rounds
    assert proposal["not_rerun"] == []  # every approved test passed on the (fake) current agent
    assert [e["event"] for e in events].count("candidate") == 6

    agents = tmp_path / "agents"
    version = build.accept(seed, proposal["number"], agents)
    assert version["number"] == 2 and "fixes wrong patient or name in call lg-1019-0804 (turn 4)" in version["message"]
    spec = seed.spec()
    repro = next(t for t in spec["tests"] if t["id"] == f"repro-{CALL}-t{TURN}")
    assert repro["status"] == "approved" and repro["hearing"]
    assert seed.fixed() == [{**seed.fixed()[0], "call": CALL, "turn": TURN, "kind": "wrong_patient", "version": 2}]
    saved = json.loads((agents / "linden-grove.json").read_text())
    assert "spell it letter by letter" in json.dumps(saved)
    assert not (seed.dir / "clinic.json").exists()  # a fix leaves the configuration alone

    app = FastAPI()
    app.include_router(detect_api.make_router(tmp_path / "logs", seed.dir.parent))
    issues = TestClient(app).get(f"/composer/calls/linden-grove/{CALL}").json()["judge"]["issues"]
    assert issues[0]["fixed"]["version"] == 2 and issues[1]["fixed"] is None


def test_a_fix_that_breaks_a_passing_test_is_blocked(seed, weak, monkeypatch):
    fakes = Fakes(backcasts=[0, 5, 4, 1], turns={"then ask them to spell it": 5}, breaks={"emergency-call-911"})
    # The loop's round tries a change and finds no failing test passes with it.
    no_change = {"diagnoses": [{"test": "emergency-call-911", "link": "overridden", "turn": 2, "explanation": "x", "question": None}],
                 "rationale": "x", "operations": [], "configuration": [], "concerns": []}
    report, _ = run_fix(seed, weak, monkeypatch, fakes, answer(reproduction()), answer(candidates()), answer(no_change))
    proposal = seed.proposal(report["proposal"])
    assert proposal["status"] == "blocked" and proposal["regressions"] == ["emergency-call-911"]
    assert any("emergency-call-911 passed on the current agent and fails now" in b for b in proposal["blocked"])


def test_tests_that_failed_before_the_fix_are_not_run_again(seed, weak, monkeypatch):
    fakes = Fakes(backcasts=[0, 5, 4, 1], turns={"then ask them to spell it": 5}, failing={"late-cancel-fee", "no-fee-cancel"})
    report, _ = run_fix(seed, weak, monkeypatch, fakes, answer(reproduction()), answer(candidates()))
    proposal = seed.proposal(report["proposal"])
    assert proposal["not_rerun"] == ["late-cancel-fee", "no-fee-cancel"]
    assert fakes.sizes == [27, 25] and proposal["status"] == "ready"


def test_a_test_flaky_before_the_fix_is_no_regression(seed, weak, monkeypatch):
    fakes = Fakes(backcasts=[0, 5, 4, 1], turns={"then ask them to spell it": 5}, breaks={"transfer-running-late"},
                  flaky={"transfer-running-late"})
    report, _ = run_fix(seed, weak, monkeypatch, fakes, answer(reproduction()), answer(candidates()))
    proposal = seed.proposal(report["proposal"])
    assert proposal["status"] == "ready" and proposal["regressions"] == []
    assert "transfer-running-late" in proposal["not_rerun"]


def test_the_api_refuses_an_issue_the_judge_did_not_find(seed, tmp_path):
    app = FastAPI()
    app.include_router(copilot_api.make_router(root=seed.dir.parent, agents_dir=tmp_path / "agents"))
    client = TestClient(app)
    response = client.post("/copilot/workspaces/linden-grove/fix", json={"call": CALL, "turn": 9})
    assert response.status_code == 404 and "turns: 4, 34" in response.json()["detail"]
    assert client.post("/copilot/workspaces/linden-grove/fix", json={"call": "nope", "turn": 4}).status_code == 404
    assert client.get("/copilot/workspaces/linden-grove/fixes/last").status_code == 404
