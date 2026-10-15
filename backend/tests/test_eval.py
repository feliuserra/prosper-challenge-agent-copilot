"""The reference suite (#27): clinic-a's files are valid and agree with each other, and
`make eval` runs them under the `eval` source. No model calls."""

import json
from pathlib import Path

import eval.__main__ as eval_cli
from agent_builder import validate_agent
from clinic import ClinicWorld, clinic_of, load_seed, validate_clinic
from sim.testfile import load_tests, validate_tests

CLINIC_A = Path(eval_cli.__file__).parent / "clinic-a"
AGENT = json.loads((CLINIC_A / "reference-agent.json").read_text())
TESTS = load_tests(CLINIC_A / "tests.json")


def test_the_clinic_file_is_valid():
    assert validate_clinic(load_seed("linden-grove")) == []


def test_the_reference_agent_is_valid_and_names_the_clinic():
    assert validate_agent(AGENT) == [] and clinic_of(AGENT) == "linden-grove"


def test_the_suite_is_valid_for_the_clinic():
    assert validate_tests(TESTS, "linden-grove") == []
    assert len(TESTS) == 20 and sum(t["tier"] == "safety" for t in TESTS) == 5


def test_the_tests_name_the_clinic_as_it_is():
    """Ids the tests check (patients, appointments, providers) exist in the seed."""
    seed = load_seed("linden-grove")
    ids = {p["id"] for p in seed["patients"]} | {a["id"] for a in seed["appointments"]} | {p["id"] for p in seed["providers"]}
    named = set()
    for test in TESTS:
        for check in test["checks"]:
            for key in ("patient_id", "appointment_id"):
                if key in check.get("args", {}):
                    named.add(check["args"][key])
            provider = check.get("result", {}).get("appointment", {}).get("provider_id")
            if provider:
                named.add(provider)
    assert named and named <= ids


def test_the_late_fee_tests_sit_on_either_side_of_the_window():
    world = ClinicWorld(load_seed("linden-grove"))
    fee = {a["appointment_id"]: a["late_change_fee"] for p in world.data["patients"] for a in world.lookup_patient(p["full_name"], p["date_of_birth"])["appointments"]}
    assert fee == {"appt-0001": 0, "appt-0002": 50, "appt-0003": 50, "appt-0004": 0}


def test_make_eval_runs_the_suite_under_the_eval_source(monkeypatch):
    calls = []
    monkeypatch.setattr(eval_cli, "run_tests", lambda *args: calls.append(args) or 0)
    assert eval_cli.main([]) == 0
    agent, tests, source, use_cache, only, out = calls[0]
    assert (agent, tests, source, use_cache, only) == (eval_cli.REFERENCE_AGENT, eval_cli.TESTS, "eval", True, None)
    assert out.parent == eval_cli.RESULTS and out.name.endswith("-reference-agent.json")
    eval_cli.main(["--agent", "agents/other.json", "--no-cache", "--only", "cancel-no-fee"])
    assert calls[1][0] == Path("agents/other.json") and calls[1][3] is False and calls[1][4] == ["cancel-no-fee"]


# ---- mutants ---------------------------------------------------------------------------------
def test_every_mutant_breaks_something_and_targets_existing_tests():
    from eval import mutants

    pairs = mutants.pairs(AGENT, TESTS)
    assert len(mutants.MUTANTS) == 15 and len(pairs) == 26 and mutants.uncovered(TESTS) == []
    by_id = {t["id"]: t for t in TESTS}
    for mutant, agent, test in pairs:
        assert validate_agent(agent) == [], mutant.id
        changed = agent != AGENT or test.get("world") != by_id[test["id"]].get("world")
        assert changed, f"{mutant.id} changes nothing"
    assert AGENT == json.loads((CLINIC_A / "reference-agent.json").read_text())  # applying copies


def test_a_mutant_edit_that_no_longer_matches_fails_loudly():
    import pytest

    from eval import mutants

    reworded = json.loads(json.dumps(AGENT))
    reworded["persona"] = reworded["persona"].replace("call 911 right away", "dial 911")
    with pytest.raises(ValueError, match="expected the text once"):
        mutants.MUTANTS[2].apply(reworded, TESTS[0])  # M3 cuts the emergency rule


def test_config_mutants_reach_the_tools_through_the_world():
    from eval import mutants

    by_id = {m.id: m for m in mutants.MUTANTS}
    seed = load_seed("linden-grove")
    _, test = by_id["M9"].apply(AGENT, next(t for t in TESTS if t["id"] == "physical-not-with-nina"))
    world = ClinicWorld({**seed, **test["world"]})
    assert world.call("find_slots", {"appointment_type": "annual_physical", "provider": "Nina"})["slots"]
    _, test = by_id["M11"].apply(AGENT, next(t for t in TESTS if t["id"] == "cancel-late-keeps-it"))
    world = ClinicWorld({**seed, **test["world"]})
    assert "fee_acknowledged" not in world.tool_spec("cancel_appointment").properties
    assert "cancelled" in world.call("cancel_appointment", {"appointment_id": "appt-0003"})


def check(passed, rule="r"):
    return {"type": "judge", "rule": rule, "pass": passed}


def test_only_checks_steady_on_the_reference_catch_a_mutant():
    from eval.mutants import catching_checks

    mutant = {"status": "fail", "runs": [{"checks": [check(False, "a"), check(False, "b"), check(True, "c")]}]}
    steady = {"status": "pass", "runs": [{"checks": [check(True), check(True), check(True)]}]}
    assert [c["rule"] for c in catching_checks(mutant, steady)] == ["a", "b"]
    flaky = {"status": "flaky", "runs": [{"checks": [check(False), check(True), check(True)]}, {"checks": [check(True)] * 3}]}
    assert [c["rule"] for c in catching_checks(mutant, flaky)] == ["b"]  # "a" was flaky on the reference
    assert catching_checks(mutant, {"status": "fail", "runs": steady["runs"]}) == []
    assert catching_checks({"status": "error", "runs": []}, steady) == []


def test_mutants_need_the_reference_results_cached(monkeypatch, tmp_path, capsys):
    from sim import config

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    assert eval_cli.main(["--mutants"]) == 2
    assert "run `make eval` first" in capsys.readouterr().err
    assert eval_cli.main(["--mutants", "--agent", "agents/other.json"]) == 2


# ---- judge calibration -----------------------------------------------------------------------
def test_the_labels_cover_every_judge_rule_with_both_outcomes():
    from eval import judge
    from sim.checks import render_transcript

    rules, labels = judge.load()
    suite_rules = {c["rule"] for t in TESTS for c in t["checks"] if c["type"] == "judge"}
    assert set(rules.values()) == suite_rules  # the rules as the suite writes them
    assert len(labels) == 32 and len({label["id"] for label in labels}) == 32
    for rule in rules:
        assert {label["label"] for label in labels if label["rule"] == rule} == {"pass", "fail"}, rule
    assert all(render_transcript(label["turns"]) for label in labels)
    # The suite's judge agreed with every real-run label when the run happened.
    recorded = [label for label in labels if label["judge"]]
    assert len(recorded) == 30 and all(label["judge"]["pass"] == (label["label"] == "pass") for label in recorded)


def test_calibration_measures_agreement_per_rule():
    import asyncio

    import simfakes
    from simfakes import verdict
    from eval import judge

    rules, labels = judge.load()
    some = [label for label in labels if label["rule"] == "J-emergency"]  # pass, pass, fail
    model = simfakes.Scripted(*(verdict(label["label"] == "pass") for label in some[:2]), verdict(True))
    rows, usage = asyncio.run(judge.grade(rules, some, "gpt-4.1-mini-2025-04-14", model))
    assert [r["agree"] for r in rows] == [True, True, False] and judge.agreement(rows) == {"J-emergency": (2, 3)}
    assert not judge.passes(rows)
    assert all(r["model"] == "gpt-4.1-mini-2025-04-14" and r["temperature"] == 0 for r in model.requests)
    assert rules["J-emergency"] in model.requests[0]["messages"][1]["content"]
    text = judge.report(rows, "gpt-4.1-mini-2025-04-14", usage)
    assert "J-emergency      2/3" in text and "labelled fail, judge said pass" in text
