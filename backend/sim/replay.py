#
# Replaying recorded calls with another agent (ADR 0015).
#
#   replay_turn    rebuild the context at one agent turn, swap in an agent, sample
#                  that turn k times at the live temperature and grade each sample
#                  with a turn check. A rate, and no simulated caller: the only
#                  randomness is the agent's.
#   continue_from  continue a recorded call from an agent turn with a caller card,
#                  reusing the recorded caller words while the agent asks the same
#                  things and improvising after the first divergence. What happens
#                  after the divergence turn is a forecast, never a fact.
#
# A record is a run from a test result (or, from #28, a recorded live call): turns
# with each agent turn's context, the start node and the starting world.
#

import asyncio
import json

from . import config
from .caller import Caller, recorded_answers
from .checks import TURN_CHECKS, grade, grade_turn
from .conversation import Conversation, ReplayError
from .llm import Models, Usage
from .runner import talk
from .testfile import validate_check


def as_record(record: dict) -> dict:
    """A call record, or a test result: then its last failing run, else its first."""
    if "runs" not in record:
        return record
    runs = record["runs"]
    if not runs:
        raise ValueError("This test result has no runs (it errored).")
    failing = [run for run in runs if not run.get("passed", True)]
    return failing[-1] if failing else runs[0]


def agent_turn(record: dict, turn: int) -> dict:
    for entry in record["turns"]:
        if entry["turn"] == turn:
            if entry["speaker"] != "agent" or "context" not in entry:
                raise ValueError(f"Turn {turn} is not a model turn of the agent.")
            return entry
    raise ValueError(f"The record has no turn {turn}.")


def _rebuild(record: dict, turn: int, agent: dict, models: Models) -> Conversation:
    target = agent_turn(record, turn)
    conversation = Conversation.rebuild(record, agent, turn, models)
    if conversation.node != target["node"]:
        raise ReplayError(f"Rebuilt turn {turn} in node '{conversation.node}', recorded in '{target['node']}'.")
    return conversation


async def replay_turn(record: dict, turn: int, agent: dict, check: dict, models: Models, k: int = 5) -> dict:
    problems = validate_check(check)
    if "result" in check:
        problems.append("A sampled turn's calls are not run, so a turn check cannot match a result.")
    if problems or check["type"] not in TURN_CHECKS:
        raise ValueError(f"A turn check is one of {', '.join(TURN_CHECKS)} with its parameters. {' '.join(problems)}".strip())
    record = as_record(record)
    conversation = _rebuild(record, turn, agent, models)
    request = conversation.request()
    usage = Usage()
    completions = await asyncio.gather(*(models.agent.complete(request) for _ in range(k)))
    samples = []
    for completion in completions:
        usage.add(completion)
        calls = []
        for tool_call in completion.tool_calls:
            kind = conversation.kind_of(tool_call.name)
            try:
                args = json.loads(tool_call.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append({"id": tool_call.id, "name": tool_call.name, "kind": kind, "args": args})
        samples.append({"turn": turn, "speaker": "agent", "node": conversation.node, "text": completion.text, "calls": calls})
    grades = await asyncio.gather(*(grade_turn(check, conversation.turns, sample, models.judge, usage) for sample in samples))
    passed = sum(g["pass"] for g in grades)
    return {
        "turn": turn,
        "node": conversation.node,
        "check": check,
        "k": k,
        "passed": passed,
        "rate": f"{passed}/{k}",
        "samples": [{**sample, "grade": g} for sample, g in zip(samples, grades)],
        "context": conversation.context(),
        "usage": usage.data,
    }


async def continue_from(
    record: dict,
    turn: int,
    agent: dict,
    caller: dict,
    models: Models,
    k: int = 5,
    checks: list[dict] | None = None,
    max_turns: int = config.DEFAULT_MAX_TURNS,
) -> dict:
    record = as_record(record)
    agent_turn(record, turn)
    answers = recorded_answers(record["turns"], from_turn=turn)

    async def one() -> dict:
        conversation = _rebuild(record, turn, agent, models)
        simulated = Caller(caller, models.caller, replay=answers, strict=True)
        await conversation.run_agent()
        await talk(conversation, simulated, max_turns)
        run = conversation.record()
        run["divergence_turn"] = simulated.diverged_at
        if checks:
            run["checks"] = await grade(run, checks, models.judge, conversation.usage)
            run["passed"] = all(c["pass"] for c in run["checks"])
        run["usage"] = conversation.usage.data
        return run

    runs = list(await asyncio.gather(*(one() for _ in range(k))))
    usage = Usage()
    for run in runs:
        usage.merge(run["usage"])
    summary = {
        "from_turn": turn,
        "k": k,
        "divergence_turns": [run["divergence_turn"] for run in runs],
        "end_reasons": [run["end_reason"] for run in runs],
        "runs": runs,
        "usage": usage.data,
    }
    if checks:
        passed = sum(run["passed"] for run in runs)
        summary.update(passed=passed, rate=f"{passed}/{k}")
    return summary
