#
# make eval:  uv run python -m eval [--agent PATH] [--no-cache] [--only ID]
#
# Runs clinic-a's reference suite (eval/clinic-a/tests.json) against an agent, by
# default the reference agent, and prints the runner's table and summary. Results go
# to eval/results/ (gitignored), and the requests to the spend log under `eval`.
# The agent must be one of Linden Grove's: the tests name its patients and ids.
#

import argparse
import sys
from datetime import datetime
from pathlib import Path

from sim.__main__ import run_tests

HERE = Path(__file__).parent
REFERENCE_AGENT = HERE / "clinic-a" / "reference-agent.json"
TESTS = HERE / "clinic-a" / "tests.json"
RESULTS = HERE / "results"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval")
    parser.add_argument("--agent", type=Path, default=REFERENCE_AGENT, help="the agent to test (default: the reference agent)")
    parser.add_argument("--no-cache", action="store_true", help="run every test again (for numbers we report)")
    parser.add_argument("--only", action="append", metavar="ID", help="run only this test id (repeatable)")
    args = parser.parse_args(argv)
    out = RESULTS / f"{datetime.now():%Y-%m-%dT%H%M%S}-{args.agent.stem}.json"
    return run_tests(args.agent, TESTS, "eval", not args.no_cache, args.only, out)


if __name__ == "__main__":
    sys.exit(main())
