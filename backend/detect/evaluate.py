#
# Measuring detection against the planted defects (#58). Only this file reads the label
# file; the detector (signals.py, triage.py) never does.
#
#   evaluate  each planted defect found or missed (and when, against which baseline),
#             false alarms per clinic per week and per 1,000 calls, and every
#             must-not-flag item with the flags that hit it
#   sweep     recall by planted rate and volume: the same defect (re-entries in Confirm
#             name) planted at several rates in a clinic at several volumes, many seeds
#

import os
from concurrent.futures import ProcessPoolExecutor

from . import signals, synth, triage


def matches(flag: dict, defect: dict) -> bool:
    """A flag finds a defect at its clinic, node and signal, while it is active."""
    return (flag["clinic"] == defect["clinic"] and flag["node"] == defect["node"] and flag["signal"] == defect["signal"]
            and flag["version"] in defect["versions"])


def _hits(item: dict, flag: dict) -> bool:
    return all(item[key] in ("*", flag[key]) for key in ("clinic", "node", "signal")) and (
        "versions" not in item or flag["version"] in item["versions"])


def evaluate(counts: signals.Counts, result: dict, labels: dict) -> dict:
    runs = result["runs"]
    defects = labels["defects"]
    planted = []
    for defect in defects:
        hits = [(run["week"], flag) for run in runs for flag in run["flags"] if matches(flag, defect)]
        active = [run["week"] for run in runs
                  if triage.current_version(counts, defect["clinic"], run["week"]) in defect["versions"]]
        planted.append({
            "id": defect["id"], "shape": defect["shape"], "clinic": defect["clinic"], "node": defect["node"],
            "signal": defect["signal"], "versions": defect["versions"], "base": defect["base"], "rate": defect["rate"],
            "found": bool(hits),
            "first_week": hits[0][0] if hits else None,
            "weeks_flagged": len({week for week, _ in hits}),
            "weeks_active": len(active),
            "baselines": sorted({flag["baseline"] for _, flag in hits}),
        })
    false = [{"week": run["week"], **flag} for run in runs for flag in run["flags"]
             if not any(matches(flag, d) for d in defects)]
    clinic_weeks = sum(1 for run in runs for clinic in counts.clinics()
                       if triage.current_version(counts, clinic, run["week"]) is not None)
    must_not = []
    for item in labels["must_not_flag"]:
        hits = [{"week": run["week"], **flag} for run in runs for flag in run["flags"]
                if _hits(item, flag) and not any(matches(flag, d) for d in defects)]
        row = {"id": item["id"], "why": item["why"], "flags": hits}
        if "rate" in item:  # a planted rise: how close it came
            tests = [t for run in runs for t in run["tests"] if _hits(item, t)]
            if tests:
                closest = min(tests, key=lambda t: t["p_adjusted"])
                row["closest"] = {key: closest[key] for key in
                                  ("version", "baseline", "rate", "base_rate", "p_adjusted", "significant", "big_enough")}
        must_not.append(row)
    found = sum(p["found"] for p in planted)
    return {
        "planted": planted,
        "found": found,
        "recall": found / len(planted) if planted else None,
        "false_alarms": false,
        "clinic_weeks": clinic_weeks,
        "false_per_clinic_week": len(false) / clinic_weeks if clinic_weeks else 0.0,
        "false_per_1000_calls": 1000 * len(false) / counts.calls if counts.calls else 0.0,
        "must_not_flag": must_not,
    }


def sweep(volumes=synth.SWEEP_VOLUMES, excesses=synth.SWEEP_EXCESS, trials: int = 10, workers: int | None = None) -> list[dict]:
    """Recall by planted rate and volume, over `trials` seeds per cell."""
    jobs = [(volume, excess, trial) for volume in volumes for excess in excesses for trial in range(trials)]
    workers = workers or min(len(jobs), os.cpu_count() or 1)
    if workers > 1:
        with ProcessPoolExecutor(workers) as pool:
            outcomes = list(pool.map(_sweep_one, jobs, chunksize=1))
    else:
        outcomes = [_sweep_one(job) for job in jobs]
    cells = []
    for volume in volumes:
        for excess in excesses:
            mine = [o for o in outcomes if o["volume"] == volume and o["excess"] == excess]
            cells.append({
                "volume": volume, "excess": excess, "trials": len(mine),
                "base": sum(o["base"] for o in mine) / len(mine),
                "found": sum(o["found"] for o in mine),
                "recall": sum(o["found"] for o in mine) / len(mine),
                "false_alarms": sum(o["false"] for o in mine),
                "clinic_weeks": sum(o["clinic_weeks"] for o in mine),
            })
    return cells


def _sweep_one(job: tuple) -> dict:
    volume, excess, trial = job
    calls, records, labels = synth.generate(synth.sweep_scenario(volume, excess), seed=1000 + trial)
    counts = signals.count(calls, records)
    result = triage.detect(counts)
    (defect,) = labels["defects"]
    flags = [flag for run in result["runs"] for flag in run["flags"]]
    return {
        "volume": volume, "excess": excess, "base": defect["base"],
        "found": any(matches(flag, defect) for flag in flags),
        "false": sum(not matches(flag, defect) for flag in flags),
        "clinic_weeks": len(result["runs"]),
    }


def report(evaluation: dict, cells: list[dict] | None = None) -> str:
    lines = [f"Planted defects found: {evaluation['found']} of {len(evaluation['planted'])}", ""]
    lines.append(f"  {'defect':<26} {'clinic':<13} {'node':<16} {'signal':<12} {'base':>6} {'planted':>8}  found")
    for p in evaluation["planted"]:
        found = (f"week of {triage.week_name(p['first_week'])}, {p['weeks_flagged']} of {p['weeks_active']} weeks, "
                 f"against {' and '.join(p['baselines'])}") if p["found"] else "MISSED"
        lines.append(f"  {p['id']:<26} {p['clinic']:<13} {p['node']:<16} {p['signal']:<12} {p['base']:>6.1%} {p['rate']:>8.1%}  {found}")
    false = evaluation["false_alarms"]
    lines += ["", f"False alarms: {len(false)} in {evaluation['clinic_weeks']} clinic-weeks "
                  f"({evaluation['false_per_clinic_week']:.2f} per clinic per week, "
                  f"{evaluation['false_per_1000_calls']:.3f} per 1,000 calls)"]
    for f in false:
        lines.append(f"  week of {triage.week_name(f['week'])}: {f['clinic']} v{f['version']} {f['node']} {f['signal']} "
                     f"{f['rate']:.1%} against {f['baseline']} {f['base_rate']:.1%}")
    lines += ["", "Must not be flagged:"]
    for item in evaluation["must_not_flag"]:
        state = f"FLAGGED {len(item['flags'])} times" if item["flags"] else "not flagged"
        line = f"  {item['id']:<22} {state}"
        if "closest" in item:
            c = item["closest"]
            line += (f"; closest test: version {c['version']} against {c['baseline']}, {c['rate']:.1%} vs "
                     f"{c['base_rate']:.1%} ({c['rate'] / c['base_rate']:.2f} times), Holm p = {c['p_adjusted']:.3g}, "
                     f"{'significant' if c['significant'] else 'not significant'}, "
                     f"{'above' if c['big_enough'] else 'below'} the minimum effect")
        lines.append(line)
    if cells:
        volumes = sorted({c["volume"] for c in cells})
        excesses = sorted({c["excess"] for c in cells})
        trials = cells[0]["trials"]
        lines += ["", f"Recall by planted rate and volume (re-entries in Confirm name, base about "
                      f"{sum(c['base'] for c in cells) / len(cells):.1%}; a new version for two weeks after two; "
                      f"{trials} seeds each):",
                  "  " + f"{'calls a week':>13}" + "".join(f"{'+' + format(e, '.1%'):>9}" for e in excesses)]
        for volume in volumes:
            row = [c for c in cells if c["volume"] == volume]
            lines.append("  " + f"{volume:>13,}" + "".join(f"{c['recall']:>9.0%}" for c in sorted(row, key=lambda c: c["excess"])))
        false = sum(c["false_alarms"] for c in cells)
        weeks = sum(c["clinic_weeks"] for c in cells)
        lines.append(f"  False alarms in the sweep: {false} in {weeks} clinic-weeks")
    return "\n".join(lines) + "\n"
