#
# python -m detect synth [--seed N] [--out DIR]
#   writes the synthetic call logs, records and labels (#57) and checks the planted rates
# python -m detect run [--dir DIR]
#   the ranked issues as of the last week in the logs (#58)
# python -m detect eval [--dir DIR] [--trials N]
#   detection measured against the planted defects, and recall by rate and volume (#58)
#

import argparse
import json
import sys
import time
from pathlib import Path

from . import evaluate, signals, synth, triage


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m detect")
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("synth", help="write synthetic call logs with planted defects")
    make.add_argument("--seed", type=int, default=synth.SEED)
    make.add_argument("--out", type=Path, default=synth.OUT_DIR)
    run = commands.add_parser("run", help="print the ranked issues")
    run.add_argument("--dir", type=Path, default=synth.OUT_DIR)
    check = commands.add_parser("eval", help="measure detection against the planted defects")
    check.add_argument("--dir", type=Path, default=synth.OUT_DIR)
    check.add_argument("--trials", type=int, default=10, help="seeds per rate and volume in the sweep (0: no sweep)")
    args = parser.parse_args(argv)
    if args.command == "synth":
        return synth_command(args)
    if not (args.dir / "calls.jsonl").exists():
        print(f"No call logs in {args.dir}: run `make synth` first.", file=sys.stderr)
        return 2
    if args.command == "run":
        return run_command(args)
    return eval_command(args)


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


def detect(directory: Path) -> tuple[signals.Counts, dict, float]:
    began = time.perf_counter()
    calls, records = synth.read(directory)
    counts = signals.count(calls, records)
    return counts, triage.detect(counts), time.perf_counter() - began


def run_command(args) -> int:
    counts, result, seconds = detect(args.dir)
    print(triage.report(counts, result), end="")
    print(f"(read, counted and tested in {seconds:.1f} s; no model calls)")
    return 0


def eval_command(args) -> int:
    counts, result, seconds = detect(args.dir)
    labels = json.loads((args.dir / "labels.json").read_text())
    evaluation = evaluate.evaluate(counts, result, labels)
    cells = None
    if args.trials:
        began = time.perf_counter()
        cells = evaluate.sweep(trials=args.trials)
        sweep_seconds = time.perf_counter() - began
    print(evaluate.report(evaluation, cells), end="")
    print(f"\n(detection in {seconds:.1f} s" + (f", sweep in {sweep_seconds:.0f} s" if cells else "") + "; no model calls)")
    out = args.dir / "evaluation.json"
    out.write_text(json.dumps({"evaluation": evaluation, "sweep": cells}, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
