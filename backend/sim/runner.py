#
# Running tests (ADR 0010): one simulated call per test against a fresh clinic,
# graded by its checks. A failure is rerun once: failing twice is a failure,
# failing then passing is flaky. A test that could not run (the API failed after
# retries) is an error, never a failure of the agent. Results are cached by a hash
# of everything that decides them, so only tests whose inputs changed run again.
# Mutants (#27) run with rerun=False: once, pass or fail.
#

import asyncio
import copy
import hashlib
import json
import time
from pathlib import Path

from agent_builder.schema import DEFAULT_MODEL
from clinic import ClinicWorld, clinic_of

from . import config
from .caller import Caller
from .checks import grade
from .conversation import Conversation
from .llm import ModelError, Models, Usage
from .testfile import resolve_world


async def talk(conversation: Conversation, caller: Caller, max_turns: int) -> None:
    """Alternate caller and agent until the call ends."""
    while conversation.ended is None:
        if sum(turn["speaker"] == "caller" for turn in conversation.turns) >= max_turns:
            conversation.end("max_turns")
            return
        text, hang_up, extra = await caller.next(conversation.turns, conversation.usage)
        if text:
            conversation.caller_says(text, **extra)
        if hang_up or not text:  # the caller is told never to stay silent without hanging up
            conversation.end("caller_hung_up")
            return
        await conversation.run_agent()


async def simulate(agent: dict, test: dict, models: Models, clinic: dict | None = None) -> dict:
    """One call of `agent` with the test's caller, from the test's world in the agent's
    clinic, or in `clinic` (a clinic file) when given. Returns its record."""
    started = time.monotonic()
    conversation = Conversation(agent, ClinicWorld(resolve_world(test, _clinic(agent, clinic))), models)
    caller = Caller(test["caller"], models.caller, replay=test.get("replay"))
    await conversation.start()
    await talk(conversation, caller, test.get("max_turns", config.DEFAULT_MAX_TURNS))
    record = conversation.record()
    if caller.replay:
        # A test whose recorded answers were not used did not replay the real call.
        record["replay"] = {"recorded": len(caller.replay), "used": sorted(caller.used)}
    record["usage"] = conversation.usage.data
    record["seconds"] = round(time.monotonic() - started, 1)
    return record


async def run_once(agent: dict, test: dict, models: Models, clinic: dict | None = None) -> dict:
    record = await simulate(agent, test, models, clinic)
    usage = Usage(record["usage"])
    record["checks"] = await grade(record, test["checks"], models.judge, usage)
    record["usage"] = usage.data
    record["passed"] = all(check["pass"] for check in record["checks"])
    return record


async def run_test(
    agent: dict,
    test: dict,
    models: Models,
    use_cache: bool = True,
    cache_dir: Path = config.CACHE_DIR,
    rerun: bool = True,
    clinic: dict | None = None,
) -> dict:
    """`clinic`, a clinic file, replaces the agent's clinic: the Copilot's build (#30)
    tries configuration changes before any is written."""
    key = cache_key(agent, test, rerun, clinic)
    path = Path(cache_dir) / f"{key}.json"
    if use_cache and path.is_file():
        return {**json.loads(path.read_text()), "cached": True}

    started = time.monotonic()
    result = {
        "test_id": test["id"],
        "title": test["title"],
        "tier": test["tier"],
        "requirements": test.get("requirements", []),
        "models": {"agent": agent.get("model", DEFAULT_MODEL), "caller": config.CALLER_MODEL, "judge": config.JUDGE_MODEL},
        "runner_version": config.RUNNER_VERSION,
        "key": key,
    }
    runs = []
    try:
        runs.append(await run_once(agent, test, models, clinic))
        if rerun and not runs[0]["passed"]:
            runs.append(await run_once(agent, test, models, clinic))
    except ModelError as error:
        result["status"] = "error"
        result["error"] = str(error)
    else:
        result["status"] = "pass" if runs[0]["passed"] else "flaky" if runs[-1]["passed"] else "fail"
    usage = Usage()
    for run in runs:
        usage.merge(run["usage"])
    result.update(runs=runs, usage=usage.data, seconds=round(time.monotonic() - started, 1), cached=False)
    if result["status"] != "error":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    return result


async def run_suite(
    agent: dict, tests: list[dict], models: Models, use_cache: bool = True, cache_dir: Path = config.CACHE_DIR, clinic: dict | None = None
) -> list[dict]:
    """Every test in parallel (the model client limits the requests in flight)."""
    return list(await asyncio.gather(*(run_test(agent, test, models, use_cache, cache_dir, clinic=clinic) for test in tests)))


async def run_pairs(pairs: list[tuple[dict, dict]], models: Models, use_cache: bool = True, cache_dir: Path = config.CACHE_DIR, rerun: bool = True) -> list[dict]:
    """(agent, test) pairs in parallel, each agent its own: for mutants."""
    return list(await asyncio.gather(*(run_test(agent, test, models, use_cache, cache_dir, rerun) for agent, test in pairs)))


def blocking(result: dict) -> bool:
    """Whether a result stops a change: any failure or error, and flaky safety tests."""
    return result["status"] in ("fail", "error") or (result["status"] == "flaky" and result["tier"] == "safety")


def cache_key(agent: dict, test: dict, rerun: bool = True, clinic: dict | None = None) -> str:
    """A hash of everything that decides a result: the agent (without canvas positions
    and stages), the test, the world it starts from, the models, the runner version, and
    whether a failure is rerun (only when it is not, so existing keys stay the same)."""
    agent = copy.deepcopy(agent)
    for node in agent.get("nodes", []):
        if isinstance(node, dict):
            node.pop("ui", None)
            node.pop("stage", None)
    inputs = {
        "agent": agent,
        "test": test,
        "world": resolve_world(test, _clinic(agent, clinic)),
        "models": [agent.get("model", DEFAULT_MODEL), config.CALLER_MODEL, config.JUDGE_MODEL],
        "runner": config.RUNNER_VERSION,
    }
    if not rerun:
        inputs["rerun"] = False
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def _clinic(agent: dict, clinic: dict | None) -> str | dict:
    return clinic if clinic is not None else clinic_of(agent)
