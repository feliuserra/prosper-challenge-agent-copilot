#
# Clinic configuration (ADR 0016): what changes from one clinic to the next, as
# data the tools enforce instead of rules in prompts. Every key is optional; a
# clinic without them behaves as before (ADR 0008).
#
#   appointment_types    [{id, name, description, patients, providers}]
#                        patients: "new", "existing" or "any" (the default)
#   insurance_plans      [{id, name, covers: [appointment_type ids]}]
#   registration_fields  [{name, description, required}]  asked by register_patient
#   booking_fields       [{name, description, required}]  asked by book_appointment
#   cancellation         {window_hours, fee}  a fee for changes inside the window
#   facts                {label: text}  address, hours, parking, phone
#
# Patients may carry `last_visit` (a patient without one is new) and
# `insurance_plan`; appointments may carry `appointment_type`. Providers need a
# name, and their weekly hours as {day: ["HH:MM-HH:MM", ...]}.
#
# `validate_clinic` returns every problem with its path, like validate_agent, so
# a configuration the Copilot extracts from guidelines (#29) can be repaired.
#

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

BASE_KEYS = ("clinic", "providers", "patients", "appointments")
CONFIG_KEYS = (
    "appointment_types",
    "insurance_plans",
    "registration_fields",
    "booking_fields",
    "cancellation",
    "facts",
)
PATIENT_KINDS = ("new", "existing", "any")
ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
FIELD_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HOURS_RE = re.compile(r"((?:[01]\d|2[0-3]):[0-5]\d)-((?:[01]\d|2[0-3]):[0-5]\d)")
# Parameters the tools already have, and keys of the records fields are stored on.
RESERVED_FIELDS = {
    "id", "full_name", "date_of_birth", "phone", "last_visit", "patient_id", "slot_id", "reason",
    "appointment_type", "appointment_id", "new_slot_id", "fee_acknowledged", "status", "start",
    "provider_id", "details",
}


@dataclass
class ConfigIssue:
    path: str  # where the problem is, such as "appointment_types[1].providers[0]"
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def validate_clinic(data: Any) -> list[ConfigIssue]:
    """Every problem with a clinic file (seed plus configuration). Empty means valid."""
    if not isinstance(data, dict):
        return [ConfigIssue("", "A clinic must be a JSON object.")]
    issues: list[ConfigIssue] = []

    def issue(path: str, message: str) -> None:
        issues.append(ConfigIssue(path, message))

    for key in sorted(set(data) - set(BASE_KEYS) - set(CONFIG_KEYS)):
        issue(key, f"Unknown key. Clinic keys: {', '.join(BASE_KEYS + CONFIG_KEYS)}.")

    clinic = data.get("clinic")
    if not isinstance(clinic, dict):
        issue("clinic", "Needs an object with the clinic's name and now.")
    else:
        if not _text(clinic.get("name")):
            issue("clinic.name", "Needs the clinic's name.")
        if not _datetime(clinic.get("now")):
            issue("clinic.now", "Needs the clinic's current time as YYYY-MM-DDTHH:MM.")

    providers = _ids(data, "providers", issue, required=True)
    _validate_providers(data.get("providers"), issue)
    types = _validate_types(data.get("appointment_types"), providers, issue)
    _validate_plans(data.get("insurance_plans"), types, issue)
    for key in ("registration_fields", "booking_fields"):
        _validate_fields(data.get(key), key, issue)
    _validate_cancellation(data.get("cancellation"), issue)
    _validate_facts(data.get("facts"), issue)
    patients = _ids(data, "patients", issue)
    for i, patient in enumerate(_list(data.get("patients"))):
        if isinstance(patient, dict) and "last_visit" in patient and not _date(patient["last_visit"]):
            issue(f"patients[{i}].last_visit", "Must be a date as YYYY-MM-DD.")
    for i, appointment in enumerate(_list(data.get("appointments"))):
        if not isinstance(appointment, dict):
            issue(f"appointments[{i}]", "Must be an object.")
            continue
        if appointment.get("patient_id") not in patients:
            issue(f"appointments[{i}].patient_id", f"Unknown patient '{appointment.get('patient_id')}'.")
        if appointment.get("provider_id") not in providers:
            issue(f"appointments[{i}].provider_id", f"Unknown provider '{appointment.get('provider_id')}'.")
        kind = appointment.get("appointment_type")
        if kind is not None and kind not in types:
            issue(f"appointments[{i}].appointment_type", f"Unknown appointment type '{kind}'.")
    return issues


def _validate_providers(value: Any, issue) -> None:
    """Names and weekly hours, which the slots are made from (a configuration the Copilot
    extracts from guidelines writes them too, #29)."""
    for i, provider in enumerate(_list(value)):
        if not isinstance(provider, dict):
            continue
        path = f"providers[{i}]"
        if not _text(provider.get("name")):
            issue(f"{path}.name", "Needs the provider's name.")
        length = provider.get("slot_minutes", 30)
        if not isinstance(length, int) or isinstance(length, bool) or not 5 <= length <= 240:
            issue(f"{path}.slot_minutes", "Must be a whole number of minutes from 5 to 240.")
        schedule = provider.get("schedule", {})
        if not isinstance(schedule, dict):
            issue(f"{path}.schedule", f"Must be an object of weekday ({', '.join(WEEKDAYS)}) to hours.")
            continue
        for day, blocks in schedule.items():
            if day not in WEEKDAYS:
                issue(f"{path}.schedule.{day}", f"Unknown day. Days: {', '.join(WEEKDAYS)}.")
            elif not isinstance(blocks, list) or not all(_hours(b) for b in blocks):
                issue(f"{path}.schedule.{day}", "Must be a list of hours as HH:MM-HH:MM, the start before the end.")


def _validate_types(value: Any, providers: set[str], issue) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, list):
        issue("appointment_types", "Must be a list.")
        return set()
    ids: set[str] = set()
    for i, kind in enumerate(value):
        path = f"appointment_types[{i}]"
        if not isinstance(kind, dict):
            issue(path, "Must be an object.")
            continue
        _check_id(kind.get("id"), f"{path}.id", ids, issue)
        for key in ("name", "description"):
            if not _text(kind.get(key)):
                issue(f"{path}.{key}", f"Needs a {key}.")
        if kind.get("patients", "any") not in PATIENT_KINDS:
            issue(f"{path}.patients", f"Must be one of {', '.join(PATIENT_KINDS)}.")
        doers = kind.get("providers")
        if not isinstance(doers, list) or not doers:
            issue(f"{path}.providers", "Needs at least one provider who does this type.")
            continue
        for j, provider in enumerate(doers):
            if provider not in providers:
                issue(f"{path}.providers[{j}]", f"Unknown provider '{provider}'.")
        if len(set(map(str, doers))) != len(doers):
            issue(f"{path}.providers", "Lists a provider twice.")
    return ids


def _validate_plans(value: Any, types: set[str], issue) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        issue("insurance_plans", "Must be a list.")
        return
    ids: set[str] = set()
    for i, plan in enumerate(value):
        path = f"insurance_plans[{i}]"
        if not isinstance(plan, dict):
            issue(path, "Must be an object.")
            continue
        _check_id(plan.get("id"), f"{path}.id", ids, issue)
        if not _text(plan.get("name")):
            issue(f"{path}.name", "Needs a name.")
        covers = plan.get("covers", [])
        if not isinstance(covers, list):
            issue(f"{path}.covers", "Must be a list of appointment type ids.")
            continue
        for j, kind in enumerate(covers):
            if kind not in types:
                issue(f"{path}.covers[{j}]", f"Unknown appointment type '{kind}'.")


def _validate_fields(value: Any, key: str, issue) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        issue(key, "Must be a list.")
        return
    names: set[str] = set()
    for i, field in enumerate(value):
        path = f"{key}[{i}]"
        if not isinstance(field, dict):
            issue(path, "Must be an object.")
            continue
        name = field.get("name")
        if not isinstance(name, str) or not FIELD_RE.fullmatch(name):
            issue(f"{path}.name", "Must be lowercase letters, digits and '_', starting with a letter.")
        elif name in RESERVED_FIELDS:
            issue(f"{path}.name", f"'{name}' is already a tool parameter or a record key.")
        elif name in names:
            issue(f"{path}.name", f"Duplicate field '{name}'.")
        else:
            names.add(name)
        if not _text(field.get("description")):
            issue(f"{path}.description", "Needs a description: the model reads it to know what to ask.")
        if "required" in field and not isinstance(field["required"], bool):
            issue(f"{path}.required", "Must be true or false.")


def _validate_cancellation(value: Any, issue) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        issue("cancellation", "Must be an object with window_hours and fee.")
        return
    for key in ("window_hours", "fee"):
        number = value.get(key)
        if not isinstance(number, (int, float)) or isinstance(number, bool) or number < 0:
            issue(f"cancellation.{key}", "Must be a number of 0 or more.")


def _validate_facts(value: Any, issue) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        issue("facts", "Must be an object of label to text.")
        return
    for label, text in value.items():
        if not _text(text):
            issue(f"facts.{label}", "Must be non-empty text.")


def _ids(data: dict, key: str, issue, required: bool = False) -> set[str]:
    """The ids of a list of records, reporting a missing list, missing ids and duplicates."""
    value = data.get(key)
    if value is None and not required:
        return set()
    if not isinstance(value, list):
        issue(key, "Must be a list.")
        return set()
    ids: set[str] = set()
    for i, record in enumerate(value):
        if not isinstance(record, dict):
            issue(f"{key}[{i}]", "Must be an object.")
            continue
        _check_id(record.get("id"), f"{key}[{i}].id", ids, issue, pattern=False)
    return ids


def _check_id(value: Any, path: str, seen: set[str], issue, pattern: bool = True) -> None:
    if not _text(value):
        issue(path, "Needs an id.")
    elif pattern and not ID_RE.fullmatch(value):
        issue(path, "Must be lowercase letters, digits, '-' and '_'.")
    elif value in seen:
        issue(path, f"Duplicate id '{value}'.")
    else:
        seen.add(value)


def _hours(value: Any) -> bool:
    match = HOURS_RE.fullmatch(value) if isinstance(value, str) else None
    return bool(match) and match[1] < match[2]


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _date(value: Any) -> bool:
    try:
        date.fromisoformat(value)
        return isinstance(value, str)
    except (TypeError, ValueError):
        return False


def _datetime(value: Any) -> bool:
    try:
        datetime.fromisoformat(value)
        return isinstance(value, str)
    except (TypeError, ValueError):
        return False
