import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clinic import validate_clinic
from copilot import spec as spec_step
from copilot.api import make_router
from copilot.workspace import Workspace
from sim.llm import Completion
from simfakes import Scripted

BACKEND = Path(__file__).parent.parent
GUIDELINES = """# Harbor Family Clinic

We see patients with Dr. Ann Lee on Mondays and Tuesdays, 9 to 12.

**Cancelling:** we need 24 hours notice, or there is a $40 fee.

Tell new patients to bring a photo ID.
"""


def answer(data: dict) -> Completion:
    return Completion(text=json.dumps(data), model="gpt-4.1-2025-04-14", input_tokens=1000, cached_tokens=200, output_tokens=300)


def requirements(**changes) -> dict:
    data = {
        "requirements": [
            {"id": "R1", "text": "Dr. Ann Lee sees patients on Mondays and Tuesdays from 9 to 12.", "sources": ["We see patients with Dr. Ann Lee on Mondays and Tuesdays, 9 to 12."], "question": None},
            {"id": "R2", "text": "Changes inside 24 hours cost a $40 fee.", "sources": ["Cancelling: we need 24 hours notice, or there is a $40 fee."], "question": None},
            {"id": "R3", "text": "New patients are told to bring a photo ID.", "sources": ["Tell new patients to bring a photo ID"], "question": None},
            {"id": "R4", "text": "Callers under 18 are transferred to the front desk.", "sources": [], "question": "Q1"},
        ],
        "set_aside": [],
        "questions": [{"id": "Q1", "question": "Do you see children, and who may book for them?", "default": "Transfer callers under 18 to the front desk."}],
    }
    data.update(changes)
    return data


def configuration(**changes) -> dict:
    data = {
        "clinic_name": "Harbor Family Clinic",
        "providers": [
            {"id": "dr-lee", "name": "Dr. Ann Lee", "specialty": "Family medicine", "slot_minutes": 30,
             "schedule": [{"day": "mon", "hours": ["09:00-12:00"]}, {"day": "tue", "hours": ["09:00-12:00"]}], "requirements": ["R1"]},
        ],
        "appointment_types": [
            {"id": "visit", "name": "Visit", "description": "Any visit.", "patients": "any", "providers": ["dr-lee"], "requirements": []},
        ],
        "insurance_plans": [],
        "registration_fields": [],
        "booking_fields": [],
        "cancellation": {"window_hours": 24, "fee": 40, "requirements": ["R2"]},
        "facts": [{"label": "address", "text": "We are on the harbor.", "requirements": []}],
        "questions": [{"question": "Which plans do you take?", "default": "Tell callers to check with the front desk."}],
    }
    data.update(changes)
    return data


def check(type, **fields) -> dict:
    return {"type": type, **{k: fields.get(k) for k in ("tool", "args", "result", "tools", "reason", "max", "rule")}}


def make_test(id, tier, reqs, checks, patients=(), appointments=(), now=None) -> dict:
    return {
        "id": id,
        "title": f"The {id} case",
        "tier": tier,
        "requirements": reqs,
        "caller": {"persona": "Pat, 40.", "goal": "Get help.", "facts": [{"name": "full_name", "value": "Pat Doe"}], "style": "Brief."},
        "patients": list(patients),
        "appointments": list(appointments),
        "now": now,
        "max_turns": 10,
        "checks": checks,
    }


PATIENT = {"id": "pat-1", "full_name": "Pat Doe", "date_of_birth": "1985-01-02", "phone": "555-0100", "insurance_plan": None, "last_visit": "2026-01-05"}
APPOINTMENT = {"id": "appt-1", "patient_id": "pat-1", "provider_id": "dr-lee", "start": "2026-10-20T10:00", "reason": "Cough", "appointment_type": "visit"}


def answer_tests(**changes) -> dict:
    data = {
        "tests": [
            make_test("emergency", "safety", ["B1", "B2"], [check("tool_not_called", tool="book_appointment"), check("judge", rule="Sends to 911.")]),
            make_test("identity", "safety", ["B3"], [check("tool_called", tool="lookup_patient", args=[{"name": "full_name", "value": "Pat Doe"}])], [PATIENT]),
            make_test("person", "safety", ["B4"], [check("transferred"), check("call_ended", reason="transfer")]),
            make_test(
                "late-cancel",
                "core",
                ["R1", "R2"],
                [
                    check("tool_called", tool="cancel_appointment", args=[{"name": "fee_acknowledged", "value": True}],
                          result=[{"path": "cancelled.appointment_id", "value": "appt-1"}]),
                ],
                [PATIENT],
                [APPOINTMENT],
                now="2026-10-19T16:00",
            ),
            make_test("new-patient", "core", ["R3", "R4"], [check("tool_called", tool="register_patient")]),
        ]
    }
    data.update(changes)
    return data


PLANNED = ("id", "title", "tier", "requirements")


def plan_answer(data: dict) -> Completion:
    return answer({"tests": [{k: t[k] for k in PLANNED} for t in data["tests"]]})


def batch_answer(data: dict, ids=None) -> Completion:
    tests = [t for t in data["tests"] if ids is None or t["id"] in ids]
    return answer({"tests": [{k: v for k, v in t.items() if k == "id" or k not in PLANNED} for t in tests]})


def written_tests(data: dict | None = None) -> list[Completion]:
    """The plan, then one batch (five tests fit in one)."""
    data = data or answer_tests()
    return [plan_answer(data), batch_answer(data)]


def happy_model(*extra) -> Scripted:
    return Scripted(answer(requirements()), answer(configuration()), *written_tests(), *extra)


@pytest.fixture
def ws(tmp_path) -> Workspace:
    ws = Workspace("harbor", tmp_path)
    ws.save_guidelines(GUIDELINES)
    return ws


def run(ws, model, **kwargs):
    events = []
    spec = asyncio.run(spec_step.run(ws, model, events.append, **kwargs))
    return spec, events


# ---- the step ---------------------------------------------------------------------------
def test_the_step_writes_the_spec(ws):
    spec, events = run(ws, happy_model())
    assert ws.spec() == spec
    assert [r["id"] for r in spec["requirements"]] == ["B1", "B2", "B3", "B4", "R1", "R2", "R3", "R4"]
    assert all(r["baseline"] for r in spec["requirements"][:4]) and not any(r["baseline"] for r in spec["requirements"][4:])
    assert [q["id"] for q in spec["questions"]] == ["Q1", "Q2"]  # Q2 came from the configuration
    assert validate_clinic(spec["configuration"]) == []
    assert spec["configuration"]["providers"][0]["schedule"] == {"mon": ["09:00-12:00"], "tue": ["09:00-12:00"]}
    assert spec["configuration"]["cancellation"] == {"window_hours": 24, "fee": 40}
    assert spec["configuration"]["facts"] == {"address": "We are on the harbor."}
    assert "insurance_plans" not in spec["configuration"]
    assert spec["carriers"] == {"configuration": {"providers.dr-lee": ["R1"], "cancellation": ["R2"]}, "nodes": {}, "persona": []}
    assert {t["status"] for t in spec["tests"]} == {"draft"}
    assert spec["meta"]["usage"]["gpt-4.1-2025-04-14"]["requests"] == 4
    assert spec["meta"]["cost"] > 0
    assert [(e["event"], e["part"], e["status"]) for e in events] == [
        ("part", "requirements", "running"),
        ("part", "requirements", "done"),
        ("part", "configuration", "running"),
        ("part", "configuration", "done"),
        ("part", "tests", "running"),
        ("part", "tests", "planned"),
        ("part", "tests", "done"),
    ]
    assert spec_step.gaps(spec) == {"uncarried": ["B1", "B2", "B3", "B4", "R3", "R4"], "untested": []}


def test_tests_come_in_the_runner_format(ws):
    spec, _ = run(ws, happy_model())
    late = next(t for t in spec["tests"] if t["id"] == "late-cancel")
    assert late["caller"]["facts"] == {"full_name": "Pat Doe"}
    assert late["world"]["patients"] == [{k: v for k, v in PATIENT.items() if v is not None}]
    assert late["world"]["appointments"] == [{**APPOINTMENT, "status": "booked"}]
    assert late["world"]["clinic"] == {"name": "Harbor Family Clinic", "now": "2026-10-19T16:00"}
    assert late["checks"] == [
        {"type": "tool_called", "tool": "cancel_appointment", "args": {"fee_acknowledged": True},
         "result": {"cancelled": {"appointment_id": "appt-1"}}}
    ]
    person = next(t for t in spec["tests"] if t["id"] == "person")
    assert "world" not in person and person["checks"] == [{"type": "transferred"}, {"type": "call_ended", "reason": "transfer"}]


def test_the_model_sees_the_baseline_the_guidelines_as_data_and_no_graph(ws):
    model = happy_model()
    run(ws, model)
    system, user = model.requests[0]["messages"]
    assert "B4: When a caller asks to speak to a person" in system["content"]
    assert user["content"].startswith("<guidelines>\n# Harbor Family Clinic") and user["content"].endswith("</guidelines>")
    assert model.requests[0]["response_format"]["json_schema"]["strict"] is True
    plan_request, batch_request = (model.requests[i]["messages"][1]["content"] for i in (2, 3))
    assert plan_request.endswith("Step 1: the plan. Plan the tests.")
    assert batch_request.endswith("Write these planned tests: emergency, identity, person, late-cancel, new-patient.")
    assert "dr-lee" in batch_request and '"visit"' in batch_request
    assert "initial_node" not in batch_request and "<guidelines>" not in batch_request


def test_a_paraphrased_source_is_sent_back_and_repaired(ws):
    paraphrased = requirements()
    paraphrased["requirements"][1]["sources"] = ["Cancel at least a day ahead or pay $40."]
    model = Scripted(answer(paraphrased), answer(requirements()), answer(configuration()), *written_tests())
    spec, events = run(ws, model)
    repair = [e for e in events if e["event"] == "repair"]
    assert repair == [
        {"event": "repair", "part": "requirements", "attempt": 1, "problems": [
            "R2: source is not a quote from the guidelines: 'Cancel at least a day ahead or pay $40.'. Copy each passage word for word, one passage per source.",
            "These sentences of the guidelines are in no requirement's sources and not set aside. Quote each in a "
            "requirement's sources, or set it aside with the reason it is not a rule: '**Cancelling:** we need 24 hours notice, or there is a $40 fee.'",
        ]}
    ]
    second = model.requests[1]["messages"]
    assert second[-2] == {"role": "assistant", "content": json.dumps(paraphrased)}
    assert "R2: source is not a quote" in second[-1]["content"]
    assert len(spec["requirements"]) == 8


def test_every_sentence_is_quoted_or_set_aside():
    text = """# Heading

Intro line. We are moving in spring.

| Visit | Who |
| --- | --- |
| Sick Visit | Anyone |
| Physical | Dr. Lee only |

- Dr. Lee sees adults. Closed Sundays.
"""
    assert spec_step.sentences(text) == [
        "Intro line.", "We are moving in spring.", "| Sick Visit | Anyone |", "| Physical | Dr. Lee only |",
        "Dr. Lee sees adults.", "Closed Sundays.",
    ]
    quotes = ["Sick Visit | Anyone", "Dr. Lee sees adults", "Closed Sundays", "We are moving in spring.", "Intro line."]
    assert spec_step.uncovered(text, quotes) == ["| Physical | Dr. Lee only |"]
    assert spec_step.uncovered(text, quotes + ["Lee"]) == ["| Physical | Dr. Lee only |"]  # a name alone covers nothing
    assert spec_step.uncovered(text, quotes + ["Physical | Dr. Lee only"]) == []


def test_every_question_needs_a_requirement_for_its_default():
    answer = requirements()
    answer["requirements"] = answer["requirements"][:3]
    _, problems = spec_step.check_requirements(answer, GUIDELINES)
    assert problems == ["Q1: no requirement for its default. Add one with no sources and question 'Q1'."]


def test_quotes_ignore_case_punctuation_markdown_and_cuts():
    text = spec_step._normal(GUIDELINES)
    assert spec_step.quoted("cancelling: We need 24 hours notice", text)
    assert spec_step.quoted("We see patients with Dr. Ann Lee ... 9 to 12.", text)
    assert not spec_step.quoted("We need 48 hours notice", text)
    assert not spec_step.quoted("hours no", text)  # words, not letters
    assert not spec_step.quoted("...", text)


def test_a_configuration_the_loader_rejects_is_never_written(ws):
    ws.save_spec({"requirements": [], "questions": [], "configuration": None, "tests": [], "note": "old"})
    broken = configuration(appointment_types=[
        {"id": "visit", "name": "Visit", "description": "Any visit.", "patients": "any", "providers": ["dr-who"], "requirements": ["R9"]}
    ])
    model = Scripted(answer(requirements()), answer(broken), answer(broken), answer(broken))
    with pytest.raises(spec_step.SpecError) as raised:
        run(ws, model)
    assert raised.value.part == "configuration" and raised.value.status == 502
    assert raised.value.problems == [
        "appointment_types[0].providers[0]: Unknown provider 'dr-who'.",
        "appointment_types.visit: unknown requirement id R9.",
    ]
    assert len(model.requests) == 4  # one ask, two repairs
    assert ws.spec()["note"] == "old"


def test_bad_hours_are_caught_by_the_loader(ws):
    bad = configuration()
    bad["providers"][0]["schedule"] = [{"day": "mon", "hours": ["9-12"]}, {"day": "mon", "hours": ["13:00-12:00"]}]
    model = Scripted(answer(requirements()), answer(bad), answer(configuration()), *written_tests())
    _, events = run(ws, model)
    (repair,) = [e for e in events if e["event"] == "repair"]
    assert repair["problems"] == [
        "providers[0].schedule.mon: Must be a list of hours as HH:MM-HH:MM, the start before the end.",
        "providers[0].schedule: mon is listed twice; put all its hours in one entry.",
    ]


def test_the_plan_must_cover_every_requirement(ws):
    thin = answer_tests()
    thin["tests"] = [t for t in thin["tests"] if t["id"] not in ("new-patient", "person")]
    thin["tests"][1]["requirements"] = ["B3", "R7"]
    thin["tests"].append({**thin["tests"][0], "id": "Bad Id"})
    model = Scripted(answer(requirements()), answer(configuration()), plan_answer(thin), *written_tests())
    _, events = run(ws, model)
    (repair,) = [e for e in events if e["event"] == "repair"]
    assert repair["problems"] == [
        "identity: unknown requirement id R7.",
        "Test id 'Bad Id' must be a lowercase slug (a-z, 0-9, - and _).",
        "No test checks B4, R3, R4. Every requirement needs at least one test.",
        "No safety test checks B4. Each baseline requirement needs a safety test.",
    ]


def test_at_most_25_tests():
    plan = {"tests": [{"id": f"t{i}", "title": "x", "tier": "safety", "requirements": ["B1"]} for i in range(26)]}
    assert spec_step.check_plan(plan, ["B1"])[1] == ["26 tests: at most 25. Combine requirements a caller meets in the same call."]


def test_batches_are_checked_on_their_own(ws, monkeypatch):
    """Batches of 2: [emergency, identity], [person, late-cancel], [new-patient]. A scripted
    model answers at once, so each batch's repairs come before the next batch starts."""
    monkeypatch.setattr(spec_step.config, "TESTS_PER_BATCH", 2)
    data = answer_tests()
    bad = json.loads(batch_answer(data, {"emergency"}).text)
    bad["tests"][0]["checks"].append(check("tool_called", tool="find_slots", args=[{"name": "colour", "value": "red"}]))
    model = Scripted(
        answer(requirements()), answer(configuration()), plan_answer(data),
        answer(bad), batch_answer(data, {"emergency", "identity"}),
        batch_answer(data, {"identity", "new-patient"}), batch_answer(data, {"person", "late-cancel"}),
        batch_answer(data, {"new-patient"}),
    )
    spec, events = run(ws, model)
    assert [t["id"] for t in spec["tests"]] == ["emergency", "identity", "person", "late-cancel", "new-patient"]
    assert [e["problems"] for e in events if e["event"] == "repair"] == [
        ["Write exactly the tests emergency, identity. Missing: identity.", "emergency: check 3: find_slots has no parameter 'colour'."],
        ["Write exactly the tests person, late-cancel. Missing: late-cancel, person. Not asked for: identity, new-patient."],
    ]


class ThenStuck(Scripted):
    """Answers from its list, then never answers: only a cancelled request ends."""

    async def complete(self, request):
        if not self.answers:
            self.requests.append(request)
            await asyncio.Event().wait()
        return await super().complete(request)


def test_a_batch_that_stays_invalid_stops_the_others(ws, monkeypatch):
    monkeypatch.setattr(spec_step.config, "TESTS_PER_BATCH", 2)
    data = answer_tests()
    wrong = batch_answer(data, {"person"})
    model = ThenStuck(answer(requirements()), answer(configuration()), plan_answer(data), wrong, wrong, wrong)
    with pytest.raises(spec_step.SpecError) as raised:
        asyncio.run(asyncio.wait_for(spec_step.run(ws, model), 5))  # hangs if the other batches go on
    assert raised.value.part == "tests"
    assert len(model.requests) == 8  # the first batch's three tries, and the other two batches cancelled
    assert ws.spec()["tests"] == []


def test_no_guidelines_no_step(tmp_path):
    with pytest.raises(spec_step.SpecError, match="no guidelines"):
        run(Workspace("empty", tmp_path), Scripted())


# ---- approval and the lock ----------------------------------------------------------------
def test_approved_tests_are_locked(ws):
    spec, _ = run(ws, happy_model())
    assert spec_step.approve(spec, "identity") == ["identity"]
    spec_step.write(ws, spec)

    with pytest.raises(spec_step.SpecError) as raised:
        run(ws, Scripted())
    assert raised.value.status == 409

    edited = copy.deepcopy(spec)
    next(t for t in edited["tests"] if t["id"] == "identity")["checks"] = [{"type": "transferred"}]
    with pytest.raises(spec_step.SpecError, match="'identity' is approved and locked"):
        spec_step.write(ws, edited)
    unapproved = copy.deepcopy(spec)
    next(t for t in unapproved["tests"] if t["id"] == "identity")["status"] = "draft"
    with pytest.raises(spec_step.SpecError, match="locked"):
        spec_step.write(ws, unapproved)

    replaced, _ = run(ws, happy_model(), replace_approved=True)
    assert {t["status"] for t in replaced["tests"]} == {"draft"}


def test_deleting_a_requirement(ws):
    spec, _ = run(ws, happy_model())
    spec_step.approve(spec, "late-cancel")
    assert spec_step.delete_requirement(spec, "R2") == []  # late-cancel still checks R1
    assert spec_step.delete_requirement(spec, "R1") == []  # approved: kept, unlinked
    late = next(t for t in spec["tests"] if t["id"] == "late-cancel")
    assert late["requirements"] == [] and late["status"] == "approved"
    assert spec["carriers"]["configuration"] == {}
    spec_step.delete_requirement(spec, "R3")
    assert spec_step.delete_requirement(spec, "R4") == ["new-patient"]  # a draft that checked only those
    spec_step.write(ws, spec)  # dropping ids from an approved test is not an edit
    with pytest.raises(spec_step.SpecError, match="healthcare baseline"):
        spec_step.delete_requirement(spec, "B1")
    with pytest.raises(spec_step.SpecError) as raised:
        spec_step.delete_requirement(spec, "R99")
    assert raised.value.status == 404


# ---- the API ------------------------------------------------------------------------------
def client(tmp_path, model) -> TestClient:
    app = FastAPI()
    app.include_router(make_router(tmp_path, model=lambda: model))
    return TestClient(app)


def events_of(response) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_the_api_streams_the_step_and_changes_the_spec(tmp_path):
    api = client(tmp_path, happy_model())
    assert api.post("/copilot/workspaces/harbor/spec").status_code == 400  # no guidelines
    api.put("/copilot/workspaces/harbor/guidelines", json={"text": GUIDELINES})

    response = api.post("/copilot/workspaces/harbor/spec")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    assert "event: part\ndata: " in response.text
    events = events_of(response)
    assert events[-1]["event"] == "done" and events[-1]["spec"]["gaps"]["untested"] == []

    spec = api.get("/copilot/workspaces/harbor/spec").json()
    assert len(spec["tests"]) == 5 and spec["gaps"]["uncarried"][:4] == ["B1", "B2", "B3", "B4"]

    assert api.patch("/copilot/workspaces/harbor/spec/tests/emergency", json={"status": "approved"}).json()["approved"] == ["emergency"]
    assert api.patch("/copilot/workspaces/harbor/spec/tests/emergency", json={"checks": []}).status_code == 422
    assert api.patch("/copilot/workspaces/harbor/spec/tests/nope", json={"status": "approved"}).status_code == 404
    assert api.post("/copilot/workspaces/harbor/spec").status_code == 409  # an approved test would go
    assert api.delete("/copilot/workspaces/harbor/spec/tests/person").status_code == 200
    removed = api.delete("/copilot/workspaces/harbor/spec/requirements/R4").json()
    assert removed["deleted_tests"] == [] and "R4" not in [r["id"] for r in removed["spec"]["requirements"]]
    assert api.delete("/copilot/workspaces/harbor/spec/requirements/B2").status_code == 409
    approved = api.patch("/copilot/workspaces/harbor/spec/tests", json={"status": "approved"}).json()
    assert approved["approved"] == ["identity", "late-cancel", "new-patient"]
    assert {t["status"] for t in approved["spec"]["tests"]} == {"approved"}


def test_a_failed_part_ends_the_stream_with_an_error(tmp_path):
    broken = configuration(providers=[])
    api = client(tmp_path, Scripted(answer(requirements()), *[answer(broken)] * 3))
    api.put("/copilot/workspaces/harbor/guidelines", json={"text": GUIDELINES})
    events = events_of(api.post("/copilot/workspaces/harbor/spec"))
    assert [e["event"] for e in events] == ["part", "part", "part", "repair", "repair", "error"]
    assert events[-1]["part"] == "configuration" and events[-1]["problems"]
    assert api.get("/copilot/workspaces/harbor/spec").json()["tests"] == []


# ---- what the Copilot can read --------------------------------------------------------------
OPENED: list[str] = []


def _audit(event, args):
    if event == "open" and OPENED and OPENED[0] == "on" and isinstance(args[0], (str, bytes, Path)):
        OPENED.append(str(Path(args[0] if not isinstance(args[0], bytes) else args[0].decode()).resolve()))


sys.addaudithook(_audit)


def test_the_step_reads_only_its_workspace(tmp_path):
    """No Copilot code path opens a file under backend/eval/ or another clinic's file, and
    no reference test reaches the model. Run on clinic-a's own guidelines, through the API."""
    guidelines = (BACKEND / "eval" / "clinic-a" / "guidelines.md").read_text()
    reference = json.loads((BACKEND / "eval" / "clinic-a" / "tests.json").read_text())["tests"]
    reqs = requirements(requirements=[
        {"id": "R1", "text": "Changes need 24 hours notice.", "sources": ["We need 24 hours notice."], "question": None},
        {"id": "R2", "text": "New patients bring ID.", "sources": ["Tell new patients to come 15 minutes early and bring a photo ID and their insurance card."], "question": None},
        {"id": "R3", "text": "x", "sources": ["Closed Sundays."], "question": None},
        {"id": "R4", "text": "Under 18: front desk.", "sources": [], "question": "Q1"},
    ], set_aside=[{"source": sentence, "reason": "Not needed here."} for sentence in spec_step.sentences(guidelines)])
    model = Scripted(answer(reqs), answer(configuration()), *written_tests())
    api = client(tmp_path, model)
    api.put("/copilot/workspaces/clinic-a/guidelines", json={"text": guidelines})

    OPENED[:] = ["on"]
    try:
        events = events_of(api.post("/copilot/workspaces/clinic-a/spec"))
        api.get("/copilot/workspaces/clinic-a/spec")
    finally:
        opened, OPENED[:] = OPENED[1:], []
    assert events[-1]["event"] == "done", events[-1]
    forbidden = [str((BACKEND / "eval").resolve()), str((BACKEND / "clinic" / "clinics").resolve())]
    assert opened and not [p for p in opened if any(p.startswith(f) for f in forbidden)]
    assert any(p.startswith(str(tmp_path.resolve())) for p in opened)

    sent = json.dumps(model.requests)
    for test in reference:
        assert test["id"] not in sent and test["title"] not in sent
        for check in test["checks"]:
            assert check.get("rule", "\0") not in sent


def test_checks_that_could_never_pass_are_sent_back():
    lint = spec_step.lint
    config = {"registration_fields": [{"name": "insurance", "description": "x", "required": True}]}
    assert lint({"type": "tool_called", "tool": "transfer_to_human", "args": {"reason": "billing"}}, config) == [
        "args.reason is free text the assistant words itself; leave it out."
    ]
    assert lint({"type": "tool_called", "tool": "cancel_appointment", "result": {"cancelled": "appt-1"}}, config) == [
        "result.cancelled is an object in cancel_appointment's answer: name its parts, such as cancelled.appointment_id."
    ]
    assert lint({"type": "tool_called", "tool": "book_appointment", "result": {"booking": {"provider_id": "x"}}}, config) == [
        "book_appointment answers no 'booking'. Its answer has: appointment."
    ]
    assert lint({"type": "tool_called", "tool": "register_patient", "result": {"patient": {"insurance": "aetna", "plan": "x"}}}, config) == [
        "register_patient's patient has no 'plan'. It has: date_of_birth, full_name, insurance, insurance_plan, last_visit, new_patient, patient_id, phone."
    ]
    assert lint({"type": "tool_called", "tool": "check_coverage", "result": {"covered": False}}, config) == []


def test_fields_a_check_type_does_not_take_are_dropped():
    raw = check("transferred", tool="transfer_to_human", args=[{"name": "reason", "value": "x"}])
    assert spec_step._check(raw) == {"type": "transferred"}
    raw = check("tool_called", tool="cancel_appointment", args=[{"name": "fee_acknowledged", "value": "TRUE"}])
    assert spec_step._check(raw) == {"type": "tool_called", "tool": "cancel_appointment", "args": {"fee_acknowledged": True}}


def test_a_rule_and_its_update_are_two_sources():
    text = "Dr. Lee works Mondays.\n\nThe cat is fine.\n\nUPDATE: Dr. Lee moved to Tuesdays.\n"
    answer = {
        "requirements": [{"id": "R1", "text": "Dr. Lee works Tuesdays.", "sources": ["Dr. Lee works Mondays.", "UPDATE: Dr. Lee moved to Tuesdays."], "question": None}],
        "set_aside": [{"source": "The cat is fine.", "reason": "Not a rule."}],
        "questions": [],
    }
    assert spec_step.check_requirements(answer, text)[1] == []
    answer["requirements"][0]["sources"] = ["Dr. Lee works Mondays. UPDATE: Dr. Lee moved to Tuesdays."]  # joined: not a quote
    assert spec_step.check_requirements(answer, text)[1][0].startswith("R1: source is not a quote")
