#
# python -m copilot spec WORKSPACE [--guidelines FILE] [--replace-approved]
#
# Runs the spec step (#29) on a workspace, as the browser's POST /copilot/.../spec
# does, and prints its progress, then the time, tokens and cost. --guidelines first
# copies a file into the workspace, as a person pasting the client's document: the step
# itself reads only the workspace. Model calls (about $0.20), logged as `copilot`.
#

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

from sim.llm import OpenAIChat, Usage

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
    args = parser.parse_args(argv)

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


def show(event: dict) -> None:
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


if __name__ == "__main__":
    sys.exit(main())
