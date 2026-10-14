#
# Call signals (#58, tier 1 of detection): every call is checked, with no model call.
# From call summaries (summary.py) and the clinic's records, events and calls are
# counted per clinic, version, week and node. Every signal is a proportion, so one
# test fits all (stats.py, triage.py).
#
# Per call that entered the node:
#   reentry       the call went back from the node to itself or to a node it had
#                 visited before it first reached this one: a loop counts where it
#                 starts, not at the node it goes back to
#   stall         a visit to the node took more than STALL_TURNS agent turns
#   hang_up, transfer, error    the call ended in the node that way
#   tool_error    a catalog tool failed in the node
#   duplicate     a patient registered in the node has an existing patient's birth date
#                 and phone under another name (from the clinic's records)
# Per call that completed in the node (an end node):
#   callback      the same number called again within 48 hours. A callback after a
#                 hang-up is a retry, which the hang-up already counts
# Per booking made in the node:
#   quick_change  the booking was changed or cancelled within 24 hours
#
# A callback or a quick change is known only 48 or 24 hours later, so it counts in the
# week it became known, and one not known by the end of the logs is left out. Weeks
# start on Monday and are named by that date.
#

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

SIGNALS = ("reentry", "stall", "hang_up", "transfer", "error", "tool_error", "duplicate", "callback", "quick_change")
ENTERED = ("reentry", "stall", "hang_up", "transfer", "error", "tool_error", "duplicate")  # per call that entered
STALL_TURNS = 6
CALLBACK_HOURS = 48
QUICK_CHANGE_HOURS = 24

LABELS = {
    "reentry": "re-entries",
    "stall": "stalls",
    "hang_up": "hang-ups",
    "transfer": "transfers",
    "error": "errors",
    "tool_error": "tool errors",
    "duplicate": "duplicate patients",
    "callback": "callbacks within 48 h",
    "quick_change": "bookings changed within 24 h",
}


@dataclass
class Cell:
    """One clinic, version, week and node."""
    k: Counter = field(default_factory=Counter)  # signal -> events
    n: Counter = field(default_factory=Counter)  # signal -> calls (or bookings) it is a share of
    exits: Counter = field(default_factory=Counter)  # edge function -> transitions out of the node
    events: dict = field(default_factory=lambda: defaultdict(list))  # signal -> call ids, in time order

    def add(self, other: "Cell") -> None:
        self.k.update(other.k)
        self.n.update(other.n)
        self.exits.update(other.exits)


@dataclass
class Counts:
    cells: dict = field(default_factory=dict)  # (clinic, version, week, node) -> Cell
    versions: dict = field(default_factory=lambda: defaultdict(dict))  # clinic -> version -> {"from", "to", "calls"}
    weeks: list = field(default_factory=list)  # every week with calls, in order
    calls: int = 0
    end: str = ""  # when the logs stop: the last call's start

    def cell(self, clinic: str, version: int, week: str, node: str) -> Cell:
        key = (clinic, version, week, node)
        cell = self.cells.get(key)
        if cell is None:
            cell = self.cells[key] = Cell()
        return cell

    def clinics(self) -> list[str]:
        return sorted(self.versions)

    def total(self, clinic: str | None = None, version: int | None = None, weeks=None, node: str | None = None,
              not_clinic: str | None = None) -> Cell:
        """The sum of the cells that match."""
        out = Cell()
        for (c, v, w, n), cell in self.cells.items():
            if ((clinic is None or c == clinic) and (not_clinic is None or c != not_clinic)
                    and (version is None or v == version) and (weeks is None or w in weeks)
                    and (node is None or n == node)):
                out.add(cell)
        return out

    def events(self, clinic: str, version: int, weeks, node: str, signal: str) -> list[str]:
        ids = []
        for week in sorted(weeks):
            cell = self.cells.get((clinic, version, week, node))
            if cell:
                ids += cell.events.get(signal, [])
        return ids


def week_of(at: str) -> str:
    day = date.fromisoformat(at[:10])
    return (day - timedelta(days=day.weekday())).isoformat()


def count(calls, records=(), end: str | None = None) -> Counts:
    """Count every signal over call summaries and the clinic's records. `end` is when the
    logs stop (default: the last call's start)."""
    counts = Counts()
    calls = list(calls)
    if not calls:
        return counts
    counts.calls = len(calls)
    counts.end = end or max(c["start"] for c in calls)
    limit = datetime.fromisoformat(counts.end)
    by_id = {}
    by_caller = defaultdict(list)
    for call in calls:
        clinic, version, path = call["clinic"], call["version"], call["path"]
        week = week_of(call["start"])
        span = counts.versions[clinic].setdefault(version, {"from": call["start"], "to": call["start"], "calls": 0})
        span["from"], span["to"] = min(span["from"], call["start"]), max(span["to"], call["start"])
        span["calls"] += 1
        by_id[call["id"]] = call
        by_caller[(clinic, call["caller"])].append(call)

        first, looped, stalled = {}, set(), set()  # first: node -> the step it was first reached
        for i, visit in enumerate(path):
            node = visit[0]
            cell = counts.cell(clinic, version, week, node)
            if node not in first:
                first[node] = i
                for signal in ENTERED:
                    cell.n[signal] += 1
            if visit[1] > STALL_TURNS:
                stalled.add(node)
            if i + 1 < len(path):
                after = path[i + 1]
                cell.exits[after[2] if len(after) > 2 else ""] += 1
                if after[0] == node or first.get(after[0], i + 1) < first[node]:
                    looped.add(node)
        flagged = [(node, "reentry") for node in looped] + [(node, "stall") for node in stalled]
        if call["ended"] in ("hang_up", "transfer", "error"):
            flagged.append((path[-1][0], call["ended"]))
        flagged += [(node, "tool_error") for node in dict.fromkeys(t[0] for t in call["tools"] if not t[2])]
        for node, signal in flagged:
            _event(counts.cell(clinic, version, week, node), signal, call["id"])

    # Callbacks: per completed call, known 48 hours after it ended.
    window = timedelta(hours=CALLBACK_HOURS)
    for same in by_caller.values():
        same.sort(key=lambda c: c["start"])
        for call, after in zip(same, same[1:] + [None]):
            if call["ended"] != "completed":
                continue
            ended = datetime.fromisoformat(call["end"])
            known = ended + window
            if known > limit:
                continue
            cell = counts.cell(call["clinic"], call["version"], week_of(known.isoformat()), call["path"][-1][0])
            cell.n["callback"] += 1
            if after and ended < datetime.fromisoformat(after["start"]) <= known:
                _event(cell, "callback", call["id"])

    # Quick changes: per booking a call made, known 24 hours after it was made.
    changes = defaultdict(list)
    for record in records:
        if record["type"] == "booking_change":
            changes[record["booking"]].append(record["at"])
    window = timedelta(hours=QUICK_CHANGE_HOURS)
    for record in records:
        call = by_id.get(record.get("call")) if record["type"] == "booking" else None
        if call is None:
            continue
        node = _tool_node(call, "book_appointment")
        created = datetime.fromisoformat(record["created"])
        known = created + window
        if node is None or known > limit:
            continue
        cell = counts.cell(call["clinic"], call["version"], week_of(known.isoformat()), node)
        cell.n["quick_change"] += 1
        if any(created < datetime.fromisoformat(at) <= known for at in changes.get(record["id"], [])):
            _event(cell, "quick_change", call["id"])

    # Duplicates: a new chart with an existing patient's birth date and phone, another name.
    names = defaultdict(set)
    patients = sorted((r for r in records if r["type"] == "patient"), key=lambda r: r.get("created") or "")
    for record in patients:
        key = (record["clinic"], record["dob"], record["phone"])
        call = by_id.get(record.get("call"))
        if call is not None and names[key] - {record["name"]}:
            node = _tool_node(call, "register_patient")
            if node is not None:
                _event(counts.cell(call["clinic"], call["version"], week_of(call["start"]), node), "duplicate", call["id"])
        names[key].add(record["name"])

    counts.weeks = sorted({w for (_, _, w, _), cell in counts.cells.items() if cell.n["reentry"]})
    return counts


def _event(cell: Cell, signal: str, call_id: str) -> None:
    cell.k[signal] += 1
    cell.events[signal].append(call_id)


def _tool_node(call: dict, tool: str) -> str | None:
    """The node where a tool last succeeded in a call."""
    return next((t[0] for t in reversed(call["tools"]) if t[1] == tool and t[2]), None)
