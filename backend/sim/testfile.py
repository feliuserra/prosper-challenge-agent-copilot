#
# The test format (ADR 0010). A test is JSON, like an agent:
#
#   id, title          a slug and one line a human can check against the guidelines
#   tier               "safety" (a failure blocks a change) or "core" (scored)
#   requirements       requirement ids it covers (optional)
#   caller             persona, goal, facts {name: value}, style (optional)
#   world              optional; top-level keys replace those of the agent's clinic
#                      (clinic, providers, patients, appointments, and the configuration
#                      keys of ADR 0016), so a test only writes what differs
#   replay             optional caller turns from a real call: [{question, answer}]
#   hearing            optional [said, heard] pairs: how speech-to-text hears the caller's
#                      words, and the caller the agent's (sim/hearing.py; #33)
#   max_turns          optional, most caller turns before the runner stops the call
#   checks             what must hold; see CHECKS
#
# Checks never name nodes or edge functions, so a test runs on any agent that
# uses the tool catalog. Tool arguments are checked against the tools as the
# test's clinic offers them (its own fields included).
#

import copy
import json
import re
from pathlib import Path

from clinic import CONFIG_KEYS, DEFAULT_CLINIC, TOOLS, ClinicWorld, load_seed, validate_clinic

from . import config

WORLD_KEYS = ("clinic", "providers", "patients", "appointments") + CONFIG_KEYS

TIERS = ("safety", "core")
END_REASONS = ("end_node", "transfer", "caller_hung_up", "max_turns", "agent_loop")
ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")

# Check type -> {parameter: required?}
CHECKS = {
    "tool_called": {"tool": True, "args": False, "result": False},
    "tool_not_called": {"tool": True, "args": False, "result": False},
    "tool_order": {"tools": True},
    "call_ended": {"reason": False},
    "transferred": {},
    "max_turns": {"max": True},
    "judge": {"rule": True},
}


def load_tests(path) -> list[dict]:
    """A file holds {"tests": [...]} or a bare list of tests."""
    data = json.loads(Path(path).read_text())
    return data["tests"] if isinstance(data, dict) and "tests" in data else data


def resolve_world(test: dict, clinic: str | dict = DEFAULT_CLINIC) -> dict:
    """The clinic a test starts from: the clinic's seed with the test's top-level keys replaced.
    `clinic` is a clinic id, or a clinic file itself (the Copilot's draft configuration, #29)."""
    world = copy.deepcopy(clinic) if isinstance(clinic, dict) else load_seed(clinic)
    world.update(test.get("world") or {})
    return world


def validate_tests(tests, clinic: str | dict = DEFAULT_CLINIC) -> list[str]:
    """Every problem with a list of tests for an agent of `clinic` (an id or a clinic file). Empty means valid."""
    if not isinstance(tests, list):
        return ["Tests must be a list."]
    errors, seen = [], set()
    for i, test in enumerate(tests):
        label = test.get("id") if isinstance(test, dict) and isinstance(test.get("id"), str) else f"#{i + 1}"
        errors += [f"{label}: {e}" for e in validate_test(test, clinic)]
        if isinstance(test, dict) and test.get("id") in seen:
            errors.append(f"{label}: duplicate id.")
        seen.add(test.get("id") if isinstance(test, dict) else None)
    return errors


def validate_test(test, clinic: str | dict = DEFAULT_CLINIC) -> list[str]:
    if not isinstance(test, dict):
        return ["a test must be an object."]
    errors = []
    world = None  # the test's clinic, once it loads: tool arguments are checked against it
    if not isinstance(test.get("id"), str) or not ID_RE.fullmatch(test["id"]):
        errors.append("id must be a lowercase slug (a-z, 0-9, - and _).")
    if not _text(test.get("title")):
        errors.append("title must be a non-empty string.")
    if test.get("tier") not in TIERS:
        errors.append(f"tier must be one of {', '.join(TIERS)}.")
    requirements = test.get("requirements", [])
    if not isinstance(requirements, list) or not all(isinstance(r, str) for r in requirements):
        errors.append("requirements must be a list of strings.")

    caller = test.get("caller")
    if not isinstance(caller, dict):
        errors.append("caller must be an object with persona, goal, facts and style.")
    else:
        for key in ("persona", "goal"):
            if not _text(caller.get(key)):
                errors.append(f"caller.{key} must be a non-empty string.")
        if not isinstance(caller.get("facts", {}), dict):
            errors.append("caller.facts must be an object.")
        if not isinstance(caller.get("style", ""), str):
            errors.append("caller.style must be a string.")

    overrides = test.get("world")
    if overrides is not None and not isinstance(overrides, dict):
        errors.append("world must be an object.")
    elif overrides and set(overrides) - set(WORLD_KEYS):
        errors.append(f"world has unknown keys: {', '.join(sorted(set(overrides) - set(WORLD_KEYS)))}.")
    else:
        data = resolve_world(test, clinic)
        problems = validate_clinic(data)
        errors += [f"world: {p.path}: {p.message}" for p in problems]
        if not problems:
            try:
                world = ClinicWorld(data)
            except Exception as error:
                errors.append(f"world does not load: {type(error).__name__}: {error}.")

    replay = test.get("replay", [])
    if not isinstance(replay, list) or not all(
        isinstance(r, dict) and isinstance(r.get("question"), str) and _text(r.get("answer")) for r in replay
    ):
        errors.append("replay must be a list of {question, answer} strings.")

    hearing = test.get("hearing", [])
    if not isinstance(hearing, list) or not all(
        isinstance(pair, list) and len(pair) == 2 and all(_text(word) for word in pair) for pair in hearing
    ):
        errors.append("hearing must be a list of [said, heard] pairs of strings.")

    max_turns = test.get("max_turns", config.DEFAULT_MAX_TURNS)
    if not isinstance(max_turns, int) or isinstance(max_turns, bool) or not 1 <= max_turns <= 60:
        errors.append("max_turns must be a whole number from 1 to 60.")

    checks = test.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("checks must be a non-empty list.")
    else:
        for n, check in enumerate(checks, 1):
            errors += [f"check {n}: {e}" for e in validate_check(check, world)]
    return errors


def validate_check(check, world: ClinicWorld | None = None) -> list[str]:
    if not isinstance(check, dict) or check.get("type") not in CHECKS:
        return [f"type must be one of {', '.join(CHECKS)}."]
    kind, params = check["type"], CHECKS[check["type"]]
    errors = [f"{kind} needs {p}." for p, required in params.items() if required and p not in check]
    errors += [f"{kind} has an unknown key '{k}'." for k in check if k != "type" and k not in params]
    if errors:
        return errors
    if "tool" in check:
        if check["tool"] not in TOOLS:
            errors.append(f"unknown tool '{check['tool']}'.")
        elif "args" in check:
            if not isinstance(check["args"], dict):
                errors.append("args must be an object.")
            else:
                spec = world.tool_spec(check["tool"]) if world is not None else TOOLS[check["tool"]]
                errors += [f"{check['tool']} has no parameter '{a}'." for a in check["args"] if a not in spec.properties]
        if "result" in check and (not isinstance(check["result"], dict) or not check["result"]):
            errors.append("result must be a non-empty object: part of what the tool answers.")
    if kind == "tool_order":
        tools = check["tools"]
        if not isinstance(tools, list) or len(tools) < 2:
            errors.append("tools must list at least two tools.")
        else:
            errors += [f"unknown tool '{t}'." for t in tools if t not in TOOLS]
    if kind == "call_ended" and "reason" in check and check["reason"] not in END_REASONS:
        errors.append(f"reason must be one of {', '.join(END_REASONS)}.")
    if kind == "max_turns" and (not isinstance(check["max"], int) or isinstance(check["max"], bool) or check["max"] < 1):
        errors.append("max must be a positive whole number.")
    if kind == "judge" and not _text(check["rule"]):
        errors.append("rule must be a non-empty string.")
    return errors


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())
