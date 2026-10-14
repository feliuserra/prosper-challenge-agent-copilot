import json
from pathlib import Path

import pytest

from clinic import TOOLS, ClinicWorld, LiveClinic, catalog
from clinic.world import MAX_SLOTS

# The #25 clinic, without configuration (ADR 0016): every tool must behave as it did then.
SEED = Path(__file__).parent / "fixtures" / "clinic-plain.json"


@pytest.fixture
def world() -> ClinicWorld:
    return ClinicWorld.from_file(SEED)


def slot_ids(result: dict) -> list[str]:
    return [s["slot_id"] for s in result["slots"]]


# ---- catalog -----------------------------------------------------------------


def test_catalog_lists_every_tool_with_its_schema():
    names = [t["name"] for t in catalog()]
    assert names == [
        "lookup_patient",
        "register_patient",
        "list_appointment_types",
        "check_coverage",
        "find_slots",
        "book_appointment",
        "reschedule_appointment",
        "cancel_appointment",
        "get_clinic_info",
        "transfer_to_human",
    ]
    for spec in TOOLS.values():
        assert spec.description
        assert set(spec.required) <= set(spec.properties)


def test_every_tool_is_a_world_method():
    for name in TOOLS:
        assert callable(getattr(ClinicWorld, name))


def test_date_line(world):
    assert world.date_line().startswith(
        "You answer the phone for Riverside Family Clinic. Today is Monday, 2026-10-12, and the time at the clinic is 08:30."
    )


# ---- lookup and register -------------------------------------------------------


@pytest.mark.parametrize("name", ["James O'Connor", "james oconnor", "  JAMES  O'CONNOR "])
def test_lookup_finds_a_patient_ignoring_case_spaces_and_punctuation(world, name):
    result = world.call("lookup_patient", {"full_name": name, "date_of_birth": "1957-11-02"})
    assert result["found"] is True
    assert result["patient"]["patient_id"] == "pat-002"
    [appointment] = result["appointments"]
    assert appointment["appointment_id"] == "appt-0002"
    assert appointment["hours_until_start"] == 2.5


def test_lookup_ignores_accents(world):
    world.data["patients"][0]["full_name"] = "Ana López"
    assert world.call("lookup_patient", {"full_name": "Ana Lopez", "date_of_birth": "1984-03-12"})["found"]


def test_lookup_needs_the_right_date_of_birth(world):
    assert world.call("lookup_patient", {"full_name": "Ana Lopez", "date_of_birth": "1984-03-13"}) == {"found": False}


def test_lookup_not_found(world):
    assert world.call("lookup_patient", {"full_name": "Nobody", "date_of_birth": "2000-01-01"}) == {"found": False}


def test_lookup_lists_only_upcoming_booked_appointments(world):
    # Mei Chen has a booked visit tomorrow and a cancelled one today.
    result = world.call("lookup_patient", {"full_name": "Mei Chen", "date_of_birth": "1992-06-30"})
    assert [a["appointment_id"] for a in result["appointments"]] == ["appt-0003"]


@pytest.mark.parametrize("dob", ["12/03/1984", "1984-3-12", "March 12 1984", "1984-02-30"])
def test_dates_must_be_strict_iso(world, dob):
    result = world.call("lookup_patient", {"full_name": "Ana Lopez", "date_of_birth": dob})
    assert "date_of_birth" in result["error"]


def test_register_a_new_patient(world):
    result = world.call(
        "register_patient", {"full_name": "Sara Boreal", "date_of_birth": "1990-05-01", "phone": "555 123 4567"}
    )
    assert result["patient"]["patient_id"] == "pat-004"
    assert world.call("lookup_patient", {"full_name": "sara boreal", "date_of_birth": "1990-05-01"})["found"]


def test_register_refuses_an_existing_patient(world):
    result = world.call(
        "register_patient", {"full_name": "ana lopez", "date_of_birth": "1984-03-12", "phone": "555"}
    )
    assert "already registered" in result["error"]


def test_missing_arguments(world):
    assert world.call("register_patient", {"full_name": "Sara"}) == {"error": "Missing date_of_birth, phone."}


# ---- slots ---------------------------------------------------------------------


def test_find_slots_defaults_to_the_earliest_open_slots(world):
    result = world.call("find_slots", {})
    # 08:00 has passed; Patel at 09:00 is free again because that appointment was cancelled.
    assert slot_ids(result)[:3] == ["dr-patel-2026-10-12-0900", "dr-okafor-2026-10-12-0900", "dr-patel-2026-10-12-0930"]
    assert len(result["slots"]) == MAX_SLOTS
    assert result["more"] is True


def test_find_slots_skips_booked_slots(world):
    result = world.call("find_slots", {"provider": "Okafor", "date_from": "2026-10-12", "date_to": "2026-10-12"})
    assert "dr-okafor-2026-10-12-1100" not in slot_ids(result)


@pytest.mark.parametrize("provider", ["dr-patel", "Dr. Patel", "Doctor Patel", "priya patel", "PATEL"])
def test_find_slots_by_provider_name_or_id(world, provider):
    result = world.call("find_slots", {"provider": provider})
    assert {s["provider_id"] for s in result["slots"]} == {"dr-patel"}


def test_unknown_provider_lists_the_providers(world):
    result = world.call("find_slots", {"provider": "Dr. Who"})
    assert "Dr. Priya Patel (dr-patel)" in result["error"]


def test_find_slots_by_day_and_time_of_day(world):
    result = world.call("find_slots", {"date_from": "2026-10-13", "date_to": "2026-10-13", "time_of_day": "afternoon"})
    assert all(s["date"] == "2026-10-13" and s["time"] >= "12:00" for s in result["slots"])
    assert result["slots"][0]["weekday"] == "Tuesday"


def test_find_slots_when_nothing_is_open(world):
    # A Saturday: nobody works.
    assert world.call("find_slots", {"date_from": "2026-10-17", "date_to": "2026-10-17"}) == {"slots": [], "more": False}


def test_find_slots_rejects_a_reversed_range(world):
    result = world.call("find_slots", {"date_from": "2026-10-20", "date_to": "2026-10-13"})
    assert result == {"error": "date_to is before date_from."}


# ---- booking ---------------------------------------------------------------------


def test_book_then_the_slot_is_no_longer_offered(world):
    result = world.call(
        "book_appointment", {"patient_id": "pat-001", "slot_id": "dr-patel-2026-10-12-0930", "reason": "Back pain"}
    )
    appointment = result["appointment"]
    assert appointment["appointment_id"] == "appt-0005"
    assert (appointment["date"], appointment["time"], appointment["provider"]) == ("2026-10-12", "09:30", "Dr. Priya Patel")
    assert "dr-patel-2026-10-12-0930" not in slot_ids(world.call("find_slots", {}))


def test_book_a_taken_slot(world):
    result = world.call("book_appointment", {"patient_id": "pat-001", "slot_id": "dr-okafor-2026-10-12-1100", "reason": "x"})
    assert result == {"error": "That slot is no longer free. Call find_slots again."}


@pytest.mark.parametrize(
    "args, error",
    [
        ({"patient_id": "pat-999", "slot_id": "dr-patel-2026-10-12-0930"}, "No patient with patient_id 'pat-999'."),
        ({"patient_id": "pat-001", "slot_id": "dr-patel-2026-10-12-0800"}, "Unknown slot_id"),  # in the past
        ({"patient_id": "pat-001", "slot_id": "Tuesday 10 AM"}, "Unknown slot_id"),
    ],
)
def test_book_refusals(world, args, error):
    assert world.call("book_appointment", {**args, "reason": "x"})["error"].startswith(error)


def test_reschedule_frees_the_old_slot(world):
    result = world.call("reschedule_appointment", {"appointment_id": "appt-0001", "new_slot_id": "dr-patel-2026-10-15-1400"})
    assert result["previous"]["date"] == "2026-10-14"
    assert (result["appointment"]["date"], result["appointment"]["time"]) == ("2026-10-15", "14:00")
    freed = world.call("find_slots", {"provider": "dr-patel", "date_from": "2026-10-14", "date_to": "2026-10-14"})
    assert "dr-patel-2026-10-14-1000" in slot_ids(freed)


def test_reschedule_unknown_appointment(world):
    result = world.call("reschedule_appointment", {"appointment_id": "appt-9", "new_slot_id": "dr-patel-2026-10-15-1400"})
    assert result == {"error": "No booked appointment with appointment_id 'appt-9'."}


def test_cancel_reports_hours_until_start_and_frees_the_slot(world):
    result = world.call("cancel_appointment", {"appointment_id": "appt-0002"})
    assert result["cancelled"]["hours_until_start"] == 2.5
    assert world.call("cancel_appointment", {"appointment_id": "appt-0002"})["error"].startswith("No booked appointment")
    assert "dr-okafor-2026-10-12-1100" in slot_ids(
        world.call("find_slots", {"provider": "okafor", "date_from": "2026-10-12", "date_to": "2026-10-12"})
    )


def test_transfer(world):
    assert world.call("transfer_to_human", {"reason": "Wants a nurse"}) == {"transferred": True}


def test_unknown_tool(world):
    assert world.call("fly_to_mars", {}) == {"error": "Unknown tool 'fly_to_mars'."}


def test_a_world_never_changes_its_input(world):
    data = json.loads(SEED.read_text())
    w = ClinicWorld(data)
    w.call("cancel_appointment", {"appointment_id": "appt-0001"})
    assert data == json.loads(SEED.read_text())


# ---- live state ---------------------------------------------------------------------


@pytest.fixture
def live(tmp_path) -> LiveClinic:
    return LiveClinic(seed_path=SEED, state_path=tmp_path / "state.json")


def test_live_state_starts_from_the_seed_and_persists_changes(live, tmp_path):
    assert not (tmp_path / "state.json").exists()
    booked = live.call("book_appointment", {"patient_id": "pat-001", "slot_id": "dr-patel-2026-10-12-0930", "reason": "x"})
    assert (tmp_path / "state.json").exists()
    # A later call (a new LiveClinic, as after a restart) sees the booking and can move it.
    later = LiveClinic(seed_path=SEED, state_path=tmp_path / "state.json")
    found = later.call("lookup_patient", {"full_name": "Ana Lopez", "date_of_birth": "1984-03-12"})
    assert booked["appointment"]["appointment_id"] in [a["appointment_id"] for a in found["appointments"]]


def test_reading_and_refused_calls_do_not_write(live, tmp_path):
    live.call("find_slots", {})
    live.call("book_appointment", {"patient_id": "nobody", "slot_id": "x", "reason": "x"})
    assert not (tmp_path / "state.json").exists()


def test_reset_restores_the_seed(live):
    live.call("cancel_appointment", {"appointment_id": "appt-0001"})
    live.reset()
    found = live.call("lookup_patient", {"full_name": "Ana Lopez", "date_of_birth": "1984-03-12"})
    assert [a["appointment_id"] for a in found["appointments"]] == ["appt-0001"]
    live.reset()  # nothing to delete is fine
