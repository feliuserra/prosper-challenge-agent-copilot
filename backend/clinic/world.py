#
# The fake clinic the tools work on (ADR 0008): providers with weekly schedules,
# patients and appointments, loaded from a seed JSON.
#
# Deterministic: "now" comes from the seed, never the clock, and open slots are
# generated from the schedules, so the same world always offers the same slots.
# A slot is open when it starts after "now" and no booked appointment uses it.
#
# Tools answer with plain dicts. A refused call (unknown id, slot taken, bad
# date format) answers {"error": "..."} so the model can read why and recover;
# it never raises into the call.
#

import copy
import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Union

from .catalog import TOOLS

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_SLOTS = 6
DEFAULT_SEARCH_DAYS = 7
DEFAULT_HORIZON_DAYS = 28
NOON = "12:00"


class ToolError(Exception):
    """A tool call the clinic refuses. The message goes back to the model."""


def normalize_name(name: str) -> str:
    """Compare names ignoring case, accents, spaces and punctuation ("O'Connor" == "oconnor")."""
    text = unicodedata.normalize("NFKD", name)
    return "".join(c for c in text.casefold() if c.isalnum())


def parse_date(value, param: str) -> date:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value.strip()):
        raise ToolError(f"{param} must be a date as YYYY-MM-DD.")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ToolError(f"{param} '{value}' is not a real date.") from None


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _next_id(items: list[dict], prefix: str, width: int) -> str:
    numbers = [int(i["id"][len(prefix) :]) for i in items if re.fullmatch(rf"{prefix}\d+", i["id"])]
    return f"{prefix}{max(numbers, default=0) + 1:0{width}d}"


class ClinicWorld:
    """One clinic's state. Tools are methods named as in the catalog; `call` runs one by name."""

    def __init__(self, data: dict):
        self.data = copy.deepcopy(data)
        self.data.setdefault("patients", [])
        self.data.setdefault("appointments", [])
        self.now = datetime.fromisoformat(self.data["clinic"]["now"])
        self._providers = {p["id"]: p for p in self.data["providers"]}
        self._slots = self._generate_slots()

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "ClinicWorld":
        return cls(json.loads(Path(path).read_text()))

    def to_dict(self) -> dict:
        return copy.deepcopy(self.data)

    @property
    def today(self) -> date:
        return self.now.date()

    def date_line(self) -> str:
        """The line the agent is told, so "next Tuesday" means something (ADR 0008)."""
        return (
            f"Today is {self.now:%A}, {self.now:%Y-%m-%d}, and the time at the clinic is "
            f"{self.now:%H:%M}. Give dates to tools as YYYY-MM-DD."
        )

    # ---- running tools -------------------------------------------------------
    def call(self, name: str, args: dict) -> dict:
        """Run a catalog tool. Refusals come back as {"error": ...}, never as exceptions."""
        spec = TOOLS.get(name)
        if spec is None:
            return {"error": f"Unknown tool '{name}'."}
        args = args if isinstance(args, dict) else {}
        missing = [p for p in spec.required if not isinstance(args.get(p), str) or not args[p].strip()]
        if missing:
            return {"error": f"Missing {', '.join(missing)}."}
        known = {k: v for k, v in args.items() if k in spec.properties and v is not None}
        try:
            return getattr(self, name)(**known)
        except ToolError as error:
            return {"error": str(error)}

    # ---- slots ---------------------------------------------------------------
    def _generate_slots(self) -> dict[str, dict]:
        """Every slot from now to the horizon, booked or not, by slot_id, in time order."""
        horizon = self.data["clinic"].get("days_ahead", DEFAULT_HORIZON_DAYS)
        slots = {}
        for offset in range(horizon):
            day = self.today + timedelta(days=offset)
            for provider in self.data["providers"]:
                length = provider.get("slot_minutes", 30)
                for block in provider.get("schedule", {}).get(WEEKDAYS[day.weekday()], []):
                    start, end = (_minutes(t) for t in block.split("-"))
                    for minute in range(start, end - length + 1, length):
                        when = datetime.combine(day, datetime.min.time()) + timedelta(minutes=minute)
                        if when <= self.now:
                            continue
                        slot_id = f"{provider['id']}-{day.isoformat()}-{_hhmm(minute).replace(':', '')}"
                        slots[slot_id] = {
                            "slot_id": slot_id,
                            "provider_id": provider["id"],
                            "provider": provider["name"],
                            "date": day.isoformat(),
                            "weekday": f"{day:%A}",
                            "time": _hhmm(minute),
                        }
        return dict(sorted(slots.items(), key=lambda item: (item[1]["date"], item[1]["time"])))

    def _booked(self) -> set[tuple[str, str]]:
        return {
            (a["provider_id"], a["start"]) for a in self.data["appointments"] if a.get("status") == "booked"
        }

    def _is_open(self, slot: dict) -> bool:
        return (slot["provider_id"], f"{slot['date']}T{slot['time']}") not in self._booked()

    def _open_slot(self, slot_id) -> dict:
        slot = self._slots.get(slot_id) if isinstance(slot_id, str) else None
        if slot is None:
            raise ToolError(f"Unknown slot_id '{slot_id}'. Use a slot_id returned by find_slots.")
        if not self._is_open(slot):
            raise ToolError("That slot is no longer free. Call find_slots again.")
        return slot

    def _provider_matching(self, query: str) -> dict:
        q = normalize_name(query)
        matches = [
            p
            for p in self.data["providers"]
            if q
            and (q == normalize_name(p["id"]) or q in normalize_name(p["name"])
                 or normalize_name(p["name"].split()[-1]) in q)
        ]
        if len(matches) != 1:
            known = ", ".join(f"{p['name']} ({p['id']})" for p in self.data["providers"])
            raise ToolError(f"No single provider matches '{query}'. Providers: {known}.")
        return matches[0]

    # ---- patients and appointments ---------------------------------------------
    def _patient(self, patient_id) -> dict:
        for patient in self.data["patients"]:
            if patient["id"] == patient_id:
                return patient
        raise ToolError(f"No patient with patient_id '{patient_id}'.")

    def _booked_appointment(self, appointment_id) -> dict:
        for appointment in self.data["appointments"]:
            if appointment["id"] == appointment_id and appointment.get("status") == "booked":
                return appointment
        raise ToolError(f"No booked appointment with appointment_id '{appointment_id}'.")

    @staticmethod
    def _patient_view(patient: dict) -> dict:
        return {
            "patient_id": patient["id"],
            "full_name": patient["full_name"],
            "date_of_birth": patient["date_of_birth"],
            "phone": patient.get("phone"),
        }

    def _appointment_view(self, appointment: dict) -> dict:
        start = datetime.fromisoformat(appointment["start"])
        provider = self._providers.get(appointment["provider_id"], {})
        return {
            "appointment_id": appointment["id"],
            "provider_id": appointment["provider_id"],
            "provider": provider.get("name", appointment["provider_id"]),
            "date": start.date().isoformat(),
            "weekday": f"{start:%A}",
            "time": f"{start:%H:%M}",
            "reason": appointment.get("reason", ""),
            "hours_until_start": round((start - self.now).total_seconds() / 3600, 1),
        }

    # ---- tools (names, parameters and descriptions are in catalog.py) ------------
    def lookup_patient(self, full_name: str, date_of_birth: str) -> dict:
        dob = parse_date(date_of_birth, "date_of_birth").isoformat()
        for patient in self.data["patients"]:
            if normalize_name(patient["full_name"]) == normalize_name(full_name) and patient["date_of_birth"] == dob:
                upcoming = sorted(
                    (
                        a
                        for a in self.data["appointments"]
                        if a["patient_id"] == patient["id"]
                        and a.get("status") == "booked"
                        and datetime.fromisoformat(a["start"]) > self.now
                    ),
                    key=lambda a: a["start"],
                )
                return {
                    "found": True,
                    "patient": self._patient_view(patient),
                    "appointments": [self._appointment_view(a) for a in upcoming],
                }
        return {"found": False}

    def register_patient(self, full_name: str, date_of_birth: str, phone: str) -> dict:
        dob = parse_date(date_of_birth, "date_of_birth")
        if dob > self.today:
            raise ToolError("date_of_birth is in the future.")
        if self.lookup_patient(full_name, dob.isoformat())["found"]:
            raise ToolError("A patient with this name and date of birth is already registered. Use lookup_patient.")
        patient = {
            "id": _next_id(self.data["patients"], "pat-", 3),
            "full_name": full_name.strip(),
            "date_of_birth": dob.isoformat(),
            "phone": phone.strip(),
        }
        self.data["patients"].append(patient)
        return {"patient": self._patient_view(patient)}

    def find_slots(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        provider: str | None = None,
        time_of_day: str | None = None,
    ) -> dict:
        first = parse_date(date_from, "date_from") if date_from else self.today
        last = parse_date(date_to, "date_to") if date_to else first + timedelta(days=DEFAULT_SEARCH_DAYS - 1)
        if last < first:
            raise ToolError("date_to is before date_from.")
        provider_id = self._provider_matching(provider)["id"] if provider else None
        if time_of_day not in (None, "morning", "afternoon"):
            raise ToolError("time_of_day must be 'morning' or 'afternoon'.")

        found = [
            slot
            for slot in self._slots.values()
            if first.isoformat() <= slot["date"] <= last.isoformat()
            and (provider_id is None or slot["provider_id"] == provider_id)
            and (time_of_day is None or (slot["time"] < NOON) == (time_of_day == "morning"))
            and self._is_open(slot)
        ]
        return {"slots": found[:MAX_SLOTS], "more": len(found) > MAX_SLOTS}

    def book_appointment(self, patient_id: str, slot_id: str, reason: str) -> dict:
        patient = self._patient(patient_id)
        slot = self._open_slot(slot_id)
        appointment = {
            "id": _next_id(self.data["appointments"], "appt-", 4),
            "patient_id": patient["id"],
            "provider_id": slot["provider_id"],
            "start": f"{slot['date']}T{slot['time']}",
            "reason": reason.strip(),
            "status": "booked",
        }
        self.data["appointments"].append(appointment)
        return {"appointment": self._appointment_view(appointment)}

    def reschedule_appointment(self, appointment_id: str, new_slot_id: str) -> dict:
        appointment = self._booked_appointment(appointment_id)
        slot = self._open_slot(new_slot_id)
        previous = self._appointment_view(appointment)
        appointment["provider_id"] = slot["provider_id"]
        appointment["start"] = f"{slot['date']}T{slot['time']}"
        return {"appointment": self._appointment_view(appointment), "previous": previous}

    def cancel_appointment(self, appointment_id: str) -> dict:
        appointment = self._booked_appointment(appointment_id)
        appointment["status"] = "cancelled"
        return {"cancelled": self._appointment_view(appointment)}

    def transfer_to_human(self, reason: str) -> dict:
        return {"transferred": True}
