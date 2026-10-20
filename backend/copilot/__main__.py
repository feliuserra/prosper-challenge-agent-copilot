#
# python -m copilot spec WORKSPACE [--guidelines FILE] [--replace-approved]
# python -m copilot build WORKSPACE [--no-cache]
# python -m copilot record WORKSPACE [--proposal N | --fix N] [--out DIR]
# python -m copilot fix WORKSPACE CALL TURN [--no-cache]
#
# `spec` runs the spec step (#29) on a workspace, as the browser's POST /copilot/.../spec
# does, and prints its progress, then the time, tokens and cost. --guidelines first
# copies a file into the workspace, as a person pasting the client's document: the step
# itself reads only the workspace. Model calls (about $0.35), logged as `copilot`.
#
# `build` runs the build and its loop (#30) on the workspace's approved tests, as POST
# /copilot/.../build does, and prints the proposal. Model calls (the tests are most of
# it: about $1.50 for a 25-test workspace, more with rounds), logged as `copilot`.
#
# `fix` fixes the judge's issue decided at TURN of CALL (#33), from the saved agent
# (agents/WORKSPACE.json), as POST /copilot/.../fix does, and prints the reproduction, the
# candidates and the proposal. Model calls (about $6 on the demo: the continuations and test runs are most).
#
# `record` writes the panel's recorded streams (#31, recording.py) from what a workspace
# stored: its spec, a proposal (the newest by default) and its test run; with --fix, a
# fix's stream from its report and proposal (#34's cached Act 2). No model calls.
#

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from sim.llm import OpenAIChat, Usage, models

from . import build as build_step
from . import fix as fix_step
from . import recording
from . import spec as spec_step
from .workspace import WORKSPACES_DIR, Workspace

AGENTS = Path(__file__).resolve().parent.parent / "agents"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m copilot")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("spec", help="write a workspace's spec from its guidelines")
    run.add_argument("workspace", help="the workspace (agent) id")
    run.add_argument("--guidelines", type=Path, help="copy this file into the workspace first")
    run.add_argument("--replace-approved", action="store_true", help="replace approved tests")
    run.add_argument("--root", type=Path, default=WORKSPACES_DIR, help=argparse.SUPPRESS)
    built = commands.add_parser("build", help="build the agent from the template and loop until its approved tests pass")
    built.add_argument("workspace", help="the workspace (agent) id")
    built.add_argument("--no-cache", action="store_true", help="run every test again")
    fixing = commands.add_parser("fix", help="fix the judge's issue at a turn of a call, from the saved agent")
    fixing.add_argument("workspace", help="the workspace (agent) id")
    fixing.add_argument("call", help="the call id, such as lg-1019-0804")
    fixing.add_argument("turn", type=int, help="the issue's decisive turn")
    fixing.add_argument("--no-cache", action="store_true", help="run every test again")
    recorded = commands.add_parser("record", help="write replayable streams from a workspace's stored spec and proposal")
    recorded.add_argument("workspace", help="the workspace (agent) id")
    recorded.add_argument("--proposal", type=int, help="the proposal to replay (default: the newest)")
    recorded.add_argument("--fix", type=int, help="record the fix stream of this fix's report instead")
    recorded.add_argument("--out", type=Path, help="the folder (default: copilot/recordings/WORKSPACE)")
    args = parser.parse_args(argv)

    if args.command == "record":
        out = args.out or recording.RECORDINGS / args.workspace
        try:
            if args.fix:
                paths = [recording.write_from_fix(Workspace(args.workspace), out, args.fix)]
            else:
                paths = recording.write_from_workspace(Workspace(args.workspace), out, args.proposal)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        for path in paths:
            print(path)
        return 0

    if args.command == "fix":
        load_dotenv(Path(__file__).parent.parent / ".env", override=True)
        logger.disable("agent_builder")
        ws = Workspace(args.workspace)
        path = AGENTS / f"{args.workspace}.json"
        if not path.is_file():
            print(f"error: no saved agent {path}", file=sys.stderr)
            return 1
        agent = json.loads(path.read_text())
        try:
            report = asyncio.run(fix_step.run(
                ws, args.call, args.turn, agent, OpenAIChat("copilot"), models("copilot"), show,
                base=build_step.saved_hash(AGENTS, args.workspace), use_cache=not args.no_cache,
            ))
        except build_step.BuildError as error:
            print(f"error: {error}", file=sys.stderr)
            for problem in error.problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print(fix_summary(report, ws))
        return 0 if report["outcome"] == "proposal" else 1

    if args.command == "build":
        load_dotenv(Path(__file__).parent.parent / ".env", override=True)
        logger.disable("agent_builder")  # the builder logs every transition and tool call
        try:
            proposal = asyncio.run(build(Workspace(args.workspace), not args.no_cache))
        except build_step.BuildError as error:
            print(f"error: {error}", file=sys.stderr)
            for problem in error.problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print(proposal_summary(proposal))
        return 0 if proposal["status"] == "ready" else 1

    ws = Workspace(args.workspace, args.root)
    if args.guidelines:
        ws.save_guidelines(args.guidelines.read_text())
    load_dotenv(Path(__file__).parent.parent / ".env", override=True)
    try:
        spec = asyncio.run(spec_step.run(ws, OpenAIChat("copilot"), show, replace_approved=args.replace_approved))
    except spec_step.SpecError as error:
        print(f"error: {error}", file=sys.stderr)
        for problem in error.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(summary(spec, ws))
    return 0


async def build(ws: Workspace, use_cache: bool = True, loop: bool = True) -> dict:
    return await build_step.run(ws, OpenAIChat("copilot"), models("copilot") if loop else None, show, use_cache=use_cache, loop=loop)


def show(event: dict) -> None:
    if event["event"] == "backcast":
        print(f"  reproduction on the current agent: {event['passed']}/{event['k']} pass", flush=True)
        return
    if event["event"] == "candidate":
        if "turn" in event:
            t = event["turn"]
            print(f"  candidate {event['number']}: turn replay {t['rate'] or t['error']}: {event['rationale']}", flush=True)
        else:
            print(f"  candidate {event['number']}: full reproduction {event['full']['rate']}", flush=True)
        return
    if event["event"] == "operation":
        op = event["operation"]
        what = op.get("name") or op.get("node") or ""
        print(f"  operation {event['index'] + 1}: {op.get('op')} {what}".rstrip(), flush=True)
        return
    if event["event"] == "tests":
        r = event["results"]
        failing = [f"{t['test_id']} ({t['status']})" for t in r["tests"] if t["status"] != "pass"]
        print(f"{event['label']}: {r['passing']}/{r['total']} pass" + (f"; not passing: {', '.join(failing)}" if failing else ""), flush=True)
        return
    if event["event"] == "round":
        for d in event.get("diagnoses", []):
            print(f"  {d['test']}: {d['link']} (turn {d['turn']}): {d['explanation']}", flush=True)
        print(f"  {'kept' if event['kept'] else 'not kept'}: {event.get('reason', '')}", flush=True)
        return
    if event["event"] == "part" and (event["part"] == "build" or event["part"].startswith("round")):
        if event["status"] == "running":
            print(f"{event['part']}: running", flush=True)
        else:
            for line in event.get("outline", []):
                print(f"  - {line}", flush=True)
        return
    if event["event"] == "part":
        if event["status"] == "running":
            print(f"{event['part']}: running", flush=True)
        else:
            counts = {k: len(v) for k, v in event.items() if isinstance(v, (list, dict)) and k != "configuration"}
            print(f"{event['part']}: done {counts}", flush=True)
    elif event["event"] == "repair":
        print(f"{event['part']}: repair {event['attempt']}, {len(event['problems'])} problem(s)", flush=True)
        for problem in event["problems"][:10]:
            print(f"  - {problem}", flush=True)


def summary(spec: dict, ws: Workspace) -> str:
    gaps = spec_step.gaps(spec)
    usage = Usage(spec["meta"]["usage"])
    tokens = ", ".join(f"{m}: {u['requests']} requests, {u['input']} in ({u['cached']} cached), {u['output']} out" for m, u in usage.data.items())
    cost = spec["meta"]["cost"]
    tiers = {tier: sum(t["tier"] == tier for t in spec["tests"]) for tier in ("safety", "core")}
    return "\n".join(
        [
            f"Spec written to {ws.dir / 'spec.json'}",
            f"  {len(spec['requirements'])} requirements, {len(spec['questions'])} client questions, "
            f"{len(spec['tests'])} tests ({tiers['safety']} safety, {tiers['core']} core)",
            f"  untested: {', '.join(gaps['untested']) or 'none'}; carried by the configuration: "
            f"{len(spec['requirements']) - len(gaps['uncarried'])}",
            f"  {spec['meta']['seconds']} s, {tokens}, about ${cost:.2f}" if cost is not None else f"  {tokens}",
        ]
    )


def proposal_summary(proposal: dict) -> str:
    usage = proposal["meta"]["usage"]
    cost = proposal["meta"]["cost"]
    lines = [
        f"Proposal {proposal['number']}: {proposal['status']}",
        f"  {proposal['configuration_entries']} configuration entries ({len(proposal['configuration_changes'])} edits), "
        f"{len(proposal['operations'])} operations, {len(proposal['rounds'])} round(s), {sum(r.get('kept', False) for r in proposal['rounds'])} kept",
    ]
    if proposal["results"]:
        results = proposal["results"]
        lines.append(f"  tests: {results['before']['passing']}/{results['before']['total']} before, {results['after']['passing']}/{results['after']['total']} after")
    lines += [f"  blocked: {reason}" for reason in proposal["blocked"]]
    lines += [f"  question: {q['question']}" for q in proposal["questions"]]
    lines += [f"  concern about {c.get('test')}: {c.get('why')}" for c in proposal["concerns"]]
    for part in ("copilot", "tests"):
        tokens = ", ".join(f"{m}: {u['requests']} requests, {u['input']} in ({u['cached']} cached), {u['output']} out" for m, u in usage[part].items())
        price = f"about ${cost[part]:.2f}" if cost[part] is not None else "cost unknown"
        lines.append(f"  {part}: {tokens or 'nothing (cached)'}; {price}")
    lines.append(f"  {proposal['meta']['seconds']} s")
    return "\n".join(lines)


def fix_summary(report: dict, ws: Workspace) -> str:
    issue = report["issue"]
    lines = [f"Fix of {issue['label'] or issue['kind']} in {issue['call']} (turn {issue['turn']}): {report['message']}"]
    if report.get("reproduction"):
        r = report["reproduction"]
        lines.append(f"  reproduction {r['test']['id']}: {r['before']['failed']}/{r['before']['k']} fail on the current agent"
                     + (f", {r['after']['passed']}/{r['after']['k']} pass after" if r.get("after") else ""))
        lines += [f"  heard '{c['heard']}' for '{c['said']}' ({c['ticket']})" for c in r["corrections"]]
    if report.get("diagnosis"):
        d = report["diagnosis"]
        lines.append(f"  broken link: {d['link']}: {d['explanation']}")
    if report.get("turn_before"):
        lines.append(f"  turn replay on the current agent: {report['turn_before']['rate']}")
    for c in report.get("candidates", []):
        full = f", full {c['full']['rate']}" if c.get("full") else ""
        chosen = " (chosen)" if c["number"] == report.get("chosen") else ""
        lines.append(f"  candidate {c['number']}{chosen}: turn {c['turn']['rate'] or c['turn']['error']}{full}")
    if report.get("agreement"):
        a = report["agreement"]
        lines.append(f"  turn replay agreed with the full reproduction on {a['agreed']} of {a['of']}; best by turn is best in full: {a['best_turn_is_best_full']}")
    if report.get("proposal"):
        proposal = ws.proposal(report["proposal"])
        lines.append(f"Proposal {proposal['number']}: {proposal['status']}, {len(proposal['operations'])} operations, {len(proposal['rounds'])} round(s)")
        results = proposal["results"]
        lines.append(f"  tests: {results['before']['passing']}/{results['before']['total']} before, {results['after']['passing']}/{results['after']['total']} after")
        lines += [f"  blocked: {reason}" for reason in proposal["blocked"]]
    cost = report["meta"]["cost"]
    lines.append(f"  cost: copilot about ${cost['copilot'] or 0:.2f}, tests and replays about ${cost['tests'] or 0:.2f}; {report['meta']['seconds']} s")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
