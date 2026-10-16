#
# The build (#30; ADR 0012, 0015, 0016): from the approved spec, the Copilot customizes
# the scheduling template and fixes it until the workspace's approved tests pass. The
# result is a proposal a person accepts or not; nothing here edits a test.
#
#   1. The approved configuration becomes the agent's clinic: it is written to the
#      workspace's clinic.json, which the clinic loader reads by the workspace's id.
#   2. One model call returns an outline and operations on a copy of the template, each
#      citing the requirements it serves. #29's operations apply them with validation
#      (problems go back to the model, repair.py); the agent is emitted after each one.
#   3. The loop, at most MAX_ROUNDS rounds: run the approved tests (cached); one model
#      call names the broken link of each failure from a fixed list (LINKS) and returns
#      one change (operations, configuration edits or both); the failing tests run again
#      on the change, and only if one of them now passes, all of them. The change is kept
#      when more tests pass and no safety test that passed now fails. An unclear
#      guideline becomes a client question, not a fix.
#   4. The proposal (workspace proposals/), with the configuration and the operations as
#      a diff on the template, the agent, the diagnosis of every failure left, test
#      results before and after, and why it is blocked, if it is: a failing test, a
#      failing safety test, or the leak check (a test caller's name, birth date or phone
#      number in the agent or the configuration).
#   5. A person accepts or rejects it (#31). A proposal blocked by tests can be accepted
#      anyway, on purpose; one blocked by the leak check cannot. Neither can one whose
#      agent was saved after the build started: the proposal did not see that change.
#
# The panel's "Run tests" (#31) runs the approved tests on the editor's agent alone.
#
# The build reads the workspace, the template and its own prompts: never backend/eval/
# or another clinic's file (a test checks it).
#

import copy
import json
import time
from datetime import date, datetime
import asyncio
from itertools import chain
from pathlib import Path
from typing import Awaitable, Callable

from clinic import TOOLS, normalize_name, validate_clinic
from clinic.clinics import WORKSPACE_CLINIC
from sim.checks import render_transcript
from sim.llm import ChatModel, Models, Usage
from sim.replay import as_record
from sim.runner import blocking, run_suite, run_test
from storage import write_atomic

from . import config
from . import spec as spec_step
from .ops import apply_operations, empty_carriers, tool_schemas
from .repair import StillInvalid, ask
from .spec import data_block
from .workspace import Workspace, agent_hash, now

TEMPLATE = Path(__file__).resolve().parent.parent / "agents" / "prosper-scheduler.json"
TEMPLATE_ID = "prosper-scheduler"
# The baseline safety rules the template's persona carries for every clinic (B1 emergencies,
# B2 medical advice). A build may add to the persona but keeps these word for word: when
# the template had none, a build said "already carried by the template" and its agent
# transferred a caller with chest pain instead of sending them to 911 (Maple Street, 2026-10-16).
SAFETY_RULES = {
    "B1": "If a caller describes a medical emergency, such as chest pain, trouble breathing, heavy bleeding, signs of a "
    "stroke or thoughts of harming themselves, tell them to hang up and call 911 right away, and call no function: "
    "do not transfer them, book or ask for anything first.",
    "B2": "Never give medical advice: not what to take, how much, whether to stop a medicine or whether something is "
    "serious; offer to book a visit instead.",
}

# The broken links of a rule chain (ADR 0015, narrowed for #30): the model names one per
# failure from this list, given the failing turn's recorded context.
LINKS = ("configuration", "node_instruction", "tool_not_offered", "overridden", "unclear_guideline")
# Top-level clinic keys a configuration edit may replace.
EDITABLE = ("providers", "appointment_types", "insurance_plans", "registration_fields", "booking_fields", "cancellation", "facts")

Emit = Callable[[dict], None]
# run_tests(agent, tests, clinic) -> results, as sim.runner.run_suite returns them.
RunTests = Callable[[dict, list[dict], dict], Awaitable[list[dict]]]


class BuildError(Exception):
    def __init__(self, message: str, status: int = 400, problems: list[str] | None = None):
        super().__init__(message)
        self.status = status
        self.problems = problems or []


# ---- the build -----------------------------------------------------------------------------
async def run(
    ws: Workspace,
    model: ChatModel,
    test_models: Models | None = None,
    emit: Emit = lambda event: None,
    run_tests: RunTests | None = None,
    use_cache: bool = True,
    loop: bool = True,
    base: str | None = None,
) -> dict:
    """Build the workspace's agent and loop until its approved tests pass. Emits progress
    events; stores and returns the proposal. `run_tests` replaces the runner (unit tests).
    With `loop` false the workspace tests are not run at all: the proposal is the build
    alone, blocked as untested (to measure the build on its own, `make eval COPILOT=1 NO_LOOP=1`).
    `base` is the hash of the agent as saved when the build started (`saved_hash`)."""
    spec = ws.spec()
    tests = approved_tests(spec)
    if not tests:
        raise BuildError("No approved tests yet. Approve the tests the agent must pass first.")
    if not spec.get("configuration"):
        raise BuildError("The spec has no configuration. Run the spec step first.")
    if run_tests is None and loop:
        if test_models is None:
            raise BuildError("No models to run the tests with.")
        run_tests = lambda agent, chosen, clinic: run_suite(agent, chosen, test_models, use_cache, clinic=clinic)

    usage, test_usage, started = Usage(), Usage(), time.monotonic()
    known = [r["id"] for r in spec["requirements"]]
    configuration = copy.deepcopy(spec["configuration"])
    write_clinic(ws, configuration)
    draft = start_agent(ws.id, configuration)

    def repaired(part):
        return lambda attempt, problems: emit({"event": "repair", "part": part, "attempt": attempt, "problems": problems})

    async def test(agent, chosen, clinic, label):
        results = await run_tests(agent, chosen, clinic)
        for result in results:
            if not result.get("cached"):
                test_usage.merge(result.get("usage", {}))
        emit({"event": "tests", "label": label, "results": summarize(results)})
        return results

    # 1-2. the configuration as the clinic, then the operations on the template copy
    emit({"event": "part", "part": "build", "status": "running", "agent": draft})
    try:
        authored = await ask(
            model, build_messages(spec, draft), "build", None, lambda a: check_build(a, draft, spec, known), usage, repaired("build")
        )
    except StillInvalid as error:
        raise BuildError("The build's operations did not apply.", problems=error.problems) from None
    agent, carriers = draft, start_carriers(spec, known)
    for i, op in enumerate(authored["operations"]):
        step = apply_operations(agent, [op], carriers)
        agent, carriers = step.agent, step.carriers
        emit({"event": "operation", "index": i, "operation": op, "agent": agent})
    emit({"event": "part", "part": "build", "status": "done", "outline": authored["outline"], "uncarried": authored["uncarried"]})

    # 3. the loop
    operations = list(authored["operations"])
    configuration_changes: list[dict] = []
    results = await test(agent, tests, configuration, "before") if loop else []
    before = results
    rounds: list[dict] = []
    diagnosed: tuple[str, list[dict]] | None = None  # (what was diagnosed, diagnoses)
    while loop and len(rounds) < config.MAX_ROUNDS:
        failing = [r for r in results if blocking(r) and r["status"] != "error"]
        if not failing:
            break
        n = len(rounds) + 1
        emit({"event": "part", "part": f"round {n}", "status": "running"})
        try:
            fix = await ask_fix(spec, agent, configuration, carriers, tests, failing, rounds, model, usage, repaired(f"round {n}"))
        except StillInvalid as error:
            rounds.append({"round": n, "error": "The change did not apply.", "problems": error.problems, "kept": False})
            continue
        diagnosed = (state_hash(agent, configuration), fix["diagnoses"])
        record = {
            "round": n,
            "diagnoses": fix["diagnoses"],
            "rationale": fix["rationale"],
            "operations": fix["operations"],
            "configuration": fix["configuration"],
            "concerns": fix["concerns"],
            "kept": False,
        }
        rounds.append(record)
        if not fix["operations"] and not fix["configuration"]:
            record["reason"] = "No change: every failure is a question for the client."
            emit({"event": "round", **record})
            break
        candidate, candidate_carriers, candidate_config = fix["agent"], fix["carriers"], fix["clinic"]
        ids = {r["test_id"] for r in failing}
        rerun = await test(candidate, [t for t in tests if t["id"] in ids], candidate_config, f"round {n}: failing tests")
        record["rerun"] = summarize(rerun)
        if all(blocking(r) for r in rerun):
            record["reason"] = "None of the failing tests passed with the change."
        else:
            full = await test(candidate, tests, candidate_config, f"round {n}: all tests")
            record["full"] = summarize(full)
            record["kept"], record["reason"] = better(results, full)
            if record["kept"]:
                agent, carriers, configuration, results = candidate, candidate_carriers, candidate_config, full
                operations += fix["operations"]
                configuration_changes += fix["configuration"]
        emit({"event": "round", **record})

    # Every failure left names its broken link: diagnose the final agent if no round did.
    failing = [r for r in results if blocking(r) and r["status"] != "error"]
    diagnoses: list[dict] = []
    if failing:
        if diagnosed and diagnosed[0] == state_hash(agent, configuration):
            diagnoses = diagnosed[1]
        else:
            try:
                fix = await ask_fix(spec, agent, configuration, carriers, tests, failing, rounds, model, usage, repaired("diagnosis"), change=False)
                diagnoses = fix["diagnoses"]
            except StillInvalid:
                diagnoses = [{"test": r["test_id"], "link": None, "turn": None, "explanation": "Could not be diagnosed.", "question": None} for r in failing]
        ids = {r["test_id"] for r in failing}
        diagnoses = [d for d in diagnoses if d["test"] in ids]

    # 4. the proposal
    found = leaks(agent, configuration, spec["tests"])
    proposal = {
        "created": now(),
        "started_from": {"template": TEMPLATE_ID, "hash": agent_hash(draft), "agent": base},
        "configuration": configuration,
        "configuration_entries": len(entries(configuration)),
        "configuration_changes": configuration_changes,
        "outline": authored["outline"],
        "operations": operations,
        "agent": agent,
        "carriers": carriers,
        "uncarried": authored["uncarried"],
        "rationale": [r["rationale"] for r in rounds if r.get("kept")],
        "diagnoses": diagnoses,
        "questions": [{"test": d["test"], "question": d["question"]} for d in diagnoses if d.get("question")],
        "concerns": list(chain(*(r.get("concerns", []) for r in rounds))),
        "rounds": rounds,
        "results": {"before": summarize(before), "after": summarize(results)} if loop else None,
        "leaks": found,
        "meta": {
            "model": config.MODEL,
            "seconds": round(time.monotonic() - started, 1),
            "usage": {"copilot": usage.data, "tests": test_usage.data},
            "cost": {"copilot": usage.cost(), "tests": test_usage.cost()},
        },
    }
    proposal["blocked"] = blockers(proposal, results) + ([] if loop else ["The workspace tests were not run (built without the loop)."])
    proposal["status"] = "blocked" if proposal["blocked"] else "ready"
    ws.save_proposal(proposal)
    if loop:
        ws.save_run({"created": now(), "agent_hash": agent_hash(agent), "proposal": proposal["number"], "results": compact(results)})
    emit({"event": "done", "proposal": proposal})
    return proposal


def approved_tests(spec: dict) -> list[dict]:
    """The approved tests in the runner's format (status dropped, so cache keys stay put)."""
    return [{k: v for k, v in t.items() if k != "status"} for t in spec.get("tests", []) if t.get("status") == "approved"]


def write_clinic(ws: Workspace, configuration: dict) -> None:
    """The approved configuration as the workspace's clinic, found by the loader under ws.id."""
    write_atomic(ws.dir / WORKSPACE_CLINIC, json.dumps(configuration, indent=2, ensure_ascii=False) + "\n")


def start_agent(clinic_id: str, configuration: dict) -> dict:
    """A copy of the template with the workspace's clinic."""
    agent = json.loads(TEMPLATE.read_text())
    agent["name"] = f"{configuration['clinic']['name']} Scheduler"
    agent["clinic"] = clinic_id
    return agent


def start_carriers(spec: dict, known: list[str]) -> dict:
    """The spec's carriers, plus the baseline requirements the template's persona carries."""
    carriers = copy.deepcopy(spec.get("carriers") or empty_carriers())
    carriers["persona"] = carriers["persona"] + [i for i in SAFETY_RULES if i in known and i not in carriers["persona"]]
    return carriers


def better(old: list[dict], new: list[dict]) -> tuple[bool, str]:
    """Whether a full rerun is an improvement worth keeping, and why (not)."""
    passing = lambda results: {r["test_id"] for r in results if not blocking(r)}
    safety = lambda results: {r["test_id"] for r in results if r["tier"] == "safety" and not blocking(r)}
    lost = safety(old) - safety(new)
    if lost:
        return False, f"Safety test(s) that passed now fail: {', '.join(sorted(lost))}."
    if len(passing(new)) <= len(passing(old)):
        return False, f"{len(passing(new))} tests pass with the change, {len(passing(old))} without it."
    return True, f"{len(passing(new))} tests pass, {len(passing(old))} before."


def blockers(proposal: dict, results: list[dict]) -> list[str]:
    """Why a proposal cannot be accepted. Empty means it can."""
    reasons = []
    links = {d["test"]: d for d in proposal["diagnoses"]}
    for result in results:
        if result["status"] == "error":
            reasons.append(f"{result['test_id']} could not run: {result.get('error', 'error')}.")
        elif blocking(result):
            d = links.get(result["test_id"], {})
            tier = "Safety test" if result["tier"] == "safety" else "Test"
            why = f" Broken link: {d['link']}. {d['explanation']}" if d.get("link") else ""
            reasons.append(f"{tier} {result['test_id']} fails ({result['status']}).{why}")
    reasons += [f"Leak: {leak}" for leak in proposal["leaks"]]
    return reasons


# ---- the build call --------------------------------------------------------------------------
def build_messages(spec: dict, draft: dict) -> list[dict]:
    carried = spec.get("carriers", {}).get("configuration", {})
    data = "\n\n".join(
        [
            data_block("requirements", _json([_requirement(r) for r in spec["requirements"]])),
            data_block("client_questions", _json(spec.get("questions", []))),
            data_block("configuration", _json(spec["configuration"])),
            data_block("carried_by_configuration", _json(carried)),
            data_block("template", _json(draft)),
        ]
    )
    return [{"role": "system", "content": _prompt("build.md")}, {"role": "user", "content": data}]


def check_build(answer: dict, draft: dict, spec: dict, known: list[str]) -> tuple[dict, list[str]]:
    problems = []
    outline, operations, uncarried = answer.get("outline"), answer.get("operations"), answer.get("uncarried", [])
    if not isinstance(outline, list) or not all(isinstance(line, str) for line in outline) or not outline:
        problems.append("`outline` must be a non-empty list of strings.")
    if not isinstance(operations, list) or not operations:
        return None, problems + ["`operations` must be a non-empty list of operations."]
    if not isinstance(uncarried, list) or not all(isinstance(u, dict) for u in uncarried):
        return None, problems + ["`uncarried` must be a list of {requirement, reason}."]
    applied = apply_operations(draft, operations, start_carriers(spec, known), known)
    problems += applied.errors
    problems += _kept_fixed(applied.agent, draft)
    if applied.ok:
        problems += guide_problems(applied.agent)
    if applied.ok:
        carried = carried_ids(applied.carriers)
        explained = {u.get("requirement") for u in uncarried if isinstance(u.get("reason"), str) and u["reason"].strip()}
        problems += [f"`uncarried` names unknown requirement '{u.get('requirement')}'." for u in uncarried if u.get("requirement") not in known]
        missing = [i for i in known if i not in carried and i not in explained]
        if missing:
            problems.append(
                f"Nothing carries {', '.join(missing)}: cite them in an operation, or list each in `uncarried` with the reason."
            )
    uncarried = [u for u in uncarried if u.get("requirement") not in carried_ids(applied.carriers)]
    return {"outline": outline, "operations": operations, "uncarried": uncarried}, problems


# ---- the fix call ----------------------------------------------------------------------------
async def ask_fix(spec, agent, configuration, carriers, tests, failing, rounds, model, usage, on_repair, change: bool = True) -> dict:
    known = [r["id"] for r in spec["requirements"]]
    ids = [r["test_id"] for r in failing]
    messages = fix_messages(spec, agent, configuration, tests, failing, rounds, change)
    check = lambda answer: check_fix(answer, agent, configuration, carriers, known, ids, spec["tests"], change)
    return await ask(model, messages, "fix", None, check, usage, on_repair)


def fix_messages(spec, agent, configuration, tests, failing, rounds, change: bool) -> list[dict]:
    by_id = {t["id"]: t for t in tests}
    mode = (
        "Diagnose every failing test, then make the change."
        if change
        else "Only diagnose this time: leave `operations` and `configuration` empty."
    )
    prompt = _prompt("fix.md").replace("{{MODE}}", mode)
    attempts = [
        {
            "round": r["round"],
            "rationale": r.get("rationale"),
            "operations": len(r.get("operations", [])),
            "configuration_edits": [c["key"] for c in r.get("configuration", [])],
            "kept": r["kept"],
            "outcome": r.get("reason") or r.get("error"),
        }
        for r in rounds
    ]
    failures = "\n\n".join(describe_failure(result, by_id[result["test_id"]]) for result in failing)
    data = "\n\n".join(
        [
            data_block("requirements", _json([_requirement(r) for r in spec["requirements"]])),
            data_block("client_questions", _json(spec.get("questions", []))),
            data_block("configuration", _json(configuration)),
            data_block("agent", _json(agent)),
            data_block("earlier_attempts", _json(attempts)),
            data_block("failing_tests", failures),
        ]
    )
    return [{"role": "system", "content": prompt}, {"role": "user", "content": data}]


def describe_failure(result: dict, test: dict) -> str:
    """A failing test as the fix call reads it: what it checks, the failed checks with their
    evidence, the transcript, and what the model was given at the failing turn."""
    record = as_record(result)
    failed = [c for c in record.get("checks", []) if not c["pass"]]
    lines = [
        f"## {test['id']}",
        f"Tier {test['tier']}, {result['status']}: {test['title']}",
        f"Requirements: {', '.join(test.get('requirements', [])) or 'none'}",
        f"Caller: {test['caller'].get('persona', '')} Goal: {test['caller'].get('goal', '')}",
        "Failed checks:",
    ]
    for check in failed:
        what = check.get("rule") or check.get("tool") or ", ".join(check.get("tools", [])) or check.get("reason", "")
        where = f" [turn {check['turn']}]" if check.get("turn") else ""
        quote = f' "{check["quote"]}"' if check.get("quote") else ""
        lines.append(f"- {check['type']} {what}: {check['detail']}{where}{quote}")
    lines += [f"Transcript (ended by {record.get('end_reason')}):", render_transcript(record["turns"], internal=True)]
    turn = failing_turn(record, failed)
    if turn is not None:
        offered = [t["function"]["name"] for t in turn["context"].get("tools", [])]
        lines.append(f"At turn {turn['turn']} the model was in node '{turn['node']}' and could call: {', '.join(offered) or 'nothing'}.")
    return "\n".join(lines)


def failing_turn(record: dict, failed: list[dict]) -> dict | None:
    """The agent turn a failure rests on: the one a check cites (or the agent turn just
    before it), else the last agent turn the model took."""
    turns = [t for t in record["turns"] if t["speaker"] == "agent" and "context" in t]
    cited = [c["turn"] for c in failed if isinstance(c.get("turn"), int)]
    if cited:
        before = [t for t in turns if t["turn"] <= min(cited)]
        if before:
            return before[-1]
    return turns[-1] if turns else None


def check_fix(answer, agent, configuration, carriers, known, failing_ids, all_tests, change: bool) -> tuple[dict, list[str]]:
    problems = []
    diagnoses = answer.get("diagnoses")
    if not isinstance(diagnoses, list) or not all(isinstance(d, dict) for d in diagnoses):
        return None, ["`diagnoses` must be a list of {test, link, turn, explanation, question}."]
    for d in diagnoses:
        if isinstance(d.get("test"), str) and d["test"].lower().startswith("test ") and d["test"][5:] in failing_ids:
            d["test"] = d["test"][5:]  # "test <id>": the id is plain enough
        if d.get("test") not in failing_ids:
            problems.append(f"Diagnosis for '{d.get('test')}': not a failing test. Failing: {', '.join(failing_ids)}.")
        if d.get("link") not in LINKS:
            problems.append(f"Diagnosis for '{d.get('test')}': link must be one of {', '.join(LINKS)}.")
        if not isinstance(d.get("explanation"), str) or not d["explanation"].strip():
            problems.append(f"Diagnosis for '{d.get('test')}': needs an explanation.")
        if d.get("link") == "unclear_guideline" and not (isinstance(d.get("question"), str) and d["question"].strip()):
            problems.append(f"Diagnosis for '{d.get('test')}': an unclear guideline needs the question for the client.")
        d.setdefault("turn", None)
        d.setdefault("question", None)
    missing = [i for i in failing_ids if not any(d.get("test") == i for d in diagnoses)]
    if missing:
        problems.append(f"Every failing test needs a diagnosis. Missing: {', '.join(missing)}.")

    operations = answer.get("operations") or []
    edits = answer.get("configuration") or []
    concerns = answer.get("concerns") or []
    if not isinstance(operations, list) or not isinstance(edits, list) or not isinstance(concerns, list):
        return None, problems + ["`operations`, `configuration` and `concerns` must be lists."]
    if not change and (operations or edits):
        problems.append("Only diagnose: leave `operations` and `configuration` empty.")

    applied = apply_operations(agent, operations, carriers, known)
    problems += applied.errors
    problems += _kept_fixed(applied.agent, agent)
    if applied.ok:
        problems += guide_problems(applied.agent)
    clinic, carriers_after = copy.deepcopy(configuration), applied.carriers
    for edit in edits:
        key = edit.get("key") if isinstance(edit, dict) else None
        if key not in EDITABLE:
            problems.append(f"A configuration edit replaces one of {', '.join(EDITABLE)}; got {key!r}.")
            continue
        cited = edit.get("requirements") or []
        unknown = [i for i in cited if i not in known]
        if unknown:
            problems.append(f"Configuration edit of {key}: unknown requirement {', '.join(map(repr, unknown))}.")
        clinic[key] = edit.get("value")
        carry_configuration(carriers_after, key, clinic[key], cited)
    problems += [f"Configuration: {i.path}: {i.message}" for i in validate_clinic(clinic)]
    if not problems:
        problems += [f"{leak} Never special-case a test caller." for leak in leaks(applied.agent, clinic, all_tests)]
    value = {
        "diagnoses": diagnoses,
        "rationale": answer.get("rationale") if isinstance(answer.get("rationale"), str) else "",
        "operations": operations,
        "configuration": edits,
        "concerns": [c for c in concerns if isinstance(c, dict)],
        "agent": applied.agent,
        "carriers": carriers_after,
        "clinic": clinic,
    }
    return value, problems


def carry_configuration(carriers: dict, key: str, value, cited: list[str]) -> None:
    """Move the citations of a replaced configuration key: entries that are gone lose
    theirs, and the entries of the new value carry what the edit cites."""
    entries_now = {e for e in entries({key: value}) if e.split(".", 1)[0] == key}
    mapping = carriers.setdefault("configuration", {})
    for entry in [e for e in mapping if e.split(".", 1)[0] == key and e not in entries_now]:
        del mapping[entry]
    for entry in entries_now:
        mapping[entry] = mapping.get(entry, []) + [i for i in cited if i not in mapping.get(entry, [])]


def guide_problems(agent: dict) -> list[str]:
    """Rules of the authoring guide that code can check. Every node that is not an end node
    offers transfer_to_human: a caller can ask for a person at any step, and the persona's
    rules to transfer work only where the tool is offered. The persona keeps the template's
    safety rules word for word."""
    problems = []
    missing = [
        n["name"]
        for n in agent.get("nodes", [])
        if isinstance(n, dict) and not n.get("end") and "transfer_to_human" not in (n.get("tools") or [])
    ]
    if missing:
        problems.append(
            f"transfer_to_human must be offered in every node that is not an end node; missing in {', '.join(missing)}. "
            "Use set_tools with the node's current tools plus transfer_to_human."
        )
    persona = agent.get("persona") or ""
    problems += [
        f"The persona must keep the template's safety rule for {i} word for word: \"{rule}\""
        for i, rule in SAFETY_RULES.items()
        if rule not in persona
    ]
    return problems


def _kept_fixed(agent: dict, before: dict) -> list[str]:
    return [
        f"Do not change the agent's `{key}` (keep {before.get(key)!r})."
        for key in ("clinic", "model", "voice_id")
        if agent.get(key) != before.get(key)
    ]


# ---- the leak check ------------------------------------------------------------------------
NAME_KEYS = ("name",)
NOT_PEOPLE = ("provider", "doctor", "clinic", "plan", "insurance", "type", "pharmacy")
DATE_FORMATS = ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%d %B %Y", "%B %d %Y")


def test_facts(tests: list[dict]) -> list[tuple[str, str, str]]:
    """(kind, value, test id) for every caller name, birth date and phone number in the
    tests: the caller cards' facts and the patients of their worlds."""
    found = []
    for test in tests:
        facts = (test.get("caller") or {}).get("facts") or {}
        people = ((test.get("world") or {}).get("patients")) or []
        pairs = list(facts.items()) + [(k, p.get(k)) for p in people if isinstance(p, dict) for k in ("full_name", "date_of_birth", "phone")]
        for key, value in pairs:
            if not isinstance(value, str) or not value.strip():
                continue
            key = key.lower()
            if "birth" in key or key == "dob":
                found.append(("birth date", value, test.get("id", "?")))
            elif "phone" in key:
                found.append(("phone number", value, test.get("id", "?")))
            elif any(k in key for k in NAME_KEYS) and not any(k in key for k in NOT_PEOPLE):
                found.append(("name", value, test.get("id", "?")))
    return found


def leaks(agent: dict, configuration: dict, tests: list[dict]) -> list[str]:
    """Test callers' facts written into the agent or the configuration (its patients and
    appointments aside): a proposal with any is blocked, so the Copilot cannot pass by
    special-casing a caller."""
    texts = list(_strings(agent)) + list(_strings({k: v for k, v in configuration.items() if k not in ("patients", "appointments")}))
    names = [normalize_name(t) for t in texts]
    lowered = [" ".join(t.lower().split()) for t in texts]
    digits = ["".join(c for c in t if c.isdigit()) for t in texts]
    found = []
    for kind, value, test_id in test_facts(tests):
        if kind == "name":
            hit = len(normalize_name(value)) >= 5 and any(normalize_name(value) in n for n in names)
        elif kind == "phone number":
            number = "".join(c for c in value if c.isdigit())
            hit = len(number) >= 7 and any(number in d for d in digits)
        else:
            hit = any(form in text for form in _date_forms(value) for text in lowered)
        if hit:
            found.append(f"the {kind} '{value}' of test {test_id}'s caller is in the agent or the configuration.")
    return list(dict.fromkeys(found))


def _date_forms(value: str) -> set[str]:
    forms = {" ".join(value.lower().split())}
    for fmt in DATE_FORMATS:
        try:
            day = datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
        forms |= _spellings(day)
    return forms


def _spellings(day: date) -> set[str]:
    month = day.strftime("%B").lower()
    return {
        day.isoformat(),
        f"{month} {day.day}, {day.year}",
        f"{month} {day.day} {day.year}",
        f"{day.day} {month} {day.year}",
        f"{day.month}/{day.day}/{day.year}",
        f"{day.month:02d}/{day.day:02d}/{day.year}",
    }


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


# ---- accepting a proposal -------------------------------------------------------------------
def saved_hash(agents_dir: Path, agent_id: str) -> str | None:
    """The hash of the agent as saved in agents/<id>.json, or None when there is no file."""
    path = Path(agents_dir) / f"{agent_id}.json"
    return agent_hash(json.loads(path.read_text())) if path.is_file() else None


def decidable(ws: Workspace, number: int) -> dict:
    proposal = ws.proposal(number)
    if proposal is None:
        raise BuildError(f"No proposal {number}.", status=404)
    if proposal.get("decision"):
        raise BuildError(f"Proposal {number} was already {proposal['decision']['status']}.", status=409)
    return proposal


def accept(ws: Workspace, number: int, agents_dir: Path, anyway: bool = False) -> dict:
    """Write an accepted proposal: the agent to agents/<id>.json (a new version), its
    configuration to the workspace's clinic, and the configuration and carriers to the
    spec. A blocked proposal is accepted only `anyway`, and never with a leak. A proposal
    whose agent was saved after the build started is refused: it would undo that save."""
    proposal = decidable(ws, number)
    if proposal.get("leaks"):
        raise BuildError("A test caller's details are in this proposal (the leak check), so it cannot be accepted.", status=409)
    blocked = proposal["status"] == "blocked"
    if blocked and not anyway:
        raise BuildError("This proposal is blocked: " + " ".join(proposal["blocked"]), status=409)
    started = proposal["started_from"]
    # Proposals from before #31 did not record the saved agent: nothing to compare.
    if "agent" in started and saved_hash(agents_dir, ws.id) != started["agent"]:
        raise BuildError("The agent was saved after this build started, so the proposal does not include that change. Build again.", status=409)
    spec = ws.spec()
    spec["configuration"] = proposal["configuration"]
    spec["carriers"] = proposal["carriers"]
    spec_step.write(ws, spec)
    write_clinic(ws, proposal["configuration"])
    write_atomic(Path(agents_dir) / f"{ws.id}.json", json.dumps(proposal["agent"], indent=2, ensure_ascii=False) + "\n")
    version, _ = ws.add_version(proposal["agent"], "copilot", f"Proposal {number}" + (", accepted while blocked" if blocked else ""))
    proposal["decision"] = {"status": "accepted", "at": now(), "version": version["number"], "blocked": blocked}
    ws.update_proposal(proposal)
    return version


def reject(ws: Workspace, number: int) -> dict:
    """Record that a person rejected the proposal. Nothing else changes."""
    proposal = decidable(ws, number)
    proposal["decision"] = {"status": "rejected", "at": now()}
    ws.update_proposal(proposal)
    return proposal["decision"]


# ---- running the tests (#31) ----------------------------------------------------------------
async def run_workspace_tests(
    ws: Workspace,
    agent: dict,
    test_models: Models | None,
    emit: Emit = lambda event: None,
    run_tests: RunTests | None = None,
    use_cache: bool = True,
) -> dict:
    """Run the approved tests on `agent` against the spec's configuration, as the build
    does, emitting each result as it ends (`test`), and store the run. `run_tests`
    replaces the runner (unit tests)."""
    spec = ws.spec()
    tests = approved_tests(spec)
    if not tests:
        raise BuildError("No approved tests yet. Approve the tests the agent must pass first.")
    clinic = spec.get("configuration")
    emit({"event": "part", "part": "tests", "status": "running", "total": len(tests)})
    usage, results = Usage(), []

    def ended(result):
        results.append(result)
        if not result.get("cached"):
            usage.merge(result.get("usage", {}))
        emit({"event": "test", "done": len(results), "total": len(tests), "result": summarize([result])["tests"][0]})

    if run_tests is not None:
        for result in await run_tests(agent, tests, clinic):
            ended(result)
    else:
        if test_models is None:
            raise BuildError("No models to run the tests with.")
        for finished in asyncio.as_completed([run_test(agent, t, test_models, use_cache, clinic=clinic) for t in tests]):
            ended(await finished)
    order = {t["id"]: i for i, t in enumerate(tests)}
    results.sort(key=lambda r: order[r["test_id"]])
    run = {"created": now(), "agent_hash": agent_hash(agent), "proposal": None, "summary": summarize(results), "cost": usage.cost()}
    run["number"] = ws.save_run({**run, "results": compact(results)})
    emit({"event": "done", "run": run})
    return run


def run_view(run: dict, number: int | None = None) -> dict:
    """A stored run without its results: what the panel shows. Runs the build stored
    (#30) have no summary yet."""
    view = {key: run.get(key) for key in ("created", "agent_hash", "proposal", "cost")}
    return {**view, "number": run.get("number", number), "summary": run.get("summary") or summarize(run.get("results", []))}


# ---- helpers -------------------------------------------------------------------------------
def summarize(results: list[dict]) -> dict:
    """Pass/fail per test with the failed checks, and the counts."""
    rows = []
    for r in results:
        failed = []
        if r["status"] in ("fail", "flaky"):
            failed = [
                {k: c.get(k) for k in ("type", "tool", "rule", "detail", "turn")}
                for c in as_record(r).get("checks", [])
                if not c["pass"]
            ]
        rows.append({"test_id": r["test_id"], "tier": r["tier"], "status": r["status"], "cached": bool(r.get("cached")), "failed": failed})
    counts = {s: sum(r["status"] == s for r in results) for s in ("pass", "flaky", "fail", "error")}
    passing = sum(not blocking(r) for r in results)
    return {"tests": rows, "counts": counts, "passing": passing, "total": len(results)}


def compact(results: list[dict]) -> list[dict]:
    """Results without the per-turn contexts, which stay in the runner's cache by key."""
    out = copy.deepcopy(results)
    for result in out:
        for run in result.get("runs", []):
            for turn in run.get("turns", []):
                turn.pop("context", None)
    return out


def entries(configuration: dict) -> list[str]:
    """The configuration's entries, named as the requirement map names them."""
    names = []
    for key in ("providers", "appointment_types", "insurance_plans"):
        names += [f"{key}.{e.get('id')}" for e in configuration.get(key) or [] if isinstance(e, dict)]
    for key in ("registration_fields", "booking_fields"):
        names += [f"{key}.{e.get('name')}" for e in configuration.get(key) or [] if isinstance(e, dict)]
    if configuration.get("cancellation"):
        names.append("cancellation")
    names += [f"facts.{label}" for label in configuration.get("facts") or {}]
    return names


def carried_ids(carriers: dict) -> set[str]:
    carriers = {**empty_carriers(), **carriers}
    return set(chain(*carriers["configuration"].values(), *carriers["nodes"].values(), carriers["persona"]))


def state_hash(agent: dict, configuration: dict) -> str:
    return agent_hash({"agent": agent, "configuration": configuration})


def _requirement(r: dict) -> dict:
    return {k: r.get(k) for k in ("id", "text", "baseline", "question")}


def _prompt(name: str) -> str:
    operations = json.dumps([t["function"] for t in tool_schemas()], ensure_ascii=False)
    return (
        config.prompt(name)
        .replace("{{OPERATIONS}}", operations)
        .replace("{{TOOLS}}", ", ".join(TOOLS))
        .replace("{{GUIDE}}", config.prompt("authoring-guide.md"))
    )


def _json(value) -> str:
    return json.dumps(value, indent=1, ensure_ascii=False)
