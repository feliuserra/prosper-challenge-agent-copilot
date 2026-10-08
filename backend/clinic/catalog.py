#
# The tool catalog (ADR 0008): the fixed set of tools a node can list, with the
# description and parameter schema the model sees. Pure data, so validation and
# the editor can read it without loading a clinic. The tools themselves are the
# methods of the same name on ClinicWorld (world.py).
#
# Every parameter is a string in a strict format (dates YYYY-MM-DD, ids as the
# tools return them), so tests can compare arguments exactly. Clinic policies
# (fees, new-patient rules) are not here: they belong in the agent's prompts.
#

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    properties: dict = field(default_factory=dict)  # JSON-schema properties
    required: tuple = ()
    changes_world: bool = False  # live state is saved after a successful call
    ends_call: bool = False  # the bot says one line, then the call ends


def _text(description: str) -> dict:
    return {"type": "string", "description": description}


FULL_NAME = _text("The patient's full name, as confirmed with the caller.")
DATE_OF_BIRTH = _text("Date of birth as YYYY-MM-DD.")
PATIENT_ID = _text("The patient_id from lookup_patient or register_patient.")
SLOT_ID = _text("A slot_id from find_slots.")
APPOINTMENT_ID = _text("An appointment_id from lookup_patient or book_appointment.")

TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            "lookup_patient",
            "Find the caller's patient record by full name and date of birth. Returns found: false when "
            "nothing matches. On a match, returns the patient_id and their upcoming appointments, each with "
            "its appointment_id and hours_until_start.",
            {"full_name": FULL_NAME, "date_of_birth": DATE_OF_BIRTH},
            ("full_name", "date_of_birth"),
        ),
        ToolSpec(
            "register_patient",
            "Register a new patient. Use only after lookup_patient found no match and the caller says they "
            "are new to the clinic. Returns the new patient_id.",
            {
                "full_name": FULL_NAME,
                "date_of_birth": DATE_OF_BIRTH,
                "phone": _text("A phone number to reach the patient, digits as the caller said them."),
            },
            ("full_name", "date_of_birth", "phone"),
            changes_world=True,
        ),
        ToolSpec(
            "find_slots",
            "List open appointment slots, earliest first, at most 6. Every filter is optional: by default, "
            "the next 7 days with any provider. Offer the caller only slots returned here.",
            {
                "date_from": _text("First day to search, YYYY-MM-DD. Defaults to today."),
                "date_to": _text("Last day to search, YYYY-MM-DD. Defaults to 6 days after date_from."),
                "provider": _text("A provider's name or provider_id, when the caller asks for someone."),
                "time_of_day": {
                    "type": "string",
                    "enum": ["morning", "afternoon"],
                    "description": "Morning is before 12:00, afternoon from 12:00.",
                },
            },
        ),
        ToolSpec(
            "book_appointment",
            "Book an open slot for a patient, once the caller has agreed to that slot. Returns the "
            "appointment with its appointment_id.",
            {
                "patient_id": PATIENT_ID,
                "slot_id": SLOT_ID,
                "reason": _text("The reason for the visit, in a few words."),
            },
            ("patient_id", "slot_id", "reason"),
            changes_world=True,
        ),
        ToolSpec(
            "reschedule_appointment",
            "Move a booked appointment to another open slot from find_slots, once the caller has agreed to it.",
            {"appointment_id": APPOINTMENT_ID, "new_slot_id": SLOT_ID},
            ("appointment_id", "new_slot_id"),
            changes_world=True,
        ),
        ToolSpec(
            "cancel_appointment",
            "Cancel a booked appointment, once the caller has confirmed which one.",
            {"appointment_id": APPOINTMENT_ID},
            ("appointment_id",),
            changes_world=True,
        ),
        ToolSpec(
            "transfer_to_human",
            "Transfer the call to a member of the clinic staff. After this, tell the caller in one short "
            "sentence that you are transferring them; the call then ends.",
            {"reason": _text("Why the caller needs a person, in a few words.")},
            ("reason",),
            ends_call=True,
        ),
    ]
}


def catalog() -> list[dict]:
    """The catalog as the editor shows it: name, description and parameters."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "properties": spec.properties,
            "required": list(spec.required),
        }
        for spec in TOOLS.values()
    ]
