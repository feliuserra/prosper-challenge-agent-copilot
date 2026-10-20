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
# python -m demo reset
#   the demo's start (#34): archives the Linden Grove agent and workspace and Act 1's
#   (to backend/.demo-archive/<time>/), installs the seed again and removes Act 1's
#   agent and workspace. `make demo-reset` adds the clinics' state and the synthetic logs.
#

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from copilot.workspace import WORKSPACES_DIR
from sim.llm import models as real_models

from . import evaluate, generate
from .weak import AGENT_ID, weak_agent

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"
SPEC_FROM = WORKSPACES_DIR / "clinic-a" / "spec.json"  # clinic-a's spec (#29): Linden Grove's guidelines
ACT1_ID = "linden-grove-new"  # the agent Act 1 creates ("Linden Grove New"); its recordings replay clinic-a's run
ARCHIVE = Path(__file__).resolve().parent.parent / ".demo-archive"


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
    commands.add_parser("reset", help="archive the demo's agents and workspaces, then install the seed again")
    args = parser.parse_args(argv)
    commands = {"agent": agent_command, "calls": calls_command, "install": install_command, "eval": eval_command, "reset": reset_command}
    return commands[args.command](args)


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
    for folder in ("versions", "calls", "proposals", "runs", "fixes"):
        if force:
            shutil.rmtree(target / folder, ignore_errors=True)
    if force:
        (target / "fixed.json").unlink(missing_ok=True)  # #33's fixed issues
    shutil.copytree(source, target, dirs_exist_ok=True)
    return []


def install_command(args) -> int:
    refused = install(args.force)
    if refused:
        print("\n".join(refused), file=sys.stderr)
        return 1
    print(f"Installed agents/{AGENT_ID}.json and workspaces/{AGENT_ID}/ from the seed.")
    return 0


def reset(agents_dir: Path = AGENTS_DIR, workspaces_dir: Path = WORKSPACES_DIR, archive: Path = ARCHIVE) -> Path | None:
    """Back to the demo's start. What it replaces (an accepted fix, Act 1's build) cost
    model calls and is not in git, so it is moved to `archive/<time>/` first; returns
    that folder, or None when there was nothing to keep."""
    kept = Path(archive) / time.strftime("%Y-%m-%dT%H%M%S")
    moved = False
    for agent_id in (AGENT_ID, ACT1_ID):
        for source, target in ((Path(agents_dir) / f"{agent_id}.json", kept / "agents"), (Path(workspaces_dir) / agent_id, kept / "workspaces")):
            if source.exists():
                target.mkdir(parents=True, exist_ok=True)
                (shutil.copytree if source.is_dir() else shutil.copy2)(source, target / source.name)
                moved = True
    for path in (Path(agents_dir) / f"{ACT1_ID}.json", Path(workspaces_dir) / ACT1_ID):
        shutil.rmtree(path) if path.is_dir() else path.unlink(missing_ok=True)
    shutil.rmtree(Path(workspaces_dir) / AGENT_ID, ignore_errors=True)  # judge results come back with the seed
    install(True, agents_dir, workspaces_dir)
    return kept if moved else None


def reset_command(args) -> int:
    kept = reset()
    print(f"Archived the demo's agents and workspaces to {kept}." if kept else "Nothing to archive.")
    print(f"Installed agents/{AGENT_ID}.json and workspaces/{AGENT_ID}/ from the seed; removed {ACT1_ID} (Act 1 creates it).")
    return 0


def eval_command(args) -> int:
    report = evaluate.evaluate()
    print(evaluate.render(report), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
