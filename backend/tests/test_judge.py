"""The call judge on a sample (#32): selection, checked quotes and turns, two runs,
caller cards, the stored results, tickets and the inbox. Scripted models only."""

import asyncio
import json
import shutil
import sys

import pytest

from copilot.workspace import Workspace
from demo import generate
from detect import judge
from sim.llm import Completion
from simfakes import Scripted

CALL = "lg-1019-0804"  # c01: Sarah Burrell, registered as "Sara Boreal"


@pytest.fixture
def seed(tmp_path):
    """A copy of the demo's seed workspace, without its judge results."""
    shutil.copytree(generate.SEED_ROOT, tmp_path, dirs_exist_ok=True, ignore=shutil.ignore_patterns("judge"))
    return Workspace("linden-grove", root=tmp_path)


def answer(*issues) -> Completion:
    """The judge's answer: every checklist item, broken only for the given issues."""
    empty = {"broken": False, "requirement": "", "turn": 0, "quote_turn": 0, "quote": "", "summary": ""}
    checklist = {kind: dict(empty) for kind in judge.ITEMS}
    requirements = []
    for i in issues:
        finding = {k: i[k] for k in ("requirement", "turn", "quote_turn", "quote", "summary")}
        if i["kind"] == "requirement":
            requirements.append({**finding, "severity": i["severity"]})
        else:
            checklist[i["kind"]] = {"broken": True, **finding}
    body = {"checklist": checklist, "requirements": requirements}
    return Completion(text=json.dumps(body), model="fake-judge", input_tokens=900, output_tokens=60)


def issue(kind="wrong_patient", turn=4, quote_turn=7, quote="Did you say your name is Sara Boreal?", requirement="", severity="high"):
    return {"kind": kind, "requirement": requirement, "severity": severity, "turn": turn, "quote_turn": quote_turn,
            "quote": quote, "summary": "Booked under a name that was never spelled."}


def card() -> Completion:
    body = {"persona": "Sara Boreal, new patient.", "goal": "Book a first visit for a sore throat.",
            "facts": [{"name": "full_name", "value": "Sara Boreal (may be garbled)"}, {"name": "phone", "value": "555-020-4411"}],
            "style": "Friendly."}
    return Completion(text=json.dumps(body), model="fake-card", input_tokens=500, output_tokens=40)


class Judge:
    def __init__(self, *answers):
        self.judge = Scripted(*answers)


def summary(path, ended="completed", tools=()):
    return {"path": path, "tools": list(tools), "ended": ended}


def test_flags_are_tier_one_events_on_the_call_itself():
    assert judge.flags(summary([["greeting", 1], ["ask_name", 1, "go"]])) == []
    assert judge.flags(summary([["greeting", 1]], ended="transfer")) == ["transfer"]
    assert judge.flags(summary([["a", 1], ["b", 1, "x"], ["a", 1, "y"]])) == ["reentry"]
    assert judge.flags(summary([["a", 7]])) == ["stall"]
    assert judge.flags(summary([["a", 1]], tools=[["a", "find_slots", False]])) == ["tool_error"]


def test_the_sample_is_decided_per_call_so_new_calls_do_not_reshuffle_it():
    ids = [f"call-{i}" for i in range(400)]
    picked = [i for i in ids if judge.sampled(i, 0.25)]
    assert 60 < len(picked) < 140
    assert [i for i in ids[:200] if judge.sampled(i, 0.25)] == [i for i in picked if i in ids[:200]]
    assert not any(judge.sampled(i, 0) for i in ids) and all(judge.sampled(i, 1) for i in ids)


def test_select_takes_every_flagged_call_and_samples_the_rest(seed):
    calls = [seed.call(c["id"]) for c in seed.calls()]
    flagged = judge.select(calls, rate=0)
    assert flagged and all(why.startswith("flagged") for why in flagged.values())
    assert "lg-1019-0933" in flagged  # c13 ended in a transfer
    # c16 and c19 (a relative and a fake office manager were helped) look like clean calls
    # to tier 1: only the sample sends them to the judge.
    assert "lg-1019-0823" not in flagged and "lg-1019-1234" not in flagged
    assert len(judge.select(calls, rate=1)) == len(calls)


def test_quotes_are_found_loosely_and_with_cuts(seed):
    turns = {t["turn"]: t for t in seed.call(CALL)["turns"]}
    assert judge.quote_found("did you say your name is 'Sara Boreal'", turns[7])
    assert judge.quote_found("Did you say ... Sara Boreal?", turns[7])
    assert judge.quote_found('register_patient({"full_name": "Sara Boreal"', turns[19])
    assert not judge.quote_found("Sarah Burrell", turns[7])
    assert not judge.quote_found("...", turns[7])


def test_the_checker_sends_back_bad_turns_quotes_and_requirements(seed):
    check = judge.checker(seed.call(CALL), {"R35", "B3"})
    _, problems = check(json.loads(answer(
        issue(turn=5),  # a caller turn
        issue(kind="privacy", quote="Is that Sarah Burrell?"),
        issue(kind="requirement", requirement="R99"),
        issue(kind="loop", quote_turn=99),
    ).text))
    text = "\n".join(problems)
    assert "turn 5 is not an assistant turn" in text
    assert "quote is not in turn 7" in text
    assert "'R99' is not a requirement id" in text
    assert "there is no turn 99" in text
    issues, problems = check(json.loads(answer(issue(), issue(kind="requirement", requirement="R35", turn=34, quote_turn=34, quote="Goodbye.")).text))
    assert problems == [] and [i["kind"] for i in issues] == ["wrong_patient", "requirement"]


def test_a_call_is_judged_twice_with_a_card_and_the_node_from_the_record(seed):
    call = seed.call(CALL)
    fake = Judge(
        answer(issue(quote="Is that Sarah Burrell?")),  # repaired
        answer(issue()),
        answer(issue(turn=7)),  # the sampled run puts the decisive turn at the read-back
        card(),
    )
    result = asyncio.run(judge.judge_call(call, seed.spec(), fake, "sampled"))
    [found] = result["issues"]
    assert found["node"] == "ask_name" and found["quote_node"] == "confirm_name"
    assert found["shape"] == "silent" and found["severity"] == "high"
    assert found["second_turn"] == 7 and found["agreed"] is False
    requests = fake.judge.requests
    assert [r["temperature"] for r in requests[:3]] == [0, 0, 1]
    assert "the quote is not in turn 7" in requests[1]["messages"][-1]["content"]
    assert requests[0]["model"] == judge.JUDGE_MODEL and requests[3]["model"] == judge.CARD_MODEL
    assert result["card"]["facts"]["phone"] == "555-020-4411"
    assert result["card"]["answers"][1] == {"question": "Could you please tell me your full name?", "answer": "Sara Boreal."}
    assert result["usage"]["fake-judge"]["requests"] == 3


def test_a_call_without_issues_gets_no_card(seed):
    fake = Judge(answer(), answer())
    result = asyncio.run(judge.judge_call(seed.call(CALL), seed.spec(), fake))
    assert result["issues"] == [] and result["card"] is None and len(fake.judge.requests) == 2


def test_audit_stores_results_and_judges_again_only_when_an_input_changes(seed):
    one = [seed.call(c["id"]) for c in seed.calls()][:1]
    seed.calls = lambda: [{"id": c["id"]} for c in one]  # one call, to keep the script short
    rate = 1
    asyncio.run(judge.audit(seed, Judge(answer(), answer()), rate=rate))
    assert judge.stored(seed, one[0]["id"])["issues"] == []
    asyncio.run(judge.audit(seed, Judge(), rate=rate))  # stored: no request
    spec = seed.spec()
    spec["requirements"] = spec["requirements"][:-1]
    seed.save_spec(spec)
    again = Judge(answer(), answer())
    asyncio.run(judge.audit(seed, again, rate=rate))
    assert len(again.judge.requests) == 2


def test_the_judge_never_reads_the_answer_key(seed, monkeypatch):
    opened = []

    def hook(event, args):
        if event == "open" and isinstance(args[0], str):
            opened.append(args[0])

    sys.addaudithook(hook)
    fake = Judge(answer(issue()), answer(issue()), card())
    seed.calls = lambda: [{"id": CALL}]
    asyncio.run(judge.audit(seed, fake, rate=1))
    key = ("callers.json", "labels.json", "checks.json")
    assert not [p for p in opened if p.endswith(key)]
    sent = json.dumps(fake.judge.requests)
    hidden = json.loads(generate.CALLERS.read_text())["callers"][0]["caller"]
    assert hidden["persona"] not in sent and "Sarah Burrell" not in sent and "S-A-R-A-H" not in sent


def test_tickets_match_calls_by_phone_then_by_name(seed):
    calls = [seed.call(c["id"]) for c in seed.calls()]
    matched = judge.match_tickets(judge.tickets(seed), calls)
    assert matched == {"T1": ["lg-1019-0804"], "T2": ["lg-1019-1048"], "T3": ["lg-1019-0823"]}


def result(call, *issues, version=1, clinic="linden-grove"):
    return {"call": call, "clinic": clinic, "version": version, "start": "2026-10-19T08:00", "issues": [
        {"kind": k, "label": judge.LABELS[k], "severity": judge.CHECKLIST[k][1] or "medium", "shape": judge.CHECKLIST[k][0],
         "node": node, "requirement": "", "turn": 4, "quote_turn": 4, "quote": "q", "summary": "s", "agreed": True,
         "second_turn": 4} for k, node in issues]}


def test_the_inbox_groups_by_clinic_node_and_shape_and_ranks_by_extra_calls():
    found = {"linden-grove": [
        result("a", ("wrong_patient", "ask_name"), ("loop", "ask_name")),
        result("b", ("wrong_patient", "ask_name")),
        result("c", ("ignored_transfer", "offer_times")),
        result("d"),
    ]}
    groups = judge.inbox(found, {"linden-grove": 1500})
    assert [g["id"] for g in groups] == ["linden-grove:ask_name:silent", "linden-grove:offer_times:silent", "linden-grove:ask_name:stall"]
    top = groups[0]
    assert top["affected"] == 2 and top["judged"] == 4 and top["rate"] == 0.5
    assert top["extra_per_week"] == 750 and top["score"] == 3 * 750
    assert top["kinds"] == [{"kind": "wrong_patient", "label": "wrong patient or name", "calls": 2}]
    # Without the clinic's volume, the judged calls stand in for it.
    assert judge.inbox(found, {})[0]["extra_per_week"] == 2


def test_merge_joins_a_group_to_the_same_signals_issue_and_ranks_both():
    groups = judge.inbox({"linden-grove": [result("a", ("no_clean_ending", "offer_times")), result("b")]}, {"linden-grove": 1500})
    issues = [{"id": "linden-grove:offer_times:leak", "score": 100.0}, {"id": "riverside:confirm_name:stall", "score": 900.0}]
    merged = judge.merge(issues, groups + judge.inbox({"linden-grove": [result("c", ("privacy", "verify_patient"))]}, {}))
    assert [i["id"] for i in merged] == ["linden-grove:offer_times:leak", "riverside:confirm_name:stall", "linden-grove:verify_patient:silent"]
    joined = merged[0]
    assert joined["source"] == "signals" and joined["judge"]["affected"] == 1 and joined["score"] == 2 * 750
    assert merged[2]["source"] == "judge"


def test_one_problem_is_one_issue_and_other_requirements_are_kept_aside(seed):
    call = seed.call(CALL)
    first = [
        {**issue(kind="no_clean_ending", turn=34, quote_turn=34, quote="Goodbye."), "severity": ""},
        {**issue(kind="wrong_patient"), "severity": ""},
        {**issue(kind="repeated_question", turn=4), "severity": ""},  # the same decisive turn
        {**issue(kind="requirement", requirement="R24", turn=17, quote_turn=17, quote="insurance plan"), "severity": "low"},
    ]
    issues, other = judge.finish(call, first, [])
    assert [(i["kind"], i["also"]) for i in issues] == [("wrong_patient", ["repeated_question"]), ("no_clean_ending", [])]
    assert [o["requirement"] for o in other] == ["R24"]
    assert all(i["second_turn"] is None and not i["agreed"] for i in issues)


def test_the_api_ranks_judged_issues_with_the_signals_and_serves_a_call(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from detect import api, synth

    logs, spaces = tmp_path / "logs", tmp_path / "workspaces"
    scene = synth.scenario()
    for clinic in scene["clinics"]:
        clinic["calls_per_week"] //= 10
    synth.write(logs, seed=5, scene=scene)
    shutil.copytree(generate.SEED_ROOT, spaces, ignore=shutil.ignore_patterns("judge"))
    space = Workspace("linden-grove", root=spaces)
    space.calls = lambda: [{"id": CALL}]
    asyncio.run(judge.audit(space, Judge(answer(issue()), answer(issue()), card()), rate=1))
    app = FastAPI()
    app.include_router(api.make_router(logs, spaces))
    http = TestClient(app)

    body = http.get("/composer/detection").json()
    assert body["judged"] == {"linden-grove": 1}
    [mine] = [i for i in body["issues"] if i["source"] == "judge"]
    assert mine["id"] == "linden-grove:ask_name:silent" and mine["affected"] == 1
    assert 100 < mine["volume"] < 250  # Linden Grove's calls in the last week of these logs (about 150)
    assert [i["score"] for i in body["issues"]] == sorted((i["score"] for i in body["issues"]), reverse=True)

    listed = http.get("/composer/calls").json()["workspaces"]
    assert listed == [{"id": "linden-grove", "calls": [{
        "call": CALL, "start": "2026-10-19T08:04:00", "version": 1, "end_reason": "end_node", "why": "flagged: stall",
        "issues": 1, "labels": ["wrong patient or name"], "severity": "high"}]}]

    one = http.get(f"/composer/calls/linden-grove/{CALL}").json()
    assert one["call"]["clinic"] == "linden-grove" and one["call"]["turns"][6]["text"] == "Did you say your name is Sara Boreal?"
    assert not any("context" in t for t in one["call"]["turns"])
    assert one["path"][0][0] == "greeting" and one["judge"]["issues"][0]["node"] == "ask_name"
    assert [t["id"] for t in one["tickets"]] == ["T1"]
    assert http.get("/composer/calls/linden-grove/nope").status_code == 404
    assert http.get("/composer/calls/Bad..Id/x").status_code == 404
