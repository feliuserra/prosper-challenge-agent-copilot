#
# Baselines, tests and triage (#58, tiers 1 and 3 of detection). Each week, for each
# clinic, every node and signal of the version it runs now is compared with two
# baselines:
#   version  the same node in the clinic's previous version: a change that made
#            things worse raises an alarm
#   fleet    the same template node in the other clinics, the same weeks: a node keeps
#            its template name, so a node added by customization has no fleet baseline
# A flag needs a one-sided two-proportion test (stats.py) that survives Holm's
# correction over every test run for that clinic that week, and a minimum effect, so a
# busy agent does not flag tiny differences and a quiet one does not flag noise.
# Clinics really differ a little (their callers, their providers), so against the
# fleet the test asks whether the rate is above 1.2 times the fleet's, not above it,
# and the minimum effect is larger than against the clinic's own previous version.
#
# Triage groups the flags by clinic, node and shape (stall, leak, detour, error,
# silent) and ranks them by severity times the extra calls affected a week (the
# excess over the baseline times the volume), with the trend, the version the
# problem started in, and a few example calls.
#

from datetime import date, timedelta

from . import stats
from .signals import LABELS, SIGNALS, Counts

WINDOW_WEEKS = 4  # a run looks at the current version's last four weeks at most
ALPHA = 0.05
ALLOWANCE = {"version": 1.0, "fleet": 1.2}  # the test's null: the rate is at most this many times the baseline
MIN_RELATIVE = {"version": 1.2, "fleet": 1.5}  # the rate must be this many times the baseline
MIN_ABSOLUTE = 0.002  # and at least 0.2 percentage points above it
MIN_EVENTS = 5  # and come from at least this many calls

SHAPES = {
    "reentry": "stall", "stall": "stall",
    "hang_up": "leak",
    "transfer": "detour",
    "error": "error", "tool_error": "error",
    "duplicate": "silent", "callback": "silent", "quick_change": "silent",
}
SEVERITY = {
    "duplicate": "high", "error": "high",
    "tool_error": "medium", "hang_up": "medium", "transfer": "medium", "callback": "medium", "quick_change": "medium",
    "reentry": "low", "stall": "low",
}
WEIGHT = {"high": 3, "medium": 2, "low": 1}
EXAMPLES = 3


def window(counts: Counts, clinic: str, version: int, week: str, weeks: int = WINDOW_WEEKS) -> list[str]:
    """The weeks of a version, up to `week`, at most the last `weeks` of them."""
    have = sorted({w for (c, v, w, _), cell in counts.cells.items()
                   if c == clinic and v == version and w <= week and cell.n["reentry"]})
    return have[-weeks:]


def current_version(counts: Counts, clinic: str, week: str) -> int | None:
    versions = [v for (c, v, w, _), cell in counts.cells.items() if c == clinic and w == week and cell.n["reentry"]]
    return max(versions) if versions else None


def previous_version(counts: Counts, clinic: str, version: int) -> int | None:
    earlier = [v for v in counts.versions[clinic] if v < version]
    return max(earlier) if earlier else None


def run(counts: Counts, week: str) -> dict:
    """Detection as of the end of `week`: {"flags": [...], "tests": [...]}, every test
    with its Holm-adjusted p-value."""
    flags, tests = [], []
    for clinic in counts.clinics():
        version = current_version(counts, clinic, week)
        if version is None:
            continue
        weeks = window(counts, clinic, version, week)
        previous = previous_version(counts, clinic, version)
        previous_weeks = window(counts, clinic, previous, week) if previous is not None else []
        nodes = sorted({n for (c, v, w, n) in counts.cells if c == clinic and v == version and w in weeks})
        mine = []
        for node in nodes:
            here = counts.total(clinic, version, weeks, node)
            baselines = {"fleet": counts.total(None, None, weeks, node, not_clinic=clinic)}
            if previous is not None:
                baselines["version"] = counts.total(clinic, previous, previous_weeks, node)
            for signal in SIGNALS:
                k, n = here.k[signal], here.n[signal]
                if not n:
                    continue
                for kind, base in baselines.items():
                    kb, nb = base.k[signal], base.n[signal]
                    if not nb or not k + kb:
                        continue  # no calls to compare with, or no events anywhere: nothing to test
                    mine.append({
                        "clinic": clinic, "version": version, "week": week, "node": node, "signal": signal,
                        "baseline": kind, "against": previous if kind == "version" else "other clinics",
                        "k": k, "n": n, "rate": k / n, "base_k": kb, "base_n": nb, "base_rate": kb / nb,
                        "weeks": len(weeks), "p": stats.p_greater(k, n, kb, nb, ALLOWANCE[kind]),
                    })
        for test, adjusted in zip(mine, stats.holm([t["p"] for t in mine])):
            test["p_adjusted"] = adjusted
            test["significant"] = adjusted <= ALPHA
            test["big_enough"] = big_enough(test)
            if test["significant"] and test["big_enough"]:
                flags.append(test)
        tests += mine
    return {"week": week, "flags": flags, "tests": tests}


def big_enough(test: dict) -> bool:
    rate, base = test["rate"], test["base_rate"]
    return (test["k"] >= MIN_EVENTS and rate - base >= MIN_ABSOLUTE
            and rate >= base * MIN_RELATIVE[test["baseline"]])


def detect(counts: Counts) -> dict:
    """Detection as of every week in the logs, and the ranked issues as of the last one."""
    runs = [run(counts, week) for week in counts.weeks]
    return {"runs": runs, "issues": triage(counts, runs) if runs else []}


def triage(counts: Counts, runs: list[dict]) -> list[dict]:
    """The latest run's flags, grouped by clinic, node and shape and ranked."""
    latest = runs[-1]
    groups = {}
    for flag in latest["flags"]:
        groups.setdefault((flag["clinic"], flag["node"], SHAPES[flag["signal"]]), []).append(flag)
    issues = []
    for (clinic, node, shape), flags in groups.items():
        evidence = []
        for flag in flags:
            per_week = flag["n"] / flag["weeks"]
            evidence.append({
                "signal": flag["signal"], "label": LABELS[flag["signal"]], "baseline": flag["baseline"],
                "against": flag["against"], "rate": flag["rate"], "base_rate": flag["base_rate"],
                "k": flag["k"], "n": flag["n"], "p": flag["p_adjusted"],
                "extra_per_week": (flag["rate"] - flag["base_rate"]) * per_week,
            })
        # The excess over the closest baseline: the smaller claim when both flag it.
        by_signal = {}
        for e in evidence:
            if e["signal"] not in by_signal or e["extra_per_week"] < by_signal[e["signal"]]["extra_per_week"]:
                by_signal[e["signal"]] = e
        lead = max(by_signal.values(), key=lambda e: e["extra_per_week"])
        severity = max((SEVERITY[s] for s in by_signal), key=lambda s: WEIGHT[s])
        version = flags[0]["version"]
        since_week, since_version = _since(runs, clinic, node, set(by_signal))
        weeks = window(counts, clinic, version, latest["week"])
        trend = _trend(counts, clinic, node, lead["signal"], latest["week"])
        issues.append({
            "id": f"{clinic}:{node}:{shape}",
            "clinic": clinic,
            "node": node,
            "shape": shape,
            "severity": severity,
            "version": version,
            "signal": lead["signal"],
            "label": lead["label"],
            "rate": lead["rate"],
            "base_rate": lead["base_rate"],
            "baseline": lead["baseline"],
            "extra_per_week": lead["extra_per_week"],
            "score": WEIGHT[severity] * lead["extra_per_week"],
            "since_week": since_week,
            "since_version": since_version,
            "trend": trend,
            "direction": _direction(trend, since_week),
            "evidence": sorted(evidence, key=lambda e: (-e["extra_per_week"], e["baseline"])),
            "examples": counts.events(clinic, version, weeks, node, lead["signal"])[-EXAMPLES:][::-1],
        })
    issues.sort(key=lambda i: (-i["score"], i["id"]))
    return issues


def _since(runs: list[dict], clinic: str, node: str, signals: set) -> tuple[str, int]:
    """The first week of the unbroken run of weeks this problem has been flagged in."""
    since = runs[-1]["week"], runs[-1]["flags"][0]["version"]
    for past in reversed(runs):
        hits = [f for f in past["flags"] if f["clinic"] == clinic and f["node"] == node and f["signal"] in signals]
        if not hits:
            break
        since = past["week"], hits[0]["version"]
    return since


def _trend(counts: Counts, clinic: str, node: str, signal: str, week: str, weeks: int = 6) -> list[dict]:
    """The signal's weekly rate at the node, every version, over the last weeks."""
    out = []
    for w in [w for w in counts.weeks if w <= week][-weeks:]:
        cell = counts.total(clinic, None, [w], node)
        versions = sorted({v for (c, v, ww, n) in counts.cells if c == clinic and ww == w and n == node})
        if cell.n[signal]:
            out.append({"week": w, "versions": versions, "k": cell.k[signal], "n": cell.n[signal],
                        "rate": cell.k[signal] / cell.n[signal]})
    return out


def _direction(trend: list[dict], since_week: str) -> str:
    """new (flagged for the first time this week), rising, falling or steady."""
    flagged = [t for t in trend if t["week"] >= since_week]
    if len(flagged) < 2:
        return "new"
    first, last = flagged[0]["rate"], flagged[-1]["rate"]
    if last > first * 1.15:
        return "rising"
    if last < first / 1.15:
        return "falling"
    return "steady"


def week_name(week: str) -> str:
    return date.fromisoformat(week).strftime("%b %-d")


def report(counts: Counts, result: dict) -> str:
    """The ranked list, as `make detect` prints it."""
    issues = result["issues"]
    week = result["runs"][-1]["week"] if result["runs"] else None
    if week is None:
        return "No calls."
    end = (date.fromisoformat(week) + timedelta(days=6)).strftime("%b %-d")
    lines = [f"{len(issues)} issues for the week of {week_name(week)} to {end} "
             f"({counts.calls:,} calls in the logs, {len(counts.clinics())} clinics), most urgent first:", ""]
    for rank, issue in enumerate(issues, 1):
        name = issue["node"].replace("_", " ").capitalize()
        lines.append(f"{rank}. {issue['clinic']}, {name}: {issue['shape']} ({issue['severity']} severity)")
        for e in issue["evidence"]:
            against = f"version {e['against']}" if e["baseline"] == "version" else "other clinics"
            lines.append(f"   {e['label'].capitalize()}: {e['rate']:.1%} of {e['n']:,} calls in version {issue['version']}, "
                         f"{e['base_rate']:.1%} in {against}")
        lines.append(f"   About {issue['extra_per_week']:,.0f} more calls a week; since version {issue['since_version']} "
                     f"(week of {week_name(issue['since_week'])}), {issue['direction']}")
        if issue["examples"]:
            lines.append(f"   Examples: {', '.join(issue['examples'])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
