#
# The demo's mock production calls (#32): the text runner's calls of the weak agent
# with the hidden callers in callers.json, stored as `production-mock` call records in
# the seed workspace. Paid: about 7 cents a call with gpt-4o as the agent.
#
# Speech-to-text, simulated (sim/hearing.py): a caller's `garbles` are [said, heard]
# pairs, so "Sarah Burrell" reaches the agent as "Sara Boreal" and the agent's "Sara
# Boreal" reaches the caller as "Sarah Burrell". Spelled letters are not touched.
#

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

from clinic import ClinicWorld, load_seed
from copilot.workspace import Workspace
from sim import config
from sim.caller import Caller
from sim.checks import grade
from sim.conversation import Conversation
from sim.hearing import Hearing, HeardCaller
from sim.llm import Models, Usage
from sim.runner import talk
from sim.testfile import resolve_world, validate_tests

from .weak import AGENT_ID

DEMO_DIR = Path(__file__).resolve().parent
CALLERS = DEMO_DIR / "callers.json"
AGENT = DEMO_DIR / "agent.json"
CHECKS = DEMO_DIR / "checks.json"  # the label aids' results: part of the answer key
SEED_ROOT = DEMO_DIR / "workspace"  # holds the seed workspace, seed/linden-grove/
CLINIC = "linden-grove"
SOURCE = "production-mock"
WORDS_PER_SECOND = 2.5  # to give a call a plausible length from its words


def load_callers() -> list[dict]:
    return json.loads(CALLERS.read_text())["callers"]


def seed_workspace(root: Path = SEED_ROOT) -> Workspace:
    return Workspace(AGENT_ID, root=root)


def call_id(entry: dict) -> str:
    """lg-1019-0804: the clinic, the day and the time the call started."""
    at = datetime.fromisoformat(entry["start"])
    return f"lg-{at:%m%d-%H%M}"


def as_test(entry: dict) -> dict:
    """The runner's test for a hidden caller: its card and checks, in Linden Grove at
    the time the call starts."""
    clinic = load_seed(CLINIC)["clinic"]
    test = {
        "id": entry["id"],
        "title": f"Mock production call {entry['id']}",
        "tier": "core",
        "caller": entry["caller"],
        "world": {"clinic": {**clinic, "now": entry["start"]}},
        "checks": entry["checks"],
    }
    if "max_turns" in entry:
        test["max_turns"] = entry["max_turns"]
    return test


async def simulate(agent: dict, entry: dict, models: Models) -> tuple[dict, list[dict]]:
    """One call: its record and the label aids' results."""
    test = as_test(entry)
    conversation = Conversation(agent, ClinicWorld(resolve_world(test, CLINIC)), models)
    caller = HeardCaller(Caller(test["caller"], models.caller), Hearing(entry.get("garbles")))
    await conversation.start()
    await talk(conversation, caller, test.get("max_turns", config.DEFAULT_MAX_TURNS))
    record = conversation.record()
    usage = conversation.usage
    checks = await grade(record, test["checks"], models.judge, usage)
    return {**record, "usage": usage.data}, checks


def duration(record: dict) -> timedelta:
    words = sum(len((t.get("text") or "").split()) for t in record["turns"])
    return timedelta(seconds=round(words / WORDS_PER_SECOND + 2 * len(record["turns"])))


def problems(callers: list[dict]) -> list[str]:
    errors = validate_tests([as_test(c) for c in callers], CLINIC)
    ids = [call_id(c) for c in callers]
    errors += [f"two callers start at the same minute ({i})" for i in {i for i in ids if ids.count(i) > 1}]
    return errors


async def generate(models: Models, only: set[str] | None = None, force: bool = False, root: Path = SEED_ROOT) -> dict:
    """Run every hidden caller not stored yet (or `only` those) and store each call.
    Returns the usage and which calls were made."""
    agent = json.loads(AGENT.read_text())
    workspace = seed_workspace(root)
    if workspace.version_of(agent) is None:
        raise ValueError("The seed workspace has no version of agent.json: run `python -m demo agent` first.")
    callers = [c for c in load_callers() if only is None or c["id"] in only]
    todo = [c for c in callers if force or workspace.call(call_id(c)) is None]
    results = await asyncio.gather(*(simulate(agent, entry, models) for entry in todo))
    stored = json.loads(CHECKS.read_text()) if CHECKS.is_file() else {}
    usage = Usage()
    for entry, (record, checks) in zip(todo, results):
        usage.merge(record.pop("usage"))
        start = datetime.fromisoformat(entry["start"])
        end = start + duration(record)
        workspace.save_call(record, agent, SOURCE, id=call_id(entry), start=start.isoformat(timespec="seconds"),
                            end=end.isoformat(timespec="seconds"))
        stored[entry["id"]] = {"call": call_id(entry), "end_reason": record["end_reason"], "checks": checks}
    CHECKS.write_text(json.dumps(dict(sorted(stored.items())), indent=2, ensure_ascii=False) + "\n")
    return {"made": [c["id"] for c in todo], "usage": usage}
