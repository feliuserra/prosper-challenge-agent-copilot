#
# CLI:  uv run python -m sim run <agent.json> <tests.json> [--no-cache] [--only ID]
#                                [--out results.json] [--transcripts]
#
# Prints a pass/fail table, the evidence for every failed check, and the time,
# tokens and estimated cost. Exits 1 when a result blocks a change (a failure,
# an error or a flaky safety test), 2 when the agent or the tests are invalid.
#

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from agent_builder import validate_agent
from clinic import clinic_of

from . import config
from .checks import render_transcript
from .llm import Usage, models
from .runner import blocking, run_suite
from .testfile import load_tests, validate_tests


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sim")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run tests against an agent and print a pass/fail table")
    run.add_argument("agent", type=Path)
    run.add_argument("tests", type=Path)
    run.add_argument("--no-cache", action="store_true", help="run every test again (for numbers we report)")
    run.add_argument("--only", action="append", metavar="ID", help="run only this test id (repeatable)")
    run.add_argument("--out", type=Path, help="write the full results as JSON")
    run.add_argument("--transcripts", action="store_true", help="print every run's transcript")
    args = parser.parse_args(argv)

    load_dotenv(Path(__file__).parent.parent / ".env", override=True)
    logger.disable("agent_builder")  # the builder logs every transition and tool call

    agent = json.loads(args.agent.read_text())
    tests = load_tests(args.tests)
    agent_errors = validate_agent(agent)
    errors = [f"agent: {e.message}" for e in agent_errors] + (validate_tests(tests, clinic_of(agent)) if not agent_errors else [])
    if args.only:
        tests = [t for t in tests if isinstance(t, dict) and t.get("id") in args.only]
        if not tests:
            errors.append(f"no test with id {', '.join(args.only)}")
    if not os.environ.get("OPENAI_API_KEY"):
        errors.append("OPENAI_API_KEY is not set (backend/.env)")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2

    started = time.monotonic()
    results = asyncio.run(run_suite(agent, tests, models(), use_cache=not args.no_cache))
    seconds = time.monotonic() - started

    print(f"{agent['name']} ({agent.get('model', 'gpt-4o')}), caller {config.CALLER_MODEL}, judge {config.JUDGE_MODEL}\n")
    print(table(results))
    for result in results:
        details = notes(result)
        if details:
            print(f"\n{result['test_id']} ({result['status']}):\n{details}")
        if args.transcripts:
            for n, run_ in enumerate(result.get("runs", []), 1):
                print(f"\n--- {result['test_id']}, run {n} (ended by {run_['end_reason']}) ---\n{render_transcript(run_['turns'], internal=True)}")
    print("\n" + summary(results, seconds))
    if args.out:
        args.out.write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n")
        print(f"Results written to {args.out}")
    return 1 if any(blocking(r) for r in results) else 0


def table(results: list[dict]) -> str:
    rows = [("TEST", "TIER", "STATUS", "TURNS", "ENDED BY", "TIME", "CHECKS")]
    for r in results:
        run_ = r["runs"][0] if r.get("runs") else None
        checks = run_["checks"] if run_ else []
        rows.append(
            (
                r["test_id"],
                r["tier"],
                r["status"] + (" (cached)" if r.get("cached") else ""),
                str(len(run_["turns"])) if run_ else "-",
                run_["end_reason"] if run_ else "-",
                f"{r['seconds']:.1f}s",
                f"{sum(c['pass'] for c in checks)}/{len(checks)}" if run_ else r.get("error", ""),
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip() for row in rows)


def notes(result: dict) -> str:
    """The evidence for every failed check, and recorded answers a run did not use."""
    if result["status"] == "error":
        return f"  error: {result['error']}"
    lines = []
    for n, run_ in enumerate(result["runs"], 1):
        replay = run_.get("replay")
        if replay and len(replay["used"]) < replay["recorded"]:
            lines.append(
                f"  run {n}: used {len(replay['used'])} of {replay['recorded']} recorded answers, "
                "so it did not fully replay the real call"
            )
        for check in run_["checks"]:
            if check["pass"]:
                continue
            what = check.get("rule") or check.get("tool") or ", ".join(check.get("tools", [])) or ""
            where = f" [turn {check['turn']}]" if check.get("turn") else ""
            quote = f' "{check["quote"]}"' if check.get("quote") else ""
            lines.append(f"  run {n}: {check['type']} {what}: {check['detail']}{where}{quote}")
    return "\n".join(lines)


def summary(results: list[dict], seconds: float) -> str:
    counts = {s: sum(r["status"] == s for r in results) for s in ("pass", "fail", "flaky", "error")}
    usage = Usage()
    for r in results:
        if not r.get("cached"):
            usage.merge(r.get("usage", {}))
    parts = [f"{counts['pass']} passed, {counts['fail']} failed, {counts['flaky']} flaky, {counts['error']} errors in {seconds:.1f}s"]
    cached = sum(bool(r.get("cached")) for r in results)
    if cached:
        parts.append(f"{cached} from cache")
    if usage.data:
        cost = usage.cost()
        parts.append(f"Estimated cost ${cost:.3f}:" if cost is not None else "Cost unknown (a model has no price in sim/config.py):")
        parts += [f"  {m}: {u['requests']} requests, {u['input']} tokens in, {u['output']} out" for m, u in sorted(usage.data.items())]
    return "\n".join(parts)


if __name__ == "__main__":
    sys.exit(main())
