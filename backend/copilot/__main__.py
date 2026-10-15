#
# python -m copilot spec WORKSPACE [--guidelines FILE] [--replace-approved]
# python -m copilot build WORKSPACE [--no-cache]
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

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from sim.llm import OpenAIChat, Usage, models

from . import build as build_step
from . import spec as spec_step
from .workspace import WORKSPACES_DIR, Workspace


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
    args = parser.parse_args(argv)

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


async def build(ws: Workspace, use_cache: bool = True) -> dict:
    return await build_step.run(ws, OpenAIChat("copilot"), models("copilot"), show, use_cache=use_cache)


def show(event: dict) -> None:
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
        f"  tests: {proposal['results']['before']['passing']}/{proposal['results']['before']['total']} before, "
        f"{proposal['results']['after']['passing']}/{proposal['results']['after']['total']} after",
    ]
    lines += [f"  blocked: {reason}" for reason in proposal["blocked"]]
    lines += [f"  question: {q['question']}" for q in proposal["questions"]]
    lines += [f"  concern about {c.get('test')}: {c.get('why')}" for c in proposal["concerns"]]
    for part in ("copilot", "tests"):
        tokens = ", ".join(f"{m}: {u['requests']} requests, {u['input']} in ({u['cached']} cached), {u['output']} out" for m, u in usage[part].items())
        price = f"about ${cost[part]:.2f}" if cost[part] is not None else "cost unknown"
        lines.append(f"  {part}: {tokens or 'nothing (cached)'}; {price}")
    lines.append(f"  {proposal['meta']['seconds']} s")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
