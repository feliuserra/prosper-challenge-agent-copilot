"""Clinic configuration (ADR 0016, #43): the loader, the rules the tools enforce on
Riverside's seed, the schemas built per clinic, and choosing a clinic per agent."""

import asyncio
import copy
import json
import shutil
from pathlib import Path

import pytest

import simfakes
from agent_builder import AgentBuilder, validate_agent
from clinic import ClinicWorld, LiveClinic, clinic_ids, clinic_of, load_seed, seed_path, validate_clinic
from clinic import clinics as clinics_module
from simfakes import caller, say
from sim.runner import cache_key, simulate
from sim.testfile import resolve_world, validate_tests

FIXTURES = Path(__file__).parent / "fixtures"
PLAIN = json.loads((FIXTURES / "clinic-plain.json").read_text())


@pytest.fixture
def riverside() -> ClinicWorld:
    return ClinicWorld(load_seed("riverside"))


@pytest.fixture
def plain() -> ClinicWorld:
    return ClinicWorld(PLAIN)


@pytest.fixture
def two_clinics(tmp_path, monkeypatch):
    """Riverside and the #25 clinic without configuration, as two registered clinics."""
    shutil.copy(seed_path("riverside"), tmp_path / "riverside.json")
    shutil.copy(FIXTURES / "clinic-plain.json", tmp_path / "plain.json")
    monkeypatch.setattr(clinics_module, "CLINICS_DIR", tmp_path)


def book(world, **args) -> dict:
    defaults = {"patient_id": "pat-001", "reason": "Check-up", "appointment_type": "checkup", "interpreter": "none"}
    return world.call("book_appointment", {**defaults, **args})


def providers_of(result: dict) -> set[str]:
    return {slot["provider_id"] for slot in result["slots"]}


# ---- the loader --------------------------------------------------------------------


def test_riverside_and_the_plain_clinic_are_valid():
    assert validate_clinic(load_seed("riverside")) == []
    assert validate_clinic(PLAIN) == []


def broken_clinic() -> dict:
    data = load_seed("riverside")
    data["policies"] = {}
    data["appointment_types"].append(copy.deepcopy(data["appointment_types"][0]))  # a second "checkup"
    data["appointment_types"][0]["providers"].append("dr-nobody")
    data["appointment_types"][2]["patients"] = "kids"
    data["appointment_types"][3]["providers"] = []
    data["insurance_plans"][0]["covers"].append("dental")
    del data["insurance_plans"][1]["name"]
    data["registration_fields"][0]["name"] = "Insurance Plan"
    data["booking_fields"] = [{"name": "reason", "description": "Again."}, {"name": "pharmacy", "required": "yes"}]
    data["cancellation"]["fee"] = -5
    data["facts"]["parking"] = ""
    data["patients"][0]["last_visit"] = "last spring"
    data["appointments"][0]["appointment_type"] = "surgery"
    return data


def test_the_loader_reports_every_planted_error_with_its_path():
    issues = validate_clinic(broken_clinic())
    assert sorted(i.path for i in issues) == sorted([
        "policies",
        "appointment_types[0].providers[2]",
        "appointment_types[5].id",
        "appointment_types[2].patients",
        "appointment_types[3].providers",
        "insurance_plans[0].covers[5]",
        "insurance_plans[1].name",
        "registration_fields[0].name",
        "booking_fields[0].name",
        "booking_fields[1].description",
        "booking_fields[1].required",
        "cancellation.fee",
        "facts.parking",
        "patients[0].last_visit",
        "appointments[0].appointment_type",
    ])
    messages = {i.path: i.message for i in issues}
    assert messages["appointment_types[0].providers[2]"] == "Unknown provider 'dr-nobody'."
    assert messages["booking_fields[0].name"] == "'reason' is already a tool parameter or a record key."


def test_the_loader_needs_an_object():
    assert [i.to_dict() for i in validate_clinic([])] == [{"path": "", "message": "A clinic must be a JSON object."}]


# ---- appointment types and providers ---------------------------------------------------


def test_list_appointment_types(riverside):
    types = riverside.call("list_appointment_types", {})["appointment_types"]
    assert [t["appointment_type"] for t in types] == ["checkup", "new_patient", "sick_visit", "follow_up", "vaccination"]
    new_patient = types[1]
    assert new_patient["for"] == "new patients only"
    assert new_patient["providers"] == ["Dr. Priya Patel"]


def test_a_clinic_without_types_says_so(plain):
    assert plain.call("list_appointment_types", {}) == {
        "appointment_types": [],
        "note": "This clinic does not use appointment types: any open slot will do.",
    }


def test_find_slots_needs_a_type_when_the_clinic_has_types(riverside):
    assert riverside.call("find_slots", {}) == {"error": "Missing appointment_type."}


def test_find_slots_offers_only_providers_who_do_the_type(riverside):
    assert providers_of(riverside.call("find_slots", {"appointment_type": "vaccination"})) == {"np-kim"}
    result = riverside.call("find_slots", {"appointment_type": "checkup", "date_to": "2026-10-18"})
    assert providers_of(result) <= {"dr-patel", "dr-okafor"} and result["slots"]


def test_find_slots_for_a_provider_who_does_not_do_the_type(riverside):
    error = riverside.call("find_slots", {"appointment_type": "new_patient", "provider": "Okafor"})["error"]
    assert error.startswith("Dr. Daniel Okafor does not do New patient visit.")
    assert error.endswith("providers who do: Dr. Priya Patel.")


def test_an_unknown_type_lists_the_types(riverside):
    error = riverside.call("find_slots", {"appointment_type": "dental"})["error"]
    assert error.startswith("Unknown appointment_type 'dental'. Types: checkup (Annual check-up), new_patient")


def test_book_with_a_provider_who_does_not_do_the_type(riverside):
    result = book(riverside, slot_id="np-kim-2026-10-13-1200", appointment_type="checkup")
    assert result["error"].startswith("Grace Kim does not do Annual check-up.")


def test_a_type_for_new_patients_refuses_an_existing_patient(riverside):
    result = book(riverside, slot_id="dr-patel-2026-10-12-0900", appointment_type="new_patient")
    assert result["error"] == (
        "New patient visit is for new patients only, and Ana Lopez has been seen here before. "
        "Types open to them: Annual check-up, Sick visit, Follow-up, Vaccination."
    )


def test_a_type_for_existing_patients_refuses_a_new_patient(riverside):
    patient = riverside.call(
        "register_patient",
        {"full_name": "Feliu Serra", "date_of_birth": "1990-05-04", "phone": "555-010-7777", "insurance_plan": "Aetna"},
    )["patient"]
    assert patient["new_patient"] is True
    result = book(riverside, patient_id=patient["patient_id"], slot_id="dr-patel-2026-10-12-0900", appointment_type="follow_up")
    assert result["error"].startswith("Follow-up is for existing patients only, and Feliu Serra is new to the clinic.")
    assert result["error"].endswith("Types open to them: Annual check-up, New patient visit, Sick visit, Vaccination.")


def test_book_stores_the_type_and_the_clinic_fields(riverside):
    result = book(riverside, slot_id="dr-patel-2026-10-12-0900", interpreter="Spanish")
    assert result["appointment"]["appointment_type"] == "checkup"
    assert result["appointment"]["type_name"] == "Annual check-up"
    stored = riverside.to_dict()["appointments"][-1]
    assert stored["appointment_type"] == "checkup" and stored["details"] == {"interpreter": "Spanish"}


def test_book_needs_the_clinic_booking_fields(riverside):
    args = {"patient_id": "pat-001", "slot_id": "dr-patel-2026-10-12-0900", "reason": "x", "appointment_type": "checkup"}
    assert riverside.call("book_appointment", args) == {"error": "Missing interpreter."}


def test_reschedule_keeps_to_providers_who_do_the_type(riverside):
    # Ana's check-up is with Dr. Patel; Grace Kim does not do check-ups.
    result = riverside.call("reschedule_appointment", {"appointment_id": "appt-0001", "new_slot_id": "np-kim-2026-10-15-1200"})
    assert result["error"].startswith("Grace Kim does not do Annual check-up.")


# ---- registration ------------------------------------------------------------------------


def test_register_needs_the_clinic_registration_fields(riverside):
    args = {"full_name": "Feliu Serra", "date_of_birth": "1990-05-04", "phone": "555-010-7777"}
    assert riverside.call("register_patient", args) == {"error": "Missing insurance_plan."}


def test_register_stores_the_clinic_fields_and_lookup_shows_them(riverside):
    args = {"full_name": "Feliu Serra", "date_of_birth": "1990-05-04", "phone": "555-010-7777", "insurance_plan": "self-pay"}
    riverside.call("register_patient", args)
    patient = riverside.call("lookup_patient", {"full_name": "Feliu Serra", "date_of_birth": "1990-05-04"})["patient"]
    assert patient["insurance_plan"] == "self-pay" and patient["new_patient"] is True


def test_lookup_shows_existing_patients_their_plan_and_last_visit(riverside):
    result = riverside.call("lookup_patient", {"full_name": "Ana Lopez", "date_of_birth": "1984-03-12"})
    assert result["patient"]["new_patient"] is False
    assert result["patient"]["insurance_plan"] == "blue-shield-ppo"
    assert result["patient"]["last_visit"] == "2025-10-20"


# ---- coverage and clinic facts ------------------------------------------------------------


@pytest.mark.parametrize(
    "plan, kind, covered",
    [("Blue Shield PPO", "checkup", True), ("aetna hmo", "checkup", False), ("Aetna", "sick_visit", True), ("medicare", "new_patient", False)],
)
def test_check_coverage(riverside, plan, kind, covered):
    result = riverside.call("check_coverage", {"insurance_plan": plan, "appointment_type": kind})
    assert result["accepted"] is True and result["covered"] is covered


def test_coverage_without_a_type_lists_what_the_plan_covers(riverside):
    result = riverside.call("check_coverage", {"insurance_plan": "Aetna HMO"})
    assert result == {"accepted": True, "insurance_plan": "Aetna HMO", "covers": ["Sick visit", "Follow-up", "Vaccination"]}


def test_an_unknown_plan_answers_with_the_accepted_plans(riverside):
    result = riverside.call("check_coverage", {"insurance_plan": "Cigna", "appointment_type": "checkup"})
    assert result == {"accepted": False, "insurance_plan": "Cigna", "accepted_plans": ["Blue Shield PPO", "Aetna HMO", "Medicare"]}


def test_coverage_with_an_unknown_type(riverside):
    assert riverside.call("check_coverage", {"insurance_plan": "Medicare", "appointment_type": "dental"})["error"].startswith(
        "Unknown appointment_type 'dental'."
    )


def test_a_clinic_without_plans_cannot_check_coverage(plain):
    assert "no insurance plans on file" in plain.call("check_coverage", {"insurance_plan": "Medicare"})["error"]


def test_get_clinic_info(riverside, plain):
    info = riverside.call("get_clinic_info", {})
    assert info["clinic"] == "Riverside Family Clinic"
    assert info["facts"]["parking"] == "Free parking behind the building."
    assert plain.call("get_clinic_info", {})["note"].startswith("No details on file.")


# ---- the late-change fee ---------------------------------------------------------------------


def test_a_late_cancellation_needs_the_fee_acknowledged(riverside):
    # James O'Connor's appointment starts in 2.5 hours, inside Riverside's 24-hour window.
    result = riverside.call("cancel_appointment", {"appointment_id": "appt-0002"})
    assert result == {
        "error": "A $50 fee applies to cancelling or moving an appointment less than 24 hours before it starts, and "
        "this one starts in 2.5 hours. Tell the caller about the fee, and call again with fee_acknowledged true "
        "only if they agree to pay it."
    }
    assert riverside.to_dict()["appointments"][1]["status"] == "booked"


@pytest.mark.parametrize("acknowledged", [True, "true"])
def test_a_late_cancellation_with_the_fee_acknowledged(riverside, acknowledged):
    result = riverside.call("cancel_appointment", {"appointment_id": "appt-0002", "fee_acknowledged": acknowledged})
    assert result["fee_charged"] == 50
    stored = riverside.to_dict()["appointments"][1]
    assert stored["status"] == "cancelled" and stored["fee_charged"] == 50


def test_fee_acknowledged_false_is_still_refused(riverside):
    assert "error" in riverside.call("cancel_appointment", {"appointment_id": "appt-0002", "fee_acknowledged": False})


def test_no_fee_outside_the_window(riverside):
    # Ana's check-up is two days away.
    result = riverside.call("cancel_appointment", {"appointment_id": "appt-0001"})
    assert "fee_charged" not in result and result["cancelled"]["appointment_id"] == "appt-0001"


def test_a_late_reschedule_needs_the_fee_acknowledged(riverside):
    args = {"appointment_id": "appt-0002", "new_slot_id": "dr-okafor-2026-10-14-0800"}
    assert riverside.call("reschedule_appointment", args)["error"].startswith("A $50 fee applies")
    result = riverside.call("reschedule_appointment", {**args, "fee_acknowledged": True})
    assert result["fee_charged"] == 50 and result["appointment"]["date"] == "2026-10-14"


def test_lookup_shows_the_fee_a_change_would_cost_now(riverside):
    james = riverside.call("lookup_patient", {"full_name": "James O'Connor", "date_of_birth": "1957-11-02"})
    ana = riverside.call("lookup_patient", {"full_name": "Ana Lopez", "date_of_birth": "1984-03-12"})
    assert james["appointments"][0]["late_change_fee"] == 50
    assert ana["appointments"][0]["late_change_fee"] == 0


def test_a_clinic_without_a_fee_ignores_fee_acknowledged(plain):
    result = plain.call("cancel_appointment", {"appointment_id": "appt-0002", "fee_acknowledged": True})
    assert "fee_charged" not in result and result["cancelled"]["appointment_id"] == "appt-0002"


# ---- schemas built per clinic --------------------------------------------------------------------


def test_the_schema_follows_the_clinic(riverside, plain):
    book_spec = riverside.tool_spec("book_appointment")
    assert book_spec.properties["appointment_type"]["enum"] == ["checkup", "new_patient", "sick_visit", "follow_up", "vaccination"]
    assert book_spec.required == ("patient_id", "slot_id", "reason", "appointment_type", "interpreter")
    assert "insurance_plan" in riverside.tool_spec("register_patient").required
    assert "fee_acknowledged" in riverside.tool_spec("cancel_appointment").properties

    plain_book = plain.tool_spec("book_appointment")
    assert "appointment_type" not in plain_book.properties and "interpreter" not in plain_book.properties
    assert "fee_acknowledged" not in plain.tool_spec("cancel_appointment").properties
    assert "appointment_type" not in plain.tool_spec("find_slots").properties


def function_schema(builder: AgentBuilder, node: str, tool: str) -> dict:
    [function] = [f for f in builder.build_node(node)["functions"] if f.name == tool]
    return function.to_function_schema().to_default_dict()["parameters"]


def test_the_same_template_builds_against_two_clinics_with_their_schemas(example, riverside, plain):
    at_riverside = AgentBuilder.from_dict(example, riverside)
    at_plain = AgentBuilder.from_dict(example, plain)
    riverside_book = function_schema(at_riverside, "offer_times", "book_appointment")
    plain_book = function_schema(at_plain, "offer_times", "book_appointment")
    assert set(riverside_book["properties"]) - set(plain_book["properties"]) == {"appointment_type", "interpreter"}
    assert "interpreter" in riverside_book["required"] and "interpreter" not in plain_book["required"]
    riverside_cancel = function_schema(at_riverside, "manage_appointment", "cancel_appointment")
    assert "fee_acknowledged" in riverside_cancel["properties"]


def test_the_runner_offers_the_model_the_clinic_schemas(example, riverside):
    from sim.conversation import Conversation

    conversation = Conversation(example, riverside, simfakes.models())
    conversation._enter(conversation.builder.build_node("offer_times"))
    [tool] = [t["function"] for t in conversation.tools if t["function"]["name"] == "book_appointment"]
    assert tool["parameters"] == function_schema(AgentBuilder.from_dict(example, riverside), "offer_times", "book_appointment")
    assert "interpreter" in tool["parameters"]["properties"]


# ---- clinics per agent ---------------------------------------------------------------------------


def test_riverside_is_a_clinic_and_the_default():
    assert "riverside" in clinic_ids()
    assert clinic_of({"name": "x"}) == "riverside"
    assert clinic_of({"clinic": "plain"}) == "plain"
    with pytest.raises(KeyError, match="Unknown clinic 'nowhere'"):
        seed_path("nowhere")


def test_an_agent_naming_an_unknown_clinic_is_invalid(example):
    example["clinic"] = "nowhere"
    [issue] = validate_agent(example)
    assert issue.message.startswith("Unknown clinic 'nowhere'. Clinics: ")
    example["clinic"] = "riverside"
    assert validate_agent(example) == []


def test_live_state_is_kept_per_clinic(two_clinics, tmp_path):
    state = tmp_path / "state"
    riverside, plain = LiveClinic.for_clinic("riverside", state), LiveClinic.for_clinic("plain", state)
    assert "error" not in plain.call("cancel_appointment", {"appointment_id": "appt-0001"})
    assert (state / "plain.json").exists() and not (state / "riverside.json").exists()
    assert riverside.call("lookup_patient", {"full_name": "Ana Lopez", "date_of_birth": "1984-03-12"})["appointments"]


def test_the_runner_uses_the_agent_clinic(two_clinics, example):
    test = {"id": "t", "title": "t", "tier": "core", "caller": {"persona": "p", "goal": "g"}, "checks": [{"type": "transferred"}]}
    models = simfakes.models(agent=[say("Hello, how can I help?")], caller=[caller("Bye.", hang_up=True)])
    at_plain = {**example, "clinic": "plain"}
    record = asyncio.run(simulate(at_plain, test, models))
    assert record["world"] == resolve_world(test, "plain")
    assert "appointment_types" not in record["world"]
    assert cache_key(at_plain, test) != cache_key(example, test)


def test_tests_are_checked_against_the_clinic_schemas(two_clinics):
    test = {
        "id": "late-cancel",
        "title": "A late cancellation",
        "tier": "core",
        "caller": {"persona": "p", "goal": "g"},
        "world": {"cancellation": {"window_hours": 48, "fee": 75}},
        "checks": [{"type": "tool_called", "tool": "book_appointment", "args": {"interpreter": "none", "appointment_type": "checkup"}}],
    }
    assert validate_tests([test], "riverside") == []
    errors = validate_tests([test], "plain")
    assert errors == [
        "late-cancel: check 1: book_appointment has no parameter 'interpreter'.",
        "late-cancel: check 1: book_appointment has no parameter 'appointment_type'.",
    ]


def test_a_test_world_with_a_broken_configuration_is_reported():
    test = {
        "id": "broken",
        "title": "Broken",
        "tier": "core",
        "caller": {"persona": "p", "goal": "g"},
        "world": {"insurance_plans": [{"id": "x", "name": "X", "covers": ["dental"]}]},
        "checks": [{"type": "transferred"}],
    }
    assert validate_tests([test]) == ["broken: world: insurance_plans[0].covers[0]: Unknown appointment type 'dental'."]
