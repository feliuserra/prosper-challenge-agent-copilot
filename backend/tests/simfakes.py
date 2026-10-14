"""Scripted models for the text runner's tests: no network, every request kept."""

import copy
import itertools
import json

from sim.llm import Completion, ModelError, Models, ToolCall

_ids = itertools.count(1)


class Scripted:
    """A ChatModel that answers from a list in order. An answer may be a function of
    the request, or an exception to raise."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests: list[dict] = []

    async def complete(self, request: dict) -> Completion:
        self.requests.append(copy.deepcopy(request))
        if not self.answers:
            raise AssertionError(f"Scripted model ran out of answers ({len(self.requests)} requests)")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer(request) if callable(answer) else answer


def say(text: str) -> Completion:
    return Completion(text=text, model="fake-agent", input_tokens=100, output_tokens=10)


def call(name: str, text: str = "", **args) -> Completion:
    return Completion(
        text=text,
        tool_calls=[ToolCall(id=f"call_{next(_ids)}", name=name, arguments=json.dumps(args))],
        model="fake-agent",
        input_tokens=100,
        output_tokens=10,
    )


def caller(words: str, hang_up: bool = False, use_recorded: int | None = None) -> Completion:
    answer = {"say": words, "hang_up": hang_up, "use_recorded": use_recorded}
    return Completion(text=json.dumps(answer), model="fake-caller", input_tokens=50, output_tokens=5)


def verdict(passed: bool, turn: int | None = 1, quote: str = "", reason: str = "Because.") -> Completion:
    answer = {"pass": passed, "turn": turn, "quote": quote, "reason": reason}
    return Completion(text=json.dumps(answer), model="fake-judge", input_tokens=200, output_tokens=20)


def models(agent=(), caller=(), judge=()) -> Models:
    return Models(agent=Scripted(*agent), caller=Scripted(*caller), judge=Scripted(*judge))


API_DOWN = ModelError("RateLimitError 429: slow down")

# A whole booking with the example agent at Riverside: Ana Lopez books a check-up
# at Dr. Patel's 9:00 (the clinic's types and its interpreter field, ADR 0016).
BOOKING_AGENT = [
    say("Hello, this is the clinic's scheduling assistant. Would you like to book, reschedule or cancel?"),
    call("choose_intent", intent="book"),
    say("Sure. What is your full name, and could you spell it for me?"),
    call("record_spelling", spelled_name="Ana Lopez"),
    say("Ana Lopez: A, N, A, L, O, P, E, Z. Is that right?"),
    call("name_confirmed", full_name="Ana Lopez"),
    say("Thanks. What is your date of birth?"),
    call("lookup_patient", full_name="Ana Lopez", date_of_birth="1984-03-12"),
    call("patient_identified", patient_id="pat-001"),
    say("What is the visit for?"),
    call("record_reason", reason="Check-up", appointment_type="checkup"),
    call("find_slots", appointment_type="checkup"),
    say("I have Monday the 12th at 9 AM or 9:30 AM with Dr. Patel. Which works?"),
    call(
        "book_appointment",
        patient_id="pat-001",
        slot_id="dr-patel-2026-10-12-0900",
        reason="Check-up",
        appointment_type="checkup",
        interpreter="none",
    ),
    call("appointment_booked", appointment_id="appt-0005"),
    say("You're booked with Dr. Patel on Monday the 12th at 9 AM, Ana. Goodbye!"),
]
BOOKING_CALLER = [
    caller("I'd like to book an appointment."),
    caller("Ana Lopez. A, N, A, L, O, P, E, Z."),
    caller("Yes, that's right."),
    caller("March 12th, 1984."),
    caller("Just a check-up."),
    caller("Nine, please."),
]

TEST = {
    "id": "book-existing",
    "title": "An existing patient books a check-up",
    "tier": "core",
    "caller": {
        "persona": "Ana Lopez, 42, a patient of the clinic.",
        "goal": "Book a check-up as soon as possible.",
        "facts": {"full_name": "Ana Lopez", "date_of_birth": "1984-03-12"},
        "style": "Brief.",
    },
    "checks": [{"type": "tool_called", "tool": "book_appointment", "args": {"patient_id": "pat-001"}}],
}
