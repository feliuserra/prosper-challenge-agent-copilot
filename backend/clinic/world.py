#
# The fake clinic the tools work on (ADR 0008): providers with weekly schedules,
# patients and appointments, loaded from a seed JSON.
#
# Deterministic: "now" comes from the seed, never the clock, and open slots are
# generated from the schedules, so the same world always offers the same slots.
# A slot is open when it starts after "now" and no booked appointment uses it.
#
# The clinic's configuration (ADR 0016, config.py) is enforced here: only the
# providers who do an appointment type are offered or booked for it, types meant
# for new or existing patients refuse the others, the clinic's fields are asked
# for, and a change inside the cancellation window needs the caller to accept the
# fee. Every key is optional, so a clinic without configuration behaves as before.
#
# Tools answer with plain dicts. A refused call (unknown id, slot taken, bad
# date format, a rule of the clinic) answers {"error": "..."} so the model can
# read why and recover; it never raises into the call.
#

import copy
import json
import re
import unicodedata
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Union

from .catalog import TOOLS, ToolSpec

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_SLOTS = 6
DEFAULT_SEARCH_DAYS = 7
DEFAULT_HORIZON_DAYS = 28
NOON = "12:00"
# Tools that must name an appointment type when the clinic has types.
NEEDS_TYPE = ("find_slots", "book_appointment")
FIELDS_OF = {"register_patient": "registration_fields", "book_appointment": "booking_fields"}
WHO = {"new": "new patients only", "existing": "existing patients only", "any": "new and existing patients"}


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


def _money(amount) -> str:
    return f"${amount:,.0f}" if float(amount).is_integer() else f"${amount:,.2f}"


def _yes(value) -> bool:
    """fee_acknowledged as the model sends it: true, or now and then the string "true"."""
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


class ClinicWorld:
    """One clinic's state. Tools are methods named as in the catalog; `call` runs one by name."""

    def __init__(self, data: dict):
        self.data = copy.deepcopy(data)
        self.data.setdefault("patients", [])
        self.data.setdefault("appointments", [])
        self.now = datetime.fromisoformat(self.data["clinic"]["now"])
        self._providers = {p["id"]: p for p in self.data["providers"]}
        self._types = {
            t["id"]: t for t in self.data.get("appointment_types") or [] if isinstance(t, dict) and isinstance(t.get("id"), str)
        }
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
        """The line the agent is told: the clinic it answers for (ADR 0016), and the date,
        so "next Tuesday" means something (ADR 0008)."""
        return (
            f"You answer the phone for {self.data['clinic']['name']}. Today is {self.now:%A}, "
            f"{self.now:%Y-%m-%d}, and the time at the clinic is {self.now:%H:%M}. Give dates to tools as YYYY-MM-DD."
        )

    # ---- the schema the model sees ---------------------------------------------
    def tool_spec(self, name: str) -> ToolSpec:
        """A catalog tool as this clinic offers it (ADR 0016): its appointment types as an
        enum, its registration and booking fields as parameters, and the parameters of
        rules it does not have (types, a late-change fee) removed."""
        spec = TOOLS[name]
        properties, required = dict(spec.properties), list(spec.required)
        if "appointment_type" in properties:
            if self._types:
                properties["appointment_type"] = {**properties["appointment_type"], "enum": list(self._types)}
                if name in NEEDS_TYPE:
                    required.append("appointment_type")
            else:
                del properties["appointment_type"]
        for field in self._fields(FIELDS_OF.get(name)):
            properties[field["name"]] = {"type": "string", "description": field["description"]}
            if field.get("required"):
                required.append(field["name"])
        if "fee_acknowledged" in properties and not self._fee_rule():
            del properties["fee_acknowledged"]
        if properties == spec.properties and required == list(spec.required):
            return spec
        return replace(spec, properties=properties, required=tuple(required))

    # ---- running tools -------------------------------------------------------
    def call(self, name: str, args: dict) -> dict:
        """Run a catalog tool. Refusals come back as {"error": ...}, never as exceptions."""
        if name not in TOOLS:
            return {"error": f"Unknown tool '{name}'."}
        spec = self.tool_spec(name)
        args = args if isinstance(args, dict) else {}
        missing = [p for p in spec.required if not isinstance(args.get(p), str) or not args[p].strip()]
        if missing:
            return {"error": f"Missing {', '.join(missing)}."}
        known = {k: v for k, v in args.items() if k in spec.properties and v is not None}
        try:
            return getattr(self, name)(**known)
        except ToolError as error:
            return {"error": str(error)}

    # ---- configuration ---------------------------------------------------------
    def _fields(self, key: str | None) -> list[dict]:
        fields = self.data.get(key) if key else None
        return [f for f in fields or [] if isinstance(f, dict) and isinstance(f.get("name"), str)]

    def _fee_rule(self) -> dict | None:
        rule = self.data.get("cancellation")
        return rule if isinstance(rule, dict) and rule.get("fee") else None

    def _type(self, type_id) -> dict:
        kind = self._types.get(type_id) if isinstance(type_id, str) else None
        if kind is None:
            known = ", ".join(f"{t['id']} ({t.get('name', t['id'])})" for t in self._types.values())
            raise ToolError(f"Unknown appointment_type '{type_id}'. Types: {known}.")
        return kind

    def _provider_names(self, ids) -> list[str]:
        return [self._providers[p]["name"] for p in ids if p in self._providers]

    def _check_provider(self, kind: dict, provider_id: str) -> None:
        if provider_id not in kind.get("providers", []):
            raise ToolError(
                f"{self._providers[provider_id]['name']} does not do {kind['name']}. Call find_slots with "
                f"appointment_type '{kind['id']}' to get slots with the providers who do: "
                f"{', '.join(self._provider_names(kind.get('providers', [])))}."
            )

    @staticmethod
    def _is_new(patient: dict) -> bool:
        return not patient.get("last_visit")

    def _check_eligible(self, kind: dict, patient: dict) -> None:
        who, new = kind.get("patients", "any"), self._is_new(patient)
        if (who == "new" and not new) or (who == "existing" and new):
            open_to = [t["name"] for t in self._types.values() if t.get("patients", "any") in ("any", "new" if new else "existing")]
            status = "is new to the clinic" if new else "has been seen here before"
            raise ToolError(
                f"{kind['name']} is for {WHO[who]}, and {patient['full_name']} {status}. "
                f"Types open to them: {', '.join(open_to)}."
            )

    def _late_fee(self, appointment: dict) -> float:
        """The fee for changing this appointment now: inside the window, if the clinic has a fee."""
        rule = self._fee_rule()
        if rule is None:
            return 0
        hours = (datetime.fromisoformat(appointment["start"]) - self.now).total_seconds() / 3600
        return rule["fee"] if hours < rule.get("window_hours", 0) else 0

    def _check_fee(self, appointment: dict, acknowledged) -> float:
        fee = self._late_fee(appointment)
        if fee and not _yes(acknowledged):
            window = self._fee_rule()["window_hours"]
            hours = round((datetime.fromisoformat(appointment["start"]) - self.now).total_seconds() / 3600, 1)
            raise ToolError(
                f"A {_money(fee)} fee applies to cancelling or moving an appointment less than {window:g} hours "
                f"before it starts, and this one starts in {hours:g} hours. Tell the caller about the fee, and "
                f"call again with fee_acknowledged true only if they agree to pay it."
            )
        return fee

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

    def _plan_matching(self, query: str) -> dict | None:
        """A plan by id or name, ignoring case and punctuation; "blue shield" finds "Blue Shield PPO"."""
        q = normalize_name(query)
        plans = [p for p in self.data.get("insurance_plans") or [] if isinstance(p, dict)]
        exact = [p for p in plans if q and q in (normalize_name(p["id"]), normalize_name(p["name"]))]
        if exact:
            return exact[0]
        partial = [p for p in plans if q and (q in normalize_name(p["name"]) or normalize_name(p["name"]) in q)]
        return partial[0] if len(partial) == 1 else None

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

    def _patient_view(self, patient: dict) -> dict:
        view = {
            "patient_id": patient["id"],
            "full_name": patient["full_name"],
            "date_of_birth": patient["date_of_birth"],
            "phone": patient.get("phone"),
        }
        if self._types:
            view["new_patient"] = self._is_new(patient)
        extra = ["insurance_plan", "last_visit"] + [f["name"] for f in self._fields("registration_fields")]
        view.update({key: patient[key] for key in extra if key in patient})
        return view

    def _appointment_view(self, appointment: dict) -> dict:
        start = datetime.fromisoformat(appointment["start"])
        provider = self._providers.get(appointment["provider_id"], {})
        view = {
            "appointment_id": appointment["id"],
            "provider_id": appointment["provider_id"],
            "provider": provider.get("name", appointment["provider_id"]),
            "date": start.date().isoformat(),
            "weekday": f"{start:%A}",
            "time": f"{start:%H:%M}",
            "reason": appointment.get("reason", ""),
            "hours_until_start": round((start - self.now).total_seconds() / 3600, 1),
        }
        kind = self._types.get(appointment.get("appointment_type"))
        if kind:
            view["appointment_type"] = kind["id"]
            view["type_name"] = kind.get("name", kind["id"])
        if self._fee_rule() and appointment.get("status") == "booked":
            view["late_change_fee"] = self._late_fee(appointment)
        return view

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

    def register_patient(self, full_name: str, date_of_birth: str, phone: str, **fields) -> dict:
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
        for field in self._fields("registration_fields"):
            value = fields.get(field["name"])
            if isinstance(value, str) and value.strip():
                patient[field["name"]] = value.strip()
        self.data["patients"].append(patient)
        return {"patient": self._patient_view(patient)}

    def list_appointment_types(self) -> dict:
        if not self._types:
            return {"appointment_types": [], "note": "This clinic does not use appointment types: any open slot will do."}
        return {
            "appointment_types": [
                {
                    "appointment_type": kind["id"],
                    "name": kind["name"],
                    "description": kind.get("description", ""),
                    "for": WHO[kind.get("patients", "any")],
                    "providers": self._provider_names(kind.get("providers", [])),
                }
                for kind in self._types.values()
            ]
        }

    def check_coverage(self, insurance_plan: str, appointment_type: str | None = None) -> dict:
        plans = self.data.get("insurance_plans") or []
        if not plans:
            raise ToolError("This clinic has no insurance plans on file. The front desk can answer insurance questions.")
        plan = self._plan_matching(insurance_plan)
        if plan is None:
            return {"accepted": False, "insurance_plan": insurance_plan, "accepted_plans": [p["name"] for p in plans]}
        result = {"accepted": True, "insurance_plan": plan["name"]}
        covers = plan.get("covers", [])
        if appointment_type:
            kind = self._type(appointment_type)
            result.update(appointment_type=kind["id"], covered=kind["id"] in covers)
        else:
            result["covers"] = [self._types[t]["name"] for t in covers if t in self._types]
        return result

    def find_slots(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        appointment_type: str | None = None,
        provider: str | None = None,
        time_of_day: str | None = None,
    ) -> dict:
        first = parse_date(date_from, "date_from") if date_from else self.today
        last = parse_date(date_to, "date_to") if date_to else first + timedelta(days=DEFAULT_SEARCH_DAYS - 1)
        if last < first:
            raise ToolError("date_to is before date_from.")
        kind = self._type(appointment_type) if appointment_type else None
        provider_id = self._provider_matching(provider)["id"] if provider else None
        if kind and provider_id:
            self._check_provider(kind, provider_id)
        if time_of_day not in (None, "morning", "afternoon"):
            raise ToolError("time_of_day must be 'morning' or 'afternoon'.")

        found = [
            slot
            for slot in self._slots.values()
            if first.isoformat() <= slot["date"] <= last.isoformat()
            and (provider_id is None or slot["provider_id"] == provider_id)
            and (kind is None or slot["provider_id"] in kind.get("providers", []))
            and (time_of_day is None or (slot["time"] < NOON) == (time_of_day == "morning"))
            and self._is_open(slot)
        ]
        return {"slots": found[:MAX_SLOTS], "more": len(found) > MAX_SLOTS}

    def book_appointment(
        self, patient_id: str, slot_id: str, reason: str, appointment_type: str | None = None, **fields
    ) -> dict:
        patient = self._patient(patient_id)
        slot = self._open_slot(slot_id)
        kind = None
        if self._types:
            kind = self._type(appointment_type)
            self._check_provider(kind, slot["provider_id"])
            self._check_eligible(kind, patient)
        appointment = {
            "id": _next_id(self.data["appointments"], "appt-", 4),
            "patient_id": patient["id"],
            "provider_id": slot["provider_id"],
            "start": f"{slot['date']}T{slot['time']}",
            "reason": reason.strip(),
            "status": "booked",
        }
        if kind:
            appointment["appointment_type"] = kind["id"]
        details = {
            f["name"]: fields[f["name"]].strip()
            for f in self._fields("booking_fields")
            if isinstance(fields.get(f["name"]), str) and fields[f["name"]].strip()
        }
        if details:
            appointment["details"] = details
        self.data["appointments"].append(appointment)
        return {"appointment": self._appointment_view(appointment)}

    def reschedule_appointment(self, appointment_id: str, new_slot_id: str, fee_acknowledged=None) -> dict:
        appointment = self._booked_appointment(appointment_id)
        slot = self._open_slot(new_slot_id)
        kind = self._types.get(appointment.get("appointment_type"))
        if kind:
            self._check_provider(kind, slot["provider_id"])
        fee = self._check_fee(appointment, fee_acknowledged)
        previous = self._appointment_view(appointment)
        appointment["provider_id"] = slot["provider_id"]
        appointment["start"] = f"{slot['date']}T{slot['time']}"
        result = {"appointment": self._appointment_view(appointment), "previous": previous}
        if fee:
            appointment["fee_charged"] = result["fee_charged"] = fee
        return result

    def cancel_appointment(self, appointment_id: str, fee_acknowledged=None) -> dict:
        appointment = self._booked_appointment(appointment_id)
        fee = self._check_fee(appointment, fee_acknowledged)
        appointment["status"] = "cancelled"
        result = {"cancelled": self._appointment_view(appointment)}
        if fee:
            appointment["fee_charged"] = result["fee_charged"] = fee
        return result

    def get_clinic_info(self) -> dict:
        facts = self.data.get("facts") or {}
        result = {"clinic": self.data["clinic"]["name"], "facts": dict(facts)}
        if not facts:
            result["note"] = "No details on file. The front desk can answer questions about the clinic."
        return result

    def transfer_to_human(self, reason: str) -> dict:
        return {"transferred": True}
