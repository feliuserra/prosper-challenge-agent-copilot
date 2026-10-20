#
# Recorded Copilot streams (#31). The Copilot panel is checked in the browser against a
# stub backend that replays recorded event streams instead of calling models, so the UI
# is built and checked for free. #34's cached fallback starts from the same files.
#
#   COPILOT_RECORD=<dir>   the runner records every stream it serves to <dir>/<step>.jsonl
#   COPILOT_REPLAY=<dir>   the runner serves <dir>/<step>.jsonl instead of running a step
#
# Steps are `spec`, `build`, `tests` and `fix` (#33). A recording is one JSON line per event, with `t`
# (seconds since the stream started); a line without `event` is a note. Replaying keeps
# the order and shortens the waits to at most MAX_GAP seconds; the stored effects (the
# spec, the proposal, the test run) are written by the API, as the real step would.
#
# `python -m copilot record WORKSPACE` writes recordings from what a workspace already
# stored (its spec, a proposal and its run; with --fix, a fix's report and its proposal):
# real model output, no new model calls.
#
# The demo (#34) keeps one folder per agent, `recordings/<agent id>/`: a step started with
# `cached` replays that agent's recording, so a slow step can switch to the rehearsal's
# result, and `make demo REHEARSE=1` records every live step there.
#

import asyncio
import copy
import json
import time
from pathlib import Path

from storage import write_atomic

from .ops import apply_operations, empty_carriers
from .workspace import Workspace, now

STEPS = ("spec", "build", "tests", "fix")
RECORDINGS = Path(__file__).parent / "recordings"
MAX_GAP = 0.6  # seconds between replayed events


class Recorder:
    """Collects a stream's events; `save` writes them once the stream ended well."""

    def __init__(self, path: Path):
        self.path, self.events, self.started = path, [], time.monotonic()

    def add(self, event: dict) -> None:
        self.events.append({**event, "t": round(time.monotonic() - self.started, 2)})

    def save(self) -> None:
        if self.events and self.events[-1]["event"] == "done":
            write(self.path, self.events, f"Recorded from a live run on {now()}.")


def write(path: Path, events: list[dict], note: str) -> None:
    lines = [json.dumps({"note": note})] + [json.dumps(e, ensure_ascii=False) for e in events]
    write_atomic(path, "\n".join(lines) + "\n")


def read(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"No recording at {path}.")
    lines = (json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return [line for line in lines if "event" in line]


def replayer(path: Path, finish):
    """A step's work (`work(emit)`) that replays a recording; `finish(done)` stores what
    the step would and returns the `done` event to send."""

    async def work(emit) -> None:
        last = 0.0
        for event in read(path):
            t = event.pop("t", last)
            await asyncio.sleep(min(max(t - last, 0.0), MAX_GAP))
            last = t
            emit(finish(event) if event["event"] == "done" else event)

    return work


# ---- recordings from a workspace's stored state ----------------------------------------------
def from_workspace(ws: Workspace, proposal_number: int | None = None) -> dict[str, list[dict]]:
    """The three streams rebuilt from what the workspace stored: the spec (its tests as
    drafts again, as a spec step writes them), a proposal (the newest by default) with
    the operations replayed on the template, and that proposal's test run."""
    from . import build as build_step
    from . import spec as spec_step

    spec = ws.spec()
    if not spec.get("tests"):
        raise ValueError(f"Workspace '{ws.id}' has no spec yet.")
    proposal = ws.proposal(proposal_number) if proposal_number else ws.last_proposal()
    if proposal is None:
        raise ValueError(f"Workspace '{ws.id}' has no proposal {proposal_number or ''}.".replace("  ", " "))
    proposal = {k: v for k, v in proposal.items() if k not in ("number", "decision")}

    drafted = copy.deepcopy(spec)
    for test in drafted["tests"]:
        test["status"] = "draft"
    drafted.pop("meta", None)
    spec_events = [
        {"event": "part", "part": "requirements", "status": "running"},
        {"event": "part", "part": "requirements", "status": "done", "requirements": drafted["requirements"], "questions": drafted["questions"]},
        {"event": "part", "part": "configuration", "status": "running"},
        {"event": "part", "part": "configuration", "status": "done", "configuration": drafted["configuration"]},
        {"event": "part", "part": "tests", "status": "running"},
        {"event": "part", "part": "tests", "status": "done", "tests": drafted["tests"]},
        {"event": "done", "spec": {**drafted, "gaps": spec_step.gaps(drafted)}},
    ]

    # The build's own operations come first; kept rounds added theirs after them.
    fixes = sum(len(r.get("operations", [])) for r in proposal["rounds"] if r.get("kept"))
    authored = proposal["operations"][: len(proposal["operations"]) - fixes]
    agent = build_step.start_agent(ws.id, proposal["configuration"])
    carriers = copy.deepcopy(spec.get("carriers") or empty_carriers())
    build_events = [{"event": "part", "part": "build", "status": "running", "agent": agent}]
    for i, op in enumerate(authored):
        step = apply_operations(agent, [op], carriers)
        agent, carriers = step.agent, step.carriers
        build_events.append({"event": "operation", "index": i, "operation": op, "agent": agent})
    build_events.append({"event": "part", "part": "build", "status": "done", "outline": proposal["outline"], "uncarried": proposal["uncarried"]})
    results = proposal.get("results")
    if results:
        build_events.append({"event": "tests", "label": "before", "results": results["before"]})
    build_events += round_events(proposal)
    build_events.append({"event": "done", "proposal": proposal})

    summary = results["after"] if results else None
    test_events = [{"event": "part", "part": "tests", "status": "running", "total": summary["total"] if summary else 0}]
    for i, row in enumerate(summary["tests"] if summary else []):
        test_events.append({"event": "test", "done": i + 1, "total": summary["total"], "result": row})
    test_events.append({"event": "done", "run": {"created": proposal["created"], "agent_hash": None, "proposal": None, "summary": summary, "cost": None}})

    # Paced like a quick live run: the replay caps each wait anyway.
    streams = {"spec": spec_events, "build": build_events, "tests": test_events}
    for events in streams.values():
        for i, event in enumerate(events):
            event["t"] = float(i)
    return streams


def round_events(proposal: dict) -> list[dict]:
    """The loop's rounds as the build and the fix stream them."""
    events = []
    for record in proposal["rounds"]:
        n = record["round"]
        events.append({"event": "part", "part": f"round {n}", "status": "running"})
        if record.get("rerun"):
            events.append({"event": "tests", "label": f"round {n}: failing tests", "results": record["rerun"]})
        if record.get("full"):
            events.append({"event": "tests", "label": f"round {n}: all tests", "results": record["full"]})
        events.append({"event": "round", **record})
    return events


def from_fix(ws: Workspace, number: int | None = None) -> list[dict]:
    """A fix's stream (#33) rebuilt from its stored report (the newest by default) and
    the proposal it made, in the order fix.run emits it."""
    report = ws.fix(number) if number else ws.last_fix()
    if report is None:
        raise ValueError(f"Workspace '{ws.id}' has no fix {number or ''}.".replace("  ", " "))
    report = {k: v for k, v in report.items() if k != "number"}
    reproduction = report.get("reproduction") or {}
    events = [{"event": "part", "part": "reproduction", "status": "running"}]
    if reproduction:
        events.append({"event": "part", "part": "reproduction", "status": "done", "test": reproduction["test"], "turn_check": reproduction["turn_check"]})
    if reproduction.get("before"):
        events.append({"event": "part", "part": "backcast", "status": "running", "k": reproduction["before"]["k"]})
        events.append({"event": "backcast", **reproduction["before"]})
    if report.get("diagnosis"):
        events.append({"event": "part", "part": "candidates", "status": "running"})
        events.append({"event": "part", "part": "candidates", "status": "done", "diagnosis": report["diagnosis"]})
        for entry in report.get("candidates", []):
            events.append({"event": "candidate", **{k: v for k, v in entry.items() if k not in ("operations", "full")}})
        events.append({"event": "part", "part": "full reproductions", "status": "running"})
        for entry in report.get("candidates", []):
            if entry.get("full"):
                events.append({"event": "candidate", "number": entry["number"], "full": entry["full"]})
    proposal = ws.proposal(report["proposal"]) if report.get("proposal") else None
    if proposal:
        proposal = {k: v for k, v in proposal.items() if k not in ("number", "decision")}
        events.append({"event": "tests", "label": "before: the current agent", "results": proposal["results"]["before"]})
        # The winner's first run is not stored apart: with no round kept it is the final one.
        events.append({"event": "tests", "label": f"candidate {proposal['chosen']}", "results": proposal["results"]["after"]})
        events += round_events(proposal)
        if any(r.get("kept") for r in proposal["rounds"]):
            events.append({"event": "part", "part": "reproduction after", "status": "running"})
    events.append({"event": "done", "fix": report, **({"proposal": proposal} if proposal else {})})
    for i, event in enumerate(events):
        event["t"] = float(i)
    return events


def write_from_workspace(ws: Workspace, out: Path, proposal_number: int | None = None) -> list[Path]:
    note = f"Rebuilt from workspace '{ws.id}' (its stored spec and proposal) on {now()}: real model output, replayed."
    paths = []
    for step, events in from_workspace(ws, proposal_number).items():
        path = Path(out) / f"{step}.jsonl"
        write(path, events, note)
        paths.append(path)
    return paths


def write_from_fix(ws: Workspace, out: Path, number: int | None = None) -> Path:
    path = Path(out) / "fix.jsonl"
    write(path, from_fix(ws, number), f"Rebuilt from workspace '{ws.id}' (a stored fix and its proposal) on {now()}: real model output, replayed.")
    return path


def available(agent_id: str, root: Path = RECORDINGS) -> list[str]:
    """The steps the agent has a recording of, for the demo's cached switch."""
    return [step for step in STEPS if (Path(root) / agent_id / f"{step}.jsonl").is_file()]
