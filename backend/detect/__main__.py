#
# python -m detect synth [--seed N] [--out DIR]
#   writes the synthetic call logs, records and labels (#57) and checks the planted rates
#

import argparse
import sys
import time
from pathlib import Path

from . import synth


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m detect")
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("synth", help="write synthetic call logs with planted defects")
    make.add_argument("--seed", type=int, default=synth.SEED)
    make.add_argument("--out", type=Path, default=synth.OUT_DIR)
    args = parser.parse_args(argv)
    if args.command == "synth":
        return synth_command(args)
    return 2


def synth_command(args) -> int:
    began = time.perf_counter()
    calls, records, labels = synth.write(args.out, args.seed)
    print(f"{len(calls):,} calls and {len(records):,} clinic records, {labels['start']} to {labels['end']} "
          f"(seed {args.seed}), in {time.perf_counter() - began:.1f} s -> {args.out}")
    for clinic in labels["clinics"]:
        counts = {}
        for call in calls:
            if call["clinic"] == clinic["id"]:
                counts[call["version"]] = counts.get(call["version"], 0) + 1
        versions = ", ".join(f"v{v['version']} from {v['from'][5:]}: {counts.get(v['version'], 0):,}" for v in clinic["versions"])
        print(f"  {clinic['name']:<30} {clinic['calls_per_week']:>6,} calls a week  ({versions})")
    rows = synth.check(calls, records, labels)
    print("\nPlanted rates, measured on the logs (labels.json; the detector never reads it):")
    print(f"  {'label':<26} {'clinic':<13} {'node':<19} {'signal':<12} {'base':>6} {'planted':>8} {'measured':>9} {'calls':>7}")
    for row in rows:
        print(f"  {row['id']:<26} {row['clinic']:<13} {row['node']:<19} {row['signal']:<12} "
              f"{row['base']:>6.1%} {row['rate']:>8.1%} {row['measured']:>9.1%} {row['calls']:>7,}  {'ok' if row['ok'] else 'OUT OF TOLERANCE'}")
    return 0 if all(row["ok"] for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
