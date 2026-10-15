#
# Workspaces (ADR 0013, #28): what the Copilot works from, one folder per agent.
# The agent itself stays in agents/<id>.json, so the Phase 1 API does not change.
#
#   workspaces/<agent-id>/
#     guidelines.md        the client's document, pasted in
#     clinic.json          the approved clinic configuration (#30): the clinic loader
#                          finds it by the workspace's id, so an agent whose `clinic`
#                          is the workspace's id runs against it
#     spec.json            requirements, client questions, the clinic configuration
#                          draft, what carries each requirement, and tests, each
#                          "draft" or "approved" (#29, copilot/spec.py)
#     versions/0001.json   a snapshot per editor save or accepted proposal
#     runs/0001.json       test runs (#30); the newest is the last result (#31)
#     proposals/0001.json  Copilot proposals (#30); the newest is the one shown
#     calls/<id>.json      call records (#32)
#
# A workspace is optional: reading one that does not exist gives empty values, and
# folders are created on the first write. Plain JSON files, written atomically.
#
# Cut on 2026-10-15 (#28): the bot recording live calls, usage per call, chat.json
# (the Copilot panel is rebuilt from this state) and tickets.
#

import copy
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from storage import AGENT_ID_RE, write_atomic

WORKSPACES_DIR = Path(__file__).resolve().parent.parent / "workspaces"

EMPTY_SPEC = {
    "requirements": [],
    "set_aside": [],
    "questions": [],
    "configuration": None,
    "carriers": {"configuration": {}, "nodes": {}, "persona": []},
    "tests": [],
}
VERSION_SOURCES = ("editor", "copilot")
CALL_SOURCES = ("live", "simulated", "production-mock")

NUMBERED_RE = re.compile(r"\d{4,}")


def agent_hash(agent: dict) -> str:
    """A hash of what the agent does. Canvas positions and stages are left out, as in
    the runner's cache key (sim/runner.py), so moving a card is not a new version."""
    agent = copy.deepcopy(agent)
    for node in agent.get("nodes", []):
        if isinstance(node, dict):
            node.pop("ui", None)
            node.pop("stage", None)
    return hashlib.sha256(json.dumps(agent, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Workspace:
    def __init__(self, agent_id: str, root: Path = WORKSPACES_DIR):
        if not AGENT_ID_RE.fullmatch(agent_id):
            raise ValueError("Agent id must be a lowercase slug: a-z, 0-9, '-', '_'.")
        self.id = agent_id
        self.dir = Path(root) / agent_id

    # ---- guidelines and spec ---------------------------------------------------------
    def guidelines(self) -> str:
        path = self.dir / "guidelines.md"
        return path.read_text() if path.is_file() else ""

    def save_guidelines(self, text: str) -> None:
        write_atomic(self.dir / "guidelines.md", text)

    def spec(self) -> dict:
        return _read(self.dir / "spec.json") or copy.deepcopy(EMPTY_SPEC)

    def save_spec(self, spec: dict) -> None:
        # Its shape is checked where it is written (#29); here it is only stored.
        _write(self.dir / "spec.json", spec)

    # ---- versions --------------------------------------------------------------------
    def add_version(self, agent: dict, source: str, message: str = "") -> tuple[dict, bool]:
        """Snapshot the agent unless it does what the newest version does. Returns the
        version's summary (the new one, or the newest when nothing changed) and whether
        it was added."""
        if source not in VERSION_SOURCES:
            raise ValueError(f"Unknown version source '{source}'.")
        digest = agent_hash(agent)
        versions = _numbered(self.dir / "versions")
        if versions:
            newest = _read(versions[-1][1])
            if newest["hash"] == digest:
                return _summary(newest), False
        number = versions[-1][0] + 1 if versions else 1
        version = {"number": number, "source": source, "message": message, "created": now(), "hash": digest, "agent": agent}
        _write(self.dir / "versions" / f"{number:04d}.json", version)
        return _summary(version), True

    def versions(self) -> list[dict]:
        """Every version without its agent, oldest first."""
        return [_summary(_read(path)) for _, path in _numbered(self.dir / "versions")]

    def version(self, number: int) -> dict | None:
        return _read(self.dir / "versions" / f"{number:04d}.json")

    def version_of(self, agent: dict) -> int | None:
        """The newest version that does what `agent` does, if any was saved."""
        digest = agent_hash(agent)
        matches = [v["number"] for v in self.versions() if v["hash"] == digest]
        return matches[-1] if matches else None

    # ---- test runs and proposals (written by #30) -------------------------------------
    def save_run(self, run: dict) -> int:
        return _append(self.dir / "runs", run)

    def last_run(self) -> dict | None:
        return _newest(self.dir / "runs")

    def save_proposal(self, proposal: dict) -> int:
        """Store a proposal with its `number` (set on the dict too) and return the number."""
        proposal["number"] = _next(self.dir / "proposals")
        return _append(self.dir / "proposals", proposal)

    def last_proposal(self) -> dict | None:
        return _newest(self.dir / "proposals")

    def proposal(self, number: int) -> dict | None:
        return _read(self.dir / "proposals" / f"{number:04d}.json") if number > 0 else None

    # ---- calls -----------------------------------------------------------------------
    def save_call(
        self, record: dict, agent: dict, source: str, *, id: str | None = None, start: str | None = None, end: str | None = None
    ) -> dict:
        """Store a call as a call record: the text runner's record (sim/conversation.py,
        with the context the model was given on each turn), plus where it came from and
        the agent that ran it. The record's `agent` (the agent's name) becomes the whole
        agent. The record keeps every key replay_turn, continue_from and the call
        summary (detect/summary.py) read, so they take a call record as it is."""
        if source not in CALL_SOURCES:
            raise ValueError(f"Unknown call source '{source}'.")
        if id is None:
            id = f"{source}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        if not AGENT_ID_RE.fullmatch(id):
            raise ValueError("Call id must be a lowercase slug: a-z, 0-9, '-', '_'.")
        call = {
            "id": id,
            "source": source,
            "version": self.version_of(agent),
            "agent_hash": agent_hash(agent),
            "start": start,
            "end": end,
            "agent": agent,
            **{key: value for key, value in record.items() if key != "agent"},
        }
        _write(self.dir / "calls" / f"{id}.json", call)
        return call

    def call(self, id: str) -> dict | None:
        if not AGENT_ID_RE.fullmatch(id):
            return None
        return _read(self.dir / "calls" / f"{id}.json")

    def calls(self) -> list[dict]:
        """Every call without its agent and turns, by start time (unknown last), then id."""
        keys = ("id", "source", "version", "agent_hash", "start", "end", "end_reason")
        calls = [{key: call.get(key) for key in keys} for path in (self.dir / "calls").glob("*.json") if (call := _read(path))]
        return sorted(calls, key=lambda c: (c["start"] is None, c["start"] or "", c["id"]))


def _read(path: Path):
    return json.loads(path.read_text()) if path.is_file() else None


def _write(path: Path, data) -> None:
    write_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _numbered(folder: Path) -> list[tuple[int, Path]]:
    """The numbered files in a folder, in order. Temp files and anything else are skipped."""
    files = [(int(path.stem), path) for path in folder.glob("*.json") if NUMBERED_RE.fullmatch(path.stem)]
    return sorted(files)


def _next(folder: Path) -> int:
    files = _numbered(folder)
    return files[-1][0] + 1 if files else 1


def _append(folder: Path, data) -> int:
    number = _next(folder)
    _write(folder / f"{number:04d}.json", data)
    return number


def _newest(folder: Path):
    files = _numbered(folder)
    return _read(files[-1][1]) if files else None


def _summary(version: dict) -> dict:
    return {key: value for key, value in version.items() if key != "agent"}
