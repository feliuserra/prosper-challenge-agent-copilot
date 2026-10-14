import json
import math

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from detect import api, evaluate, signals, stats, synth, triage


# ---- the test --------------------------------------------------------------------------

def test_binomial_tail_matches_a_direct_sum():
    n, p = 40, 0.1
    for k in (0, 3, 4, 9, 40):
        direct = sum(math.comb(n, x) * p ** x * (1 - p) ** (n - x) for x in range(k, n + 1))
        assert stats.binomial_tail(k, n, p) == pytest.approx(direct, rel=1e-9)


def test_p_greater():
    assert stats.p_greater(20, 1000, 20, 1000) > 0.4  # the same rate
    assert stats.p_greater(90, 1000, 20, 1000) < 1e-9  # 9% against 2%
    assert stats.p_greater(10, 1000, 40, 1000) > 0.99  # lower, never flagged
    assert stats.p_greater(0, 100, 0, 100) == 1.0  # no events at all
    assert stats.p_greater(5, 0, 1, 100) == 1.0  # no calls
    # Against 1.2 times the baseline, a rate exactly 1.2 times it is not evidence.
    assert stats.p_greater(1200, 10_000, 1000, 10_000, ratio=1.2) > 0.4
    assert stats.p_greater(1200, 10_000, 1000, 10_000) < 1e-4


def test_small_counts_use_the_exact_tail():
    """17 of 148 against 669 of 13,970: the normal approximation would say 0.00008."""
    p = stats.p_greater(17, 148, 669, 13_970)
    assert 0.0005 < p < 0.002
    share = 148 / (148 + 13_970)
    assert p == pytest.approx(stats.binomial_tail(17, 686, share))


def test_holm():
    adjusted = stats.holm([0.01, 0.04, 0.03, 0.005])
    assert adjusted == pytest.approx([0.03, 0.06, 0.06, 0.02])


# ---- counting ----------------------------------------------------------------------------

def call(id, path, *, ended="completed", start="2026-09-01T10:00:00", end="2026-09-01T10:03:00", clinic="a",
         version=1, caller=None, tools=()):
    return {"id": id, "source": "synthetic", "clinic": clinic, "version": version, "start": start, "end": end,
            "caller": caller or f"555-{id}", "path": path, "tools": list(tools), "ended": ended}


MAIN = [["greeting", 1], ["ask_name", 1, "choose_intent"], ["confirm_name", 1, "record_spelling"]]


def test_a_loop_counts_where_it_starts():
    calls = [
        call("self", MAIN + [["confirm_name", 1, "correct_spelling"], ["verify_patient", 2, "name_confirmed"]], ended="hang_up"),
        call("back", MAIN + [["ask_name", 1, "spell_again"], ["confirm_name", 1, "record_spelling"]], ended="hang_up"),
        call("plain", MAIN, ended="hang_up"),
    ]
    counts = signals.count(calls)
    week = "2026-08-31"
    confirm = counts.cells[("a", 1, week, "confirm_name")]
    ask = counts.cells[("a", 1, week, "ask_name")]
    assert (confirm.k["reentry"], confirm.n["reentry"]) == (2, 3)
    assert confirm.events["reentry"] == ["self", "back"]
    assert ask.k["reentry"] == 0  # going on to Confirm name again is not a loop of its own
    assert ask.n["reentry"] == 3  # each call counts once, however often it entered
    assert confirm.exits == {"correct_spelling": 1, "name_confirmed": 1, "spell_again": 1}


def test_endings_stalls_and_tool_errors():
    calls = [
        call("1", [["greeting", 7]], ended="transfer"),
        call("2", [["greeting", 2], ["ask_name", 1, "choose_intent"]], ended="hang_up"),
        call("3", [["greeting", 1], ["verify_patient", 3, "x"]], ended="error",
             tools=[["verify_patient", "lookup_patient", False], ["verify_patient", "lookup_patient", False],
                    ["verify_patient", "register_patient", True]]),
    ]
    cells = signals.count(calls).cells
    greeting = cells[("a", 1, "2026-08-31", "greeting")]
    assert greeting.k["stall"] == 1 and greeting.k["transfer"] == 1 and greeting.k["hang_up"] == 0
    assert cells[("a", 1, "2026-08-31", "ask_name")].k["hang_up"] == 1
    verify = cells[("a", 1, "2026-08-31", "verify_patient")]
    assert verify.k["error"] == 1
    assert verify.k["tool_error"] == 1  # per call, not per failed call


def test_callbacks_follow_completed_calls_and_are_counted_when_known():
    calls = [
        call("done", MAIN + [["confirm", 1, "x"]], caller="555-1", start="2026-09-04T10:00:00", end="2026-09-04T10:05:00"),
        call("again", [["greeting", 1]], caller="555-1", ended="hang_up", start="2026-09-05T09:00:00", end="2026-09-05T09:01:00"),
        call("retry", [["greeting", 1]], caller="555-1", ended="hang_up", start="2026-09-05T12:00:00", end="2026-09-05T12:01:00"),
        call("late", MAIN + [["confirm", 1, "x"]], caller="555-2", start="2026-09-04T11:00:00", end="2026-09-04T11:05:00"),
        call("much later", [["greeting", 1]], caller="555-2", ended="hang_up", start="2026-09-07T12:00:00", end="2026-09-07T12:01:00"),
        call("too recent", MAIN + [["confirm", 1, "x"]], caller="555-3", start="2026-09-10T10:00:00", end="2026-09-10T10:05:00"),
        call("end", [["greeting", 1]], caller="555-9", ended="hang_up", start="2026-09-11T10:00:00", end="2026-09-11T10:01:00"),
    ]
    counts = signals.count(calls)
    # Calls on Friday 09-04 are known on Sunday 09-06: still the week of 08-31.
    cell = counts.cells[("a", 1, "2026-08-31", "confirm")]
    assert (cell.k["callback"], cell.n["callback"]) == (1, 2)
    assert cell.events["callback"] == ["done"]
    # Hang-ups are retried, which the hang-up already counts: no callback signal there.
    assert counts.total("a", node="greeting").n["callback"] == 0
    # Within 48 hours of the logs' end, a callback cannot be known yet.
    assert counts.total("a", node="confirm").n["callback"] == 2


def test_quick_changes_and_duplicates_come_from_the_records():
    calls = [
        call("b1", [["offer_times", 3]], tools=[["offer_times", "book_appointment", True]], start="2026-09-01T10:00:00"),
        call("b2", [["offer_times", 3]], tools=[["offer_times", "book_appointment", True]], start="2026-09-01T11:00:00"),
        call("r1", [["verify_patient", 2]], tools=[["verify_patient", "register_patient", True]], start="2026-09-02T10:00:00"),
        call("r2", [["verify_patient", 2]], tools=[["verify_patient", "register_patient", True]], start="2026-09-02T11:00:00"),
        call("last", [["greeting", 1]], ended="hang_up", start="2026-09-09T10:00:00"),
    ]
    records = [
        {"type": "booking", "clinic": "a", "id": "x1", "patient": None, "created": "2026-09-01T10:02:00", "call": "b1"},
        {"type": "booking", "clinic": "a", "id": "x2", "patient": None, "created": "2026-09-01T11:02:00", "call": "b2"},
        {"type": "booking_change", "clinic": "a", "booking": "x1", "at": "2026-09-01T18:00:00", "action": "cancelled", "call": None},
        {"type": "booking_change", "clinic": "a", "booking": "x2", "at": "2026-09-03T18:00:00", "action": "cancelled", "call": None},
        {"type": "patient", "clinic": "a", "id": "p1", "name": "Ana Lopez", "dob": "1984-03-12", "phone": "555-1",
         "created": None, "call": None},
        {"type": "patient", "clinic": "a", "id": "p2", "name": "Ana Lopes", "dob": "1984-03-12", "phone": "555-1",
         "created": "2026-09-02T10:01:00", "call": "r1"},
        {"type": "patient", "clinic": "a", "id": "p3", "name": "Mei Chen", "dob": "1992-06-30", "phone": "555-2",
         "created": "2026-09-02T11:01:00", "call": "r2"},
    ]
    counts = signals.count(calls, records)
    offer = counts.total("a", node="offer_times")
    assert (offer.k["quick_change"], offer.n["quick_change"]) == (1, 2)
    verify = counts.total("a", node="verify_patient")
    assert (verify.k["duplicate"], verify.n["duplicate"]) == (1, 2)
    assert counts.events("a", 1, ["2026-08-31"], "verify_patient", "duplicate") == ["r1"]


# ---- baselines and flags -----------------------------------------------------------------

def cell(k: dict, n: int, signal_n: dict | None = None) -> signals.Cell:
    c = signals.Cell()
    for signal in signals.ENTERED:
        c.n[signal] = n
    c.n.update(signal_n or {})
    c.k.update(k)
    return c


def world(spec: dict) -> signals.Counts:
    """Counts from {(clinic, version, week, node): (events, calls)} for re-entries."""
    counts = signals.Counts()
    for (clinic, version, week, node), (k, n) in spec.items():
        counts.cells[(clinic, version, week, node)] = cell({"reentry": k}, n)
        counts.versions[clinic].setdefault(version, {"from": week, "to": week, "calls": n})
    counts.weeks = sorted({key[2] for key in spec})
    counts.calls = sum(n for _, n in spec.values())
    return counts


W1, W2 = "2026-09-07", "2026-09-14"


def test_a_rise_after_a_version_change_is_flagged():
    counts = world({("a", 1, W1, "confirm_name"): (200, 10_000), ("a", 2, W2, "confirm_name"): (900, 10_000)})
    flags = triage.run(counts, W2)["flags"]
    assert [(f["signal"], f["baseline"], f["against"]) for f in flags] == [("reentry", "version", 1)]


def test_a_rise_below_the_minimum_effect_is_not_flagged():
    """1.12 times: significant at this volume, but under the 1.2 minimum."""
    counts = world({("a", 1, W1, "greeting"): (8_600, 100_000), ("a", 2, W2, "greeting"): (9_630, 100_000)})
    (test,) = triage.run(counts, W2)["tests"]
    assert test["significant"] and not test["big_enough"]
    assert triage.run(counts, W2)["flags"] == []


def test_against_the_fleet_a_clinic_must_be_well_above_it():
    counts = world({
        ("a", 1, W1, "offer_times"): (130, 1_000),  # 13% against 10%: clinics differ this much
        ("b", 1, W1, "offer_times"): (1_000, 10_000),
        ("c", 1, W1, "offer_times"): (400, 1_000),  # 40%: a leak
    })
    flags = triage.run(counts, W1)["flags"]
    assert [(f["clinic"], f["baseline"]) for f in flags] == [("c", "fleet")]


def test_a_customized_node_has_no_fleet_baseline():
    counts = world({("a", 1, W1, "ask_referral"): (300, 1_000), ("b", 1, W1, "greeting"): (10, 1_000)})
    assert [t for t in triage.run(counts, W1)["tests"] if t["node"] == "ask_referral"] == []


def test_few_events_are_never_enough():
    counts = world({("a", 1, W1, "confirm"): (0, 100), ("a", 2, W2, "confirm"): (4, 20)})
    run = triage.run(counts, W2)
    assert run["flags"] == []
    assert run["tests"][0]["k"] < triage.MIN_EVENTS


# ---- the demo logs: the acceptance criteria ----------------------------------------------

@pytest.fixture(scope="module")
def demo(demo_logs):
    calls, records, labels = demo_logs
    counts = signals.count(calls, records)
    result = triage.detect(counts)
    return calls, counts, result, labels, evaluate.evaluate(counts, result, labels)


def test_finds_the_planted_defects(demo):
    *_, evaluation = demo
    assert evaluation["recall"] >= 0.8
    assert [p["id"] for p in evaluation["planted"] if not p["found"]] == []


def test_at_most_one_false_alarm_per_clinic_per_week(demo):
    *_, evaluation = demo
    assert evaluation["false_per_clinic_week"] <= 1
    assert evaluation["false_alarms"] == []


def test_nothing_that_must_not_be_flagged_is(demo):
    *_, evaluation = demo
    for item in evaluation["must_not_flag"]:
        assert item["flags"] == [], item["id"]
    below = next(i for i in evaluation["must_not_flag"] if i["id"] == "below-min-effect")
    assert below["closest"]["significant"] and not below["closest"]["big_enough"]


def test_the_ranked_list(demo):
    _, counts, result, _, _ = demo
    issues = result["issues"]
    assert [(i["clinic"], i["node"], i["shape"]) for i in issues[:2]] == [
        ("riverside", "confirm_name", "stall"), ("riverside", "offer_times", "error")]
    stall = issues[0]
    assert stall["since_version"] == 3
    assert {(e["baseline"], e["against"]) for e in stall["evidence"]} == {("version", 2), ("fleet", "other clinics")}
    # The excess counts against the closer baseline: the other clinics' 2.4%, not version 2's 2.0%.
    assert stall["baseline"] == "fleet"
    assert 500 < stall["extra_per_week"] < 900  # about 6.5 points of 10,500 calls a week
    assert len(stall["examples"]) == triage.EXAMPLES
    assert {i["id"] for i in issues} == {"riverside:confirm_name:stall", "riverside:offer_times:error",
                                         "linden-grove:verify_patient:detour", "linden-grove:offer_times:leak",
                                         "maple-street:confirm:silent"}
    assert issues == sorted(issues, key=lambda i: -i["score"])
    text = triage.report(counts, result)
    assert "riverside, Confirm name: stall" in text


def test_the_tool_errors_started_in_version_2(demo):
    _, _, result, _, _ = demo
    errors = next(i for i in result["issues"] if i["id"] == "riverside:offer_times:error")
    assert (errors["version"], errors["since_version"]) == (3, 2)


def test_sweep_cell():
    """One cell of the recall sweep: a 5-point rise at a medium clinic is found."""
    (cell,) = evaluate.sweep(volumes=(1500,), excesses=(0.05,), trials=1, workers=1)
    assert cell["found"] == 1


# ---- the endpoint ------------------------------------------------------------------------

def client(data_dir) -> TestClient:
    app = FastAPI()
    app.include_router(api.make_router(data_dir))
    return TestClient(app)


def test_detection_without_logs(tmp_path):
    body = client(tmp_path).get("/composer/detection").json()
    assert body["available"] is False and "make synth" in body["reason"]


def test_detection_endpoint(tmp_path):
    scene = synth.scenario()
    for clinic in scene["clinics"]:
        clinic["calls_per_week"] //= 10
    synth.write(tmp_path, seed=5, scene=scene)
    body = client(tmp_path).get("/composer/detection").json()
    assert body["available"] is True
    assert [c["id"] for c in body["clinics"]] == ["linden-grove", "maple-street", "riverside"]
    assert [v["version"] for v in body["clinics"][2]["versions"]] == [1, 2, 3]
    confirm = body["nodes"]["riverside"]["3"]["confirm_name"]
    reentry = confirm["signals"]["reentry"]
    assert reentry["rate"] > reentry["version"]["rate"] * 2 and reentry["version"]["p"] < 1e-6
    assert set(confirm["exits"]) == {"name_confirmed", "correct_spelling", "spell_again"}
    assert "version" not in body["nodes"]["riverside"]["1"]["greeting"]["signals"]["hang_up"]  # no earlier version
    for issue in body["issues"]:
        assert all(call_id in body["example_calls"] for call_id in issue["examples"])
    assert body["signals"]["reentry"]["shape"] == "stall"
    json.dumps(body)


def test_detection_rereads_changed_logs(tmp_path):
    scene = synth.scenario()
    scene["clinics"] = scene["clinics"][2:]
    synth.write(tmp_path, seed=5, scene=scene)
    app = client(tmp_path)
    first = app.get("/composer/detection").json()["calls"]
    scene["clinics"][0]["calls_per_week"] *= 2
    synth.write(tmp_path, seed=5, scene=scene)
    assert app.get("/composer/detection").json()["calls"] > first
