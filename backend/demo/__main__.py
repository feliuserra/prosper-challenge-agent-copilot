#
# python -m demo agent [--spec PATH]
#   writes the weak agent (agent.json) and the seed workspace's spec and version 1
# python -m demo calls [--only c01,c02] [--force]
#   makes the mock production calls of the hidden callers not stored yet (model calls,
#   about 7 cents each)
# python -m demo install [--force]
#   installs the seed as agents/linden-grove.json and workspaces/linden-grove/
# python -m demo eval
#   the judge's results on the installed workspace measured against labels.json
#

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from copilot.workspace import WORKSPACES_DIR
from sim.llm import models as real_models

from . import evaluate, generate
from .weak import AGENT_ID, weak_agent

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"
SPEC_FROM = WORKSPACES_DIR / "clinic-a" / "spec.json"  # clinic-a's spec (#29): Linden Grove's guidelines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m demo")
    commands = parser.add_subparsers(dest="command", required=True)
    agent = commands.add_parser("agent", help="write the weak agent and the seed workspace")
    agent.add_argument("--spec", type=Path, default=SPEC_FROM, help="the spec to copy (once; kept after)")
    calls = commands.add_parser("calls", help="make the mock production calls (model calls)")
    calls.add_argument("--only", help="caller ids, comma separated")
    calls.add_argument("--force", action="store_true", help="make them again even when stored")
    install = commands.add_parser("install", help="install the seed as the linden-grove agent and workspace")
    install.add_argument("--force", action="store_true", help="replace an agent or workspace that differs")
    commands.add_parser("eval", help="measure the judge against the labels")
    args = parser.parse_args(argv)
    return {"agent": agent_command, "calls": calls_command, "install": install_command, "eval": eval_command}[args.command](args)


def agent_command(args) -> int:
    agent = weak_agent()
    generate.AGENT.write_text(json.dumps(agent, indent=2, ensure_ascii=False) + "\n")
    workspace = generate.seed_workspace()
    spec_path = workspace.dir / "spec.json"
    if not spec_path.is_file():
        workspace.save_spec(json.loads(args.spec.read_text()))
    version, added = workspace.add_version(agent, "editor", "Weak first version (demo seed, #32)")
    print(f"{generate.AGENT.name}: {len(agent['nodes'])} nodes; seed workspace version {version['number']}"
          f"{' added' if added else ' unchanged'}; {len(workspace.spec()['requirements'])} requirements")
    return 0


def calls_command(args) -> int:
    callers = generate.load_callers()
    errors = generate.problems(callers)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2
    load_dotenv(Path(__file__).parent.parent / ".env", override=True)
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set (backend/.env)", file=sys.stderr)
        return 2
    only = set(args.only.split(",")) if args.only else None
    done = asyncio.run(generate.generate(real_models("demo"), only, args.force))
    cost = done["usage"].cost()
    print(f"Made {len(done['made'])} calls: {', '.join(done['made']) or 'none'}")
    for model, entry in done["usage"].data.items():
        print(f"  {model}: {entry['requests']} requests, {entry['input']:,} input ({entry['cached']:,} cached), {entry['output']:,} output")
    print(f"  about ${cost:.2f}" if cost is not None else "  (a model has no price listed)")
    return 0


def install(force: bool = False, agents_dir: Path = AGENTS_DIR, workspaces_dir: Path = WORKSPACES_DIR) -> list[str]:
    """Copy the seed in. Refuses (returns the reasons) when an installed agent differs
    and `force` is not set. Stored judge results are kept: they are keyed by call."""
    agent_text = generate.AGENT.read_text()
    agent_path = agents_dir / f"{AGENT_ID}.json"
    if agent_path.is_file() and agent_path.read_text() != agent_text and not force:
        return [f"{agent_path} differs from the seed's agent; pass --force to replace it."]
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_path.write_text(agent_text)
    source, target = generate.seed_workspace().dir, Path(workspaces_dir) / AGENT_ID
    for folder in ("versions", "calls", "proposals", "runs"):
        if force:
            shutil.rmtree(target / folder, ignore_errors=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    return []


def install_command(args) -> int:
    refused = install(args.force)
    if refused:
        print("\n".join(refused), file=sys.stderr)
        return 1
    print(f"Installed agents/{AGENT_ID}.json and workspaces/{AGENT_ID}/ from the seed.")
    return 0


def eval_command(args) -> int:
    report = evaluate.evaluate()
    print(evaluate.render(report), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
