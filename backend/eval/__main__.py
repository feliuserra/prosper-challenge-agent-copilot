#
# make eval:            uv run python -m eval [--agent PATH] [--no-cache] [--only ID]
# make eval MUTANTS=1:  uv run python -m eval --mutants [--no-cache]
# make eval JUDGE=m:    uv run python -m eval --judge MODEL [--only LABEL_ID]
#
# Runs clinic-a's reference suite (eval/clinic-a/tests.json) against an agent, by
# default the reference agent, and prints the runner's table and summary. Results go
# to eval/results/ (gitignored), and the requests to the spend log under `eval`.
# The agent must be one of Linden Grove's: the tests name its patients and ids.
#
# --mutants runs each mutant (eval/mutants.py) once against its own tests and says
# which checks caught it, against the reference agent's cached results: run the
# suite first, so comparing with the reference costs nothing.
#
# --judge grades the reviewed judge labels (eval/judge-labels.json) with a model and
# prints agreement per rule; --only picks label ids.
#

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from agent_builder import validate_agent
from clinic import clinic_of
from sim import config
from sim.__main__ import run_tests
from sim.llm import Usage, models
from sim.runner import cache_key, run_pairs, run_suite
from sim.testfile import load_tests, validate_tests

from . import judge, mutants

HERE = Path(__file__).parent
REFERENCE_AGENT = HERE / "clinic-a" / "reference-agent.json"
TESTS = HERE / "clinic-a" / "tests.json"
RESULTS = HERE / "results"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval")
    parser.add_argument("--agent", type=Path, default=REFERENCE_AGENT, help="the agent to test (default: the reference agent)")
    parser.add_argument("--no-cache", action="store_true", help="run every test again (for numbers we report)")
    parser.add_argument("--only", action="append", metavar="ID", help="run only this test id (repeatable)")
    parser.add_argument("--mutants", action="store_true", help="run each mutant once against its own tests")
    parser.add_argument("--judge", metavar="MODEL", help="grade the reviewed judge labels with this model")
    args = parser.parse_args(argv)
    stamp = f"{datetime.now():%Y-%m-%dT%H%M%S}"
    if args.judge:
        return run_judge(args.judge, args.only, RESULTS / f"{stamp}-judge-{args.judge}.json")
    if args.mutants:
        if args.agent != REFERENCE_AGENT or args.only:
            print("--mutants runs the reference agent's mutants: it takes no --agent or --only.", file=sys.stderr)
            return 2
        return run_mutants(not args.no_cache, RESULTS / f"{stamp}-mutants.json")
    return run_tests(args.agent, TESTS, "eval", not args.no_cache, args.only, RESULTS / f"{stamp}-{args.agent.stem}.json")


def run_mutants(use_cache: bool, out: Path) -> int:
    load_dotenv(HERE.parent / ".env", override=True)
    logger.disable("agent_builder")  # the builder logs every transition and tool call
    agent = json.loads(REFERENCE_AGENT.read_text())
    tests = load_tests(TESTS)
    errors = [f"agent: {e.message}" for e in validate_agent(agent)] + validate_tests(tests, clinic_of(agent))
    missing = [t["id"] for t in tests if not (config.CACHE_DIR / f"{cache_key(agent, t)}.json").is_file()]
    if missing:
        errors.append(f"The reference results are not cached for {', '.join(missing)}: run `make eval` first.")
    if not os.environ.get("OPENAI_API_KEY"):
        errors.append("OPENAI_API_KEY is not set (backend/.env)")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2

    chat = models("eval")
    reference = {r["test_id"]: r for r in asyncio.run(run_suite(agent, tests, chat))}  # all from the cache
    todo = mutants.pairs(agent, tests)
    started = time.monotonic()
    results = asyncio.run(run_pairs([(a, t) for _, a, t in todo], chat, use_cache, rerun=False))
    seconds = time.monotonic() - started

    rows = [
        {"mutant": m.id, "kind": m.kind, "breaks": m.breaks, "test_id": t["id"], "status": r["status"],
         "caught_by": mutants.catching_checks(r, reference[t["id"]]), "result": r}
        for (m, _, t), r in zip(todo, results)
    ]
    print(f"Mutants of {agent['name']}, each run once against its own tests\n")
    print(table(rows))
    print("\n" + summary(rows, seconds, mutants.uncovered(tests)))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    print(f"Results written to {out}")
    return 0 if all(caught(rows, m.id) for m in mutants.MUTANTS) else 1


def run_judge(model: str, only: list[str] | None, out: Path) -> int:
    load_dotenv(HERE.parent / ".env", override=True)
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set (backend/.env)", file=sys.stderr)
        return 2
    rules, labels = judge.load()
    if only:
        labels = [label for label in labels if label["id"] in only]
        if not labels:
            print(f"no label with id {', '.join(only)}", file=sys.stderr)
            return 2
    rows, usage = asyncio.run(judge.grade(rules, labels, model, models("eval").judge))
    print(judge.report(rows, model, usage))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": model, "rows": rows, "usage": usage.data}, indent=1, ensure_ascii=False) + "\n")
    print(f"Results written to {out}")
    return 0 if judge.passes(rows) else 1


def caught(rows: list[dict], mutant: str) -> bool:
    return any(row["caught_by"] for row in rows if row["mutant"] == mutant)


def describe(check: dict) -> str:
    what = check.get("rule") or check.get("tool") or ", ".join(check.get("tools", [])) or check.get("reason", "")
    return f"{check['type']} {what[:70]}{'...' if len(what) > 70 else ''}".strip()


def table(rows: list[dict]) -> str:
    lines = [("MUTANT", "KIND", "TEST", "RESULT", "CAUGHT BY")]
    for row in rows:
        if row["status"] == "error":
            result, by = "error", row["result"].get("error", "")
        else:
            result = "caught" if row["caught_by"] else "survived"
            by = "; ".join(describe(c) for c in row["caught_by"])
        lines.append((row["mutant"], row["kind"], row["test_id"], result + (" (cached)" if row["result"].get("cached") else ""), by))
    widths = [max(len(line[i]) for line in lines) for i in range(4)]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(line[:4], widths)) + "  " + line[4] for line in lines)


def summary(rows: list[dict], seconds: float, uncovered: list[str]) -> str:
    ids = list(dict.fromkeys(row["mutant"] for row in rows))
    survived = [m for m in ids if not caught(rows, m)]
    parts = [f"{len(ids) - len(survived)} of {len(ids)} mutants caught in {seconds:.1f}s ({len(rows)} simulated calls)"]
    for m in survived:
        breaks = next(row["breaks"] for row in rows if row["mutant"] == m)
        parts.append(f"  survived: {m} ({breaks})")
    parts.append("Every test is designed to catch at least one mutant." if not uncovered else f"No mutant targets: {', '.join(uncovered)}")
    usage = Usage()
    for row in rows:
        if not row["result"].get("cached"):
            usage.merge(row["result"].get("usage", {}))
    if usage.data:
        cost = usage.cost()
        parts.append(f"Estimated cost ${cost:.3f}:" if cost is not None else "Cost unknown (a model has no price in sim/config.py):")
        parts += [f"  {m}: {u['requests']} requests, {u['input']} tokens in ({u['cached']} cached), {u['output']} out" for m, u in sorted(usage.data.items())]
    return "\n".join(parts)


if __name__ == "__main__":
    sys.exit(main())
