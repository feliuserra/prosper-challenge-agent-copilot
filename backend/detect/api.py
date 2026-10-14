#
# GET /composer/detection (#58): the ranked issues and the per-node numbers the canvas
# heatmap draws (#59), from the call logs in a folder (by default the synthetic ones,
# backend/.synth). Read and counted on the first request, then again only when the
# files change.
#

from pathlib import Path

from fastapi import APIRouter

from . import signals, stats, triage
from .synth import read

EXAMPLE_FIELDS = ("id", "clinic", "version", "start", "end", "caller", "path", "tools", "ended")


def make_router(data_dir: Path) -> APIRouter:
    router = APIRouter(prefix="/composer")
    cache: dict = {}

    @router.get("/detection")
    def detection() -> dict:
        calls_file, records_file = data_dir / "calls.jsonl", data_dir / "records.jsonl"
        if not calls_file.exists():
            return {"available": False, "reason": "No call logs yet: run `make synth` to write synthetic ones."}
        key = tuple(f.stat().st_mtime_ns if f.exists() else 0 for f in (calls_file, records_file))
        if cache.get("key") != key:
            calls, records = read(data_dir)
            counts = signals.count(calls, records)
            cache.update(key=key, body=body(counts, triage.detect(counts), calls))
        return cache["body"]

    return router


def body(counts: signals.Counts, result: dict, calls: list) -> dict:
    """What the editor gets: clinics and versions, the ranked issues with their example
    calls, and every node's numbers per clinic and version."""
    examples = {call_id for issue in result["issues"] for call_id in issue["examples"]}
    latest = result["runs"][-1]["week"] if result["runs"] else None
    return {
        "available": True,
        "week": latest,
        "end": counts.end,
        "calls": counts.calls,
        "clinics": [
            {"id": clinic, "versions": [{"version": v, **span} for v, span in sorted(counts.versions[clinic].items())]}
            for clinic in counts.clinics()
        ],
        "issues": result["issues"],
        "example_calls": {c["id"]: {key: c[key] for key in EXAMPLE_FIELDS} for c in calls if c["id"] in examples},
        "nodes": node_numbers(counts, result),
        "settings": {
            "window_weeks": triage.WINDOW_WEEKS, "alpha": triage.ALPHA, "allowance": triage.ALLOWANCE,
            "min_relative": triage.MIN_RELATIVE, "min_absolute": triage.MIN_ABSOLUTE, "min_events": triage.MIN_EVENTS,
            "stall_turns": signals.STALL_TURNS,
        },
        "signals": {signal: {"label": signals.LABELS[signal], "shape": triage.SHAPES[signal]} for signal in signals.SIGNALS},
    }


def node_numbers(counts: signals.Counts, result: dict) -> dict:
    """clinic -> version -> node -> {entered, exits, signals}. Over the whole version (not
    the detector's four-week window); each signal with its rate, its baselines (the
    previous version, and the other clinics in the same weeks) with a raw one-sided
    p-value each, and whether the detector flagged it while that version ran."""
    flagged = {(f["clinic"], f["version"], f["node"], f["signal"], f["baseline"])
               for run in result["runs"] for f in run["flags"]}
    out = {}
    for clinic in counts.clinics():
        out[clinic] = {}
        for version in sorted(counts.versions[clinic]):
            weeks = triage.window(counts, clinic, version, counts.weeks[-1], weeks=len(counts.weeks))
            previous = triage.previous_version(counts, clinic, version)
            previous_weeks = triage.window(counts, clinic, previous, counts.weeks[-1], weeks=len(counts.weeks)) \
                if previous is not None else []
            nodes = sorted({n for (c, v, w, n) in counts.cells if c == clinic and v == version and w in weeks})
            out[clinic][version] = {}
            for node in nodes:
                here = counts.total(clinic, version, weeks, node)
                baselines = {"fleet": counts.total(None, None, weeks, node, not_clinic=clinic)}
                if previous is not None:
                    baselines["version"] = counts.total(clinic, previous, previous_weeks, node)
                numbers = {}
                for signal in signals.SIGNALS:
                    k, n = here.k[signal], here.n[signal]
                    if not n:
                        continue
                    entry = {"k": k, "n": n, "rate": k / n}
                    for kind, base in baselines.items():
                        kb, nb = base.k[signal], base.n[signal]
                        if nb:
                            entry[kind] = {"k": kb, "n": nb, "rate": kb / nb,
                                           "p": stats.p_greater(k, n, kb, nb, triage.ALLOWANCE[kind]),
                                           "flagged": (clinic, version, node, signal, kind) in flagged}
                    numbers[signal] = entry
                out[clinic][version][node] = {"entered": here.n["reentry"], "exits": dict(here.exits), "signals": numbers}
    return out
