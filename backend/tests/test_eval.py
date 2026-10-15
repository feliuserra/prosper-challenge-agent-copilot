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
