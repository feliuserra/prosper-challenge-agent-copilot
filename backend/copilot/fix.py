#
# Fix from an issue (#33; ADR 0015): the production loop from an issue the call judge
# found (#32) to a proposal with its evidence.
#
#   1. Reproduction. One model call reads the issue, the caller card, the transcript and
#      the call's tickets and writes the reproduction: corrections (what the caller said
#      that speech-to-text heard wrong, from a ticket: the card only knows what it
#      heard), checks from the broken requirement, and a turn check for the decisive
#      turn. Code checks every correction against the ticket and the recorded words.
#      The reproduction's caller is the card with the corrections, heard through them
#      (sim/hearing.py), so the agent hears what it heard on the call.
#   2. Backcast. The current agent continues the call from its first turn K times
#      (continue_from: the recorded words while it asks the same things, the caller
#      improvising after). The share that fails is the base rate. None fails: the issue
#      does not reproduce, and the step stops.
#   3. Candidates. One model call names the broken link at the decisive turn and returns
#      CANDIDATES changes (operations only). Each is tried with replay_turn on the
#      decisive turn, K samples graded by the turn check.
#   4. Every candidate also gets the full backcast, K continuations. The winner is the
#      best full rate (then the turn rate, then fewer operations): in the first real run
#      the turn replay ranked the candidates in reverse, so it is measured against the
#      full rate, not trusted alone. None passes either: the step stops (rollouts to look
#      for an earlier turn were cut on 2026-10-16).
#   5. The winner goes through #30's loop on the tests that passed on the current agent
#      (not flaky ones) plus the reproduction: a test that already failed cannot regress,
#      and the agent's other failures are not this fix's business.
#   6. The proposal: the reproduction before and after, the candidates, the tests before
#      (current agent) and after. Blocked by a failing reproduction, any test that passed
#      before and fails now, or the leak check. Accepting it (build.accept) adds the
#      reproduction test, approved, to the workspace's suite and marks the issue fixed in
#      the new version.
#

import copy
import json
import time
from typing import Callable

from clinic import normalize_name
from detect import judge as call_judge
from sim.caller import recorded_answers
from sim.checks import TURN_CHECKS, render_transcript
from sim.conversation import ReplayError
from sim.hearing import Hearing, word_pairs
from sim.llm import ChatModel, Models, Usage
from sim.replay import continue_from, replay_turn
from sim.runner import blocking, run_suite
from sim.testfile import validate_check, validate_test

from . import config
from .build import (
    LINKS,
    BuildError,
    _kept_fixed,
    _prompt,
    approved_tests,
    guide_problems,
    improve,
    leaks,
    summarize,
)
from .ops import apply_operations, empty_carriers
from .repair import StillInvalid, ask
from .spec import data_block, lint
from .workspace import Workspace, agent_hash, now

Emit = Callable[[dict], None]


async def run(
    ws: Workspace,
    call_id: str,
    turn: int,
    agent: dict,
    model: ChatModel,
    test_models: Models,
    emit: Emit = lambda event: None,
    base: str | None = None,
    use_cache: bool = True,
    k: int = config.FIX_K,
) -> dict:
    """Fix the issue the judge found at `turn` of call `call_id`, starting from `agent`
    (the agent as saved; `base` its hash). Emits progress; stores and returns the report,
    with the proposal's number when it got that far."""
    started = time.monotonic()
    spec = ws.spec()
    configuration = spec.get("configuration")
    if not configuration:
        raise BuildError("The spec has no configuration. Run the spec step first.")
    call, issue, judged = find_issue(ws, call_id, turn)
    tickets = call_tickets(ws, call)
    usage, test_usage = Usage(), Usage()
    report = {"created": now(), "issue": issue_view(call, issue), "outcome": None}

    def repaired(part):
        return lambda attempt, problems: emit({"event": "repair", "part": part, "attempt": attempt, "problems": problems})

    def spent(result: dict) -> dict:
        test_usage.merge(result.get("usage", {}))
        return result

    def finish(outcome: str, message: str) -> dict:
        report.update(outcome=outcome, message=message, meta=meta(usage, test_usage, started))
        report["number"] = ws.save_fix(report)
        emit({"event": "done", "fix": report})
        return report

    # 1. the reproduction
    emit({"event": "part", "part": "reproduction", "status": "running"})
    requirement = next((r for r in spec["requirements"] if r["id"] == issue["requirement"]), None)
    try:
        written = await ask(
            model,
            reproduce_messages(call, issue, requirement, judged["card"], tickets),
            "reproduce",
            None,
            lambda answer: check_reproduction(answer, call, judged["card"], tickets, configuration, issue),
            usage,
            repaired("reproduction"),
        )
    except StillInvalid as error:
        raise BuildError("The reproduction could not be written.", problems=error.problems) from None
    test = written["test"]
    report["reproduction"] = {"test": test, "turn_check": written["turn_check"], "corrections": written["corrections"]}
    emit({"event": "part", "part": "reproduction", "status": "done", "test": test, "turn_check": written["turn_check"]})

    # 2. the backcast
    emit({"event": "part", "part": "backcast", "status": "running", "k": k})
    before = spent(await backcast(call, agent, test, test_models, k))
    report["reproduction"]["before"] = before_view = rollout_view(before)
    emit({"event": "backcast", **before_view})
    if before["passed"] == k:
        return finish("not_reproduced", f"The issue did not come back in {k} continuations of the call: nothing to fix.")

    # 3. the candidates and their turn replays
    emit({"event": "part", "part": "candidates", "status": "running"})
    known = [r["id"] for r in spec["requirements"]]
    carriers = copy.deepcopy(spec.get("carriers") or empty_carriers())
    all_tests = spec["tests"] + [test]
    try:
        proposed = await ask(
            model,
            candidate_messages(spec, call, issue, agent, before, written["turn_check"]),
            "candidates",
            None,
            lambda answer: check_candidates(answer, agent, carriers, known, all_tests),
            usage,
            repaired("candidates"),
        )
    except StillInvalid as error:
        raise BuildError("The candidate changes did not apply.", problems=error.problems) from None
    report["diagnosis"] = {key: proposed[key] for key in ("link", "turn", "explanation", "question")}
    emit({"event": "part", "part": "candidates", "status": "done", "diagnosis": report["diagnosis"]})

    current_turn = spent(await turn_rate(call, issue["turn"], agent, written["turn_check"], test_models, k))
    report["turn_before"] = {"passed": current_turn.get("passed"), "rate": current_turn.get("rate"), "error": current_turn.get("error")}
    candidates = []
    for i, candidate in enumerate(proposed["candidates"], 1):
        replayed = spent(await turn_rate(call, issue["turn"], candidate["agent"], written["turn_check"], test_models, k))
        entry = {
            "number": i,
            "rationale": candidate["rationale"],
            "operations": candidate["operations"],
            "turn": {"passed": replayed.get("passed"), "rate": replayed.get("rate"), "error": replayed.get("error"),
                     "samples": [sample_view(s) for s in replayed.get("samples", [])]},
        }
        candidates.append(entry)
        emit({"event": "candidate", **{k_: v for k_, v in entry.items() if k_ != "operations"}})
    report["candidates"] = candidates

    # 4. every candidate's full reproduction: the choice, and the turn replay measured against it
    emit({"event": "part", "part": "full reproductions", "status": "running"})
    fulls = {}
    for entry, candidate in zip(candidates, proposed["candidates"]):
        fulls[entry["number"]] = full = spent(await backcast(call, candidate["agent"], test, test_models, k))
        entry["full"] = rollout_view(full)
        emit({"event": "candidate", "number": entry["number"], "full": entry["full"]})
    report["agreement"] = agreement(candidates, k)
    winner = choose(candidates)
    if winner is None:
        return finish("no_candidate", f"No candidate changed the decisive turn (turn {issue['turn']}) or passed the reproduction.")
    report["chosen"] = winner
    winner_full = fulls[winner]

    # 5. the loop, from the winner. A test that failed on the current agent cannot regress,
    # so after it only the tests that passed run again, with the reproduction.
    chosen = proposed["candidates"][winner - 1]
    tests = approved_tests(spec) + [test]

    async def run_tests(agent_, chosen_tests, clinic, label):
        results = await run_suite(agent_, chosen_tests, test_models, use_cache, clinic=clinic)
        for result in results:
            if not result.get("cached"):
                test_usage.merge(result.get("usage", {}))
        emit({"event": "tests", "label": label, "results": summarize(results)})
        return results

    old = await run_tests(agent, tests, configuration, "before: the current agent")
    # Only a test that passed outright can regress: one that was already flaky fails some
    # runs anyway (#33's third real run: a flaky transfer test blocked a fix in another node).
    passed_before = {r["test_id"] for r in old if r["status"] == "pass"}
    rerun = [t for t in tests if t["id"] in passed_before or t["id"] == test["id"]]
    report["not_rerun"] = sorted(t["id"] for t in tests if t not in rerun)
    first = await run_tests(chosen["agent"], rerun, configuration, f"candidate {winner}")
    looped = await improve(
        spec, chosen["agent"], chosen["carriers"], configuration, rerun, first, model, run_tests, usage, repaired, emit,
    )
    final, results = looped["agent"], looped["results"]
    if looped["operations"]:
        emit({"event": "part", "part": "reproduction after", "status": "running"})
        after = spent(await backcast(call, final, test, test_models, k))
    else:
        after = winner_full
    report["reproduction"]["after"] = rollout_view(after)

    # 6. the proposal
    proposal = {
        "kind": "fix",
        "created": now(),
        "started_from": {"agent": base, "hash": agent_hash(agent), "version": ws.version_of(agent)},
        "issue": report["issue"],
        "configuration": configuration,
        "configuration_changes": [],
        "operations": chosen["operations"] + looped["operations"],
        "agent": final,
        "carriers": looped["carriers"],
        "diagnosis": report["diagnosis"],
        "diagnoses": [],
        "questions": [{"test": test["id"], "question": proposed["question"]}] if proposed.get("question") else [],
        "concerns": [c for r in looped["rounds"] for c in r.get("concerns", [])],
        "rationale": [chosen["rationale"]] + [r["rationale"] for r in looped["rounds"] if r.get("kept")],
        "reproduction": report["reproduction"],
        "turn_before": report["turn_before"],
        "candidates": candidates,
        "chosen": winner,
        "agreement": report["agreement"],
        "rounds": looped["rounds"],
        "results": {"before": summarize(old), "after": summarize(results)},
        "not_rerun": report["not_rerun"],
        "leaks": leaks(final, configuration, all_tests),
    }
    proposal["regressions"] = sorted(passed_before - {r["test_id"] for r in results if not blocking(r)})
    proposal["blocked"] = fix_blockers(proposal, results, test["id"])
    proposal["status"] = "blocked" if proposal["blocked"] else "ready"
    proposal["meta"] = meta(usage, test_usage, started)
    ws.save_proposal(proposal)
    report["proposal"] = proposal["number"]
    report.update(outcome="proposal", message=f"Proposal {proposal['number']} is {proposal['status']}.", meta=proposal["meta"])
    report["number"] = ws.save_fix(report)
    emit({"event": "done", "fix": report, "proposal": proposal})
    return report


# ---- the issue ---------------------------------------------------------------------------------
def find_issue(ws: Workspace, call_id: str, turn: int) -> tuple[dict, dict, dict]:
    call = ws.call(call_id)
    if call is None:
        raise BuildError(f"No call '{call_id}' in this workspace.", status=404)
    judged = call_judge.stored(ws, call_id)
    if judged is None:
        raise BuildError(f"The judge has not read call '{call_id}'.", status=404)
    issue = next((i for i in judged["issues"] if i["turn"] == turn), None)
    if issue is None:
        turns = ", ".join(str(i["turn"]) for i in judged["issues"]) or "none"
        raise BuildError(f"Call '{call_id}' has no issue decided at turn {turn}. Its issues' turns: {turns}.", status=404)
    if not judged.get("card"):
        raise BuildError(f"Call '{call_id}' has no caller card.", status=400)
    return call, issue, judged


def call_tickets(ws: Workspace, call: dict) -> list[dict]:
    found = call_judge.tickets(ws)
    matched = call_judge.match_tickets(found, [call])
    return [t for t in found if call["id"] in matched.get(t["id"], [])]


def issue_view(call: dict, issue: dict) -> dict:
    keys = ("kind", "severity", "requirement", "turn", "quote", "quote_turn", "summary", "node", "label")
    return {"call": call["id"], **{key: issue.get(key) for key in keys}}


# ---- 1. the reproduction ---------------------------------------------------------------------
def reproduce_messages(call: dict, issue: dict, requirement: dict | None, card: dict, tickets: list[dict]) -> list[dict]:
    data = "\n\n".join(
        [
            data_block("issue", _json(issue_view(call, issue))),
            data_block("requirement", _json(requirement or {"id": issue["requirement"], "text": "(not in the spec)"})),
            data_block("caller_card", _json({k: card.get(k) for k in ("persona", "goal", "facts", "style")})),
            data_block("tickets", _json(tickets)),
            data_block("transcript", render_transcript(call["turns"], internal=True)),
        ]
    )
    return [{"role": "system", "content": config.prompt("reproduce.md")}, {"role": "user", "content": data}]


def check_reproduction(answer: dict, call: dict, card: dict, tickets: list[dict], configuration: dict, issue: dict) -> tuple[dict, list[str]]:
    problems = []
    title, corrections, checks, turn_check = answer.get("title"), answer.get("corrections") or [], answer.get("checks"), answer.get("turn_check")
    if not isinstance(title, str) or not title.strip():
        problems.append("`title` must be one sentence.")
    if not isinstance(corrections, list) or not all(isinstance(c, dict) for c in corrections):
        return None, problems + ["`corrections` must be a list of {said, heard, ticket}."]
    spoken = " ".join(t["text"] for t in call["turns"] if t["speaker"] == "caller").lower()
    texts = {t["id"]: t["text"] for t in tickets}
    pairs = []
    for c in corrections:
        said, heard = c.get("said"), c.get("heard")
        if not isinstance(said, str) or not isinstance(heard, str) or not said.strip() or not heard.strip():
            problems.append("Each correction needs `said` and `heard`.")
            continue
        if heard.lower() not in spoken:
            problems.append(f"'{heard}' is not in the caller's words in the transcript: `heard` is copied from them.")
        if not any(normalize_name(said) in normalize_name(text) for text in texts.values()):
            problems.append(f"'{said}' is in no ticket: `said` is copied from a ticket ({', '.join(texts) or 'there are none'}).")
        if said.lower() == heard.lower():
            problems.append(f"'{said}' was heard right: leave it out.")
        pairs += word_pairs(said.strip(), heard.strip())
    if not isinstance(checks, list) or not checks:
        problems.append("`checks` must be a non-empty list.")
        checks = []
    checks = [_clean(c) for c in checks if isinstance(c, dict)]
    for n, check in enumerate(checks, 1):
        problems += [f"check {n}: {p}" for p in lint(check, configuration)]
        # A null argument would demand a null value (found in the first real run, #33).
        problems += [f"check {n}: args.{k} is null: leave out an argument you do not know." for k, v in (check.get("args") or {}).items() if v is None]
    if not isinstance(turn_check, dict) or turn_check.get("type") not in TURN_CHECKS:
        problems.append(f"`turn_check` must be one check of type {', '.join(TURN_CHECKS)}.")
    else:
        turn_check = _clean(turn_check)
        if "result" in turn_check:
            problems.append("`turn_check` cannot have a `result`: the sampled reply's calls are not run.")
        problems += [f"turn_check: {p}" for p in validate_check(turn_check)]
    max_turns = answer.get("max_turns")
    recorded = sum(t["speaker"] == "caller" for t in call["turns"])
    if not isinstance(max_turns, int) or isinstance(max_turns, bool):
        max_turns = recorded + 6
    test = {
        "id": f"repro-{call['id']}-t{issue['turn']}",
        "title": title.strip() if isinstance(title, str) else "",
        "tier": "core",
        "requirements": [issue["requirement"]] if issue.get("requirement") else [],
        "caller": corrected_card(card, pairs),
        "world": test_world(call),
        "replay": [{"question": a["question"], "answer": a["answer"]} for a in recorded_answers(call["turns"])],
        "hearing": pairs,
        "max_turns": max(1, min(60, max(max_turns, recorded + 2))),
        "checks": checks,
        "source": {"call": call["id"], "turn": issue["turn"], "tickets": [t["id"] for t in tickets]},
    }
    if not problems:
        problems += validate_test({k: v for k, v in test.items() if k != "source"}, configuration)
    corrections = [{k: c.get(k) for k in ("said", "heard", "ticket")} for c in corrections]
    return {"test": test, "turn_check": turn_check, "corrections": corrections}, problems


def corrected_card(card: dict, pairs: list[list[str]]) -> dict:
    """The caller card as the caller knows it: what speech-to-text misheard put back."""
    hearing = Hearing(pairs)
    fix = lambda value: hearing.to_caller(value) if isinstance(value, str) else value
    return {
        "persona": fix(card.get("persona", "")),
        "goal": fix(card.get("goal", "")),
        "facts": {key: fix(value) for key, value in (card.get("facts") or {}).items()},
        "style": fix(card.get("style", "")),
    }


def test_world(call: dict) -> dict:
    """The clinic as it was when the call started, configuration included: the
    reproduction replays that call. (The demo's spec names its entries differently from
    the clinic the calls ran in, so its recorded appointments do not load against it.)"""
    return copy.deepcopy(call["world"])


def _clean(check: dict) -> dict:
    """The fields a check type takes, nulls dropped (the model writes every field)."""
    return {key: value for key, value in check.items() if value is not None}


# ---- 2. the backcast ---------------------------------------------------------------------------
async def backcast(call: dict, agent: dict, test: dict, models: Models, k: int) -> dict:
    """`agent` continues the call from its first turn K times with the reproduction's caller."""
    first = next(t["turn"] for t in call["turns"] if t["speaker"] == "agent" and "context" in t)
    return await continue_from(
        call, first, agent, test["caller"], models, k=k, checks=test["checks"], max_turns=test["max_turns"], hearing=test["hearing"]
    )


def rollout_view(rollout: dict) -> dict:
    """Continuations without their turns' contexts: each run's outcome and failed checks."""
    runs = []
    for run in rollout["runs"]:
        failed = [{key: c.get(key) for key in ("type", "tool", "rule", "detail", "turn", "quote")} for c in run.get("checks", []) if not c["pass"]]
        runs.append({
            "passed": run.get("passed"),
            "end_reason": run["end_reason"],
            "divergence_turn": run.get("divergence_turn"),
            "failed": failed,
            "turns": [{key: t.get(key) for key in ("turn", "speaker", "node", "text", "calls", "replayed")} for t in run["turns"]],
        })
    return {"k": rollout["k"], "passed": rollout["passed"], "rate": rollout["rate"], "failed": rollout["k"] - rollout["passed"], "runs": runs}


# ---- 3. candidates and turn replays ------------------------------------------------------------
def candidate_messages(spec: dict, call: dict, issue: dict, agent: dict, before: dict, turn_check: dict) -> list[dict]:
    decisive = next(t for t in call["turns"] if t["turn"] == issue["turn"])
    context = decisive.get("context") or {}
    offered = [t["function"]["name"] for t in context.get("tools", [])]
    instructions = [m["content"] for m in context.get("messages", []) if m.get("role") in ("system", "developer")][-3:]
    failures = [
        {"run": i + 1, "failed": [{k: c.get(k) for k in ("type", "tool", "rule", "detail", "turn")} for c in run.get("checks", []) if not c["pass"]]}
        for i, run in enumerate(before["runs"])
        if not run.get("passed")
    ]
    data = "\n\n".join(
        [
            data_block("issue", _json(issue_view(call, issue))),
            data_block("requirements", _json([{k: r.get(k) for k in ("id", "text")} for r in spec["requirements"]])),
            data_block("reproduction", _json({"failed": f"{before['k'] - before['passed']} of {before['k']}", "failures": failures})),
            data_block("decisive_turn", _json({
                "turn": issue["turn"], "node": decisive.get("node"), "said": decisive.get("text"),
                "called": [c["name"] for c in decisive.get("calls", [])], "could_call": offered,
                "system": context.get("system"), "latest_instructions": instructions,
                "graded_by": turn_check,
            })),
            data_block("transcript", render_transcript(call["turns"], internal=True)),
            data_block("agent", _json(agent)),
        ]
    )
    prompt = _prompt("candidates.md").replace("{{CANDIDATES}}", str(config.CANDIDATES))
    return [{"role": "system", "content": prompt}, {"role": "user", "content": data}]


def check_candidates(answer: dict, agent: dict, carriers: dict, known: list[str], tests: list[dict]) -> tuple[dict, list[str]]:
    problems = []
    if answer.get("link") not in LINKS:
        problems.append(f"`link` must be one of {', '.join(LINKS)}.")
    if not isinstance(answer.get("explanation"), str) or not answer["explanation"].strip():
        problems.append("`explanation` must say why the agent did what it did.")
    if answer.get("link") == "unclear_guideline" and not (isinstance(answer.get("question"), str) and answer["question"].strip()):
        problems.append("An unclear guideline needs the question for the client.")
    proposed = answer.get("candidates")
    if not isinstance(proposed, list) or len(proposed) != config.CANDIDATES:
        return None, problems + [f"`candidates` must be a list of exactly {config.CANDIDATES} {{rationale, operations}}."]
    candidates, seen = [], {agent_hash(agent): "the current agent"}
    for n, c in enumerate(proposed, 1):
        operations = c.get("operations") if isinstance(c, dict) else None
        if not isinstance(operations, list) or not operations:
            problems.append(f"Candidate {n}: `operations` must be a non-empty list.")
            continue
        applied = apply_operations(agent, operations, carriers, known)
        found = [f"Candidate {n}: {e}" for e in applied.errors + _kept_fixed(applied.agent, agent)]
        if applied.ok:
            found += [f"Candidate {n}: {e}" for e in guide_problems(applied.agent, agent)]
            found += [f"Candidate {n}: {leak} Never special-case a caller." for leak in leaks(applied.agent, {}, tests)]
            digest = agent_hash(applied.agent)
            if digest in seen:
                found.append(f"Candidate {n} does what {seen[digest]} does: make the candidates different.")
            seen[digest] = f"candidate {n}"
        problems += found
        rationale = c.get("rationale") if isinstance(c.get("rationale"), str) else ""
        candidates.append({"rationale": rationale, "operations": operations, "agent": applied.agent, "carriers": applied.carriers})
    value = {
        "link": answer.get("link"),
        "turn": answer.get("turn") if isinstance(answer.get("turn"), int) else None,
        "explanation": answer.get("explanation"),
        "question": answer.get("question") if isinstance(answer.get("question"), str) and answer["question"].strip() else None,
        "candidates": candidates,
    }
    return value, problems


async def turn_rate(call: dict, turn: int, agent: dict, check: dict, models: Models, k: int) -> dict:
    """replay_turn, or why it could not run (a candidate that removed the turn's node)."""
    try:
        return await replay_turn(call, turn, agent, check, models, k)
    except ReplayError as error:
        return {"passed": None, "rate": None, "error": str(error), "samples": [], "usage": {}}


def sample_view(sample: dict) -> dict:
    return {"text": sample.get("text"), "calls": [c["name"] for c in sample.get("calls", [])], "pass": sample["grade"]["pass"], "detail": sample["grade"].get("detail")}


def choose(candidates: list[dict]) -> int | None:
    """The candidate whose full reproduction passes most often, then the better turn rate,
    then fewer operations; None when none passes either. (#33's first real run: the turn
    replay ranked the three candidates in reverse, so it is a tiebreak and a measurement,
    not the choice.)"""
    scored = [c for c in candidates if c["full"]["passed"] or c["turn"]["passed"]]
    if not scored:
        return None
    return max(scored, key=lambda c: (c["full"]["passed"], c["turn"]["passed"] or 0, -len(c["operations"]), -c["number"]))["number"]


def agreement(candidates: list[dict], k: int) -> dict:
    """Turn replay against the full continuation, per candidate: do the two say the same
    (a majority of passes, or not)? And is the candidate with the best turn rate also the
    best in full? The rates themselves are in each candidate."""
    rows = [
        {"candidate": c["number"], "turn": c["turn"]["passed"], "full": c["full"]["passed"],
         "agree": (c["turn"]["passed"] * 2 > k) == (c["full"]["passed"] * 2 > k)}
        for c in candidates
        if c["turn"]["passed"] is not None
    ]
    best_turn = max(rows, key=lambda r: r["turn"], default=None)
    return {
        "k": k,
        "rows": rows,
        "agreed": sum(r["agree"] for r in rows),
        "of": len(rows),
        "best_turn_is_best_full": bool(best_turn) and best_turn["full"] == max(r["full"] for r in rows),
    }


# ---- 6. the proposal ---------------------------------------------------------------------------
def fix_blockers(proposal: dict, results: list[dict], test_id: str) -> list[str]:
    reasons = []
    for result in results:
        if result["status"] == "error":
            reasons.append(f"{result['test_id']} could not run: {result.get('error', 'error')}.")
    repro = next((r for r in results if r["test_id"] == test_id), None)
    if repro is None or blocking(repro):
        reasons.append(f"The reproduction test {test_id} still fails ({repro['status'] if repro else 'not run'}).")
    for test in proposal["regressions"]:
        tier = next((r["tier"] for r in results if r["test_id"] == test), "core")
        reasons.append(f"{'Safety test' if tier == 'safety' else 'Test'} {test} passed on the current agent and fails now.")
    reasons += [f"Leak: {leak}" for leak in proposal["leaks"]]
    return reasons


def meta(usage: Usage, test_usage: Usage, started: float) -> dict:
    return {
        "model": config.MODEL,
        "seconds": round(time.monotonic() - started, 1),
        "usage": {"copilot": usage.data, "tests": test_usage.data},
        "cost": {"copilot": usage.cost(), "tests": test_usage.cost()},
    }


def _json(value) -> str:
    return json.dumps(value, indent=1, ensure_ascii=False)
