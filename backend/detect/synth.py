#
# Synthetic call logs with planted defects (#57): production-scale call data for
# detection (#58) at no model cost. The scheduling template's graph is walked with a
# probability for each outcome at each node, for three clinics over six weeks, and
# every call is written as a summary (summary.py) plus the clinic records it left.
# Defects are planted at known rates and listed in a label file that the detector
# never reads, so detection can be measured. The same seed gives the same files.
#
# Output (gitignored), in backend/.synth/:
#   calls.jsonl     one call summary per line, in start order
#   records.jsonl   the clinics' records, in time order, one of:
#                     {"type": "patient", "clinic", "id", "name", "dob", "phone", "created", "call"}
#                       (created and call are null for a patient registered before the logs start)
#                     {"type": "booking", "clinic", "id", "patient", "created", "call"}
#                     {"type": "booking_change", "clinic", "booking", "at", "action", "call"}
#                       (action "rescheduled" or "cancelled"; call is null for the front desk)
#   labels.json     the scenario: clinics and versions, the planted defects with their
#                   base and planted rates, and what must not be flagged
#
# Rates are per call that entered the node, as the detector measures them: `reentry`
# (the call went back from the node to one it had already visited: itself or an earlier
# node, so a loop is counted where it starts), `hang_up`, `transfer`, `error` (the call ended there that way),
# `tool_error` (a catalog tool failed there) and `duplicate` (a patient registered
# there matches an existing patient's birth date and phone under another name). Two
# come from what happened after the call: `callback` (per call that ended in the node:
# the same number called again within 48 hours) and `quick_change` (per booking made
# in the node: changed or cancelled within 24 hours).
#

import copy
import heapq
import itertools
import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
TEMPLATE = BACKEND / "agents" / "prosper-scheduler.json"
OUT_DIR = BACKEND / ".synth"
SEED = 57

SIGNALS = ("reentry", "hang_up", "transfer", "error", "tool_error", "duplicate", "callback", "quick_change")
CALLBACK_HOURS = 48
QUICK_CHANGE_HOURS = 24

# ---- behaviour of the template's nodes, the same at every clinic -----------------------
# turns: (least, mean extra) agent turns per visit. exits: weights of the forward edges
# (equal when absent). loops: edges that re-enter the node or an earlier one, with
# weights; `reentry` is the chance the first visit takes one, REPEAT_LOOP a later visit's.
NODES = {
    "greeting": {"turns": (1, 0.8), "hang_up": 0.08, "transfer": 0.05},
    "ask_name": {"turns": (1, 0.4), "hang_up": 0.015},
    "confirm_name": {"turns": (1, 0.3), "hang_up": 0.01, "reentry": 0.02,
                     "loops": {"correct_spelling": 0.8, "spell_again": 0.2}},
    "verify_patient": {"turns": (2, 1.0), "hang_up": 0.02, "tool_error": 0.004, "duplicate": 0.003,
                       "exits": {"patient_identified": 0.78, "change_appointment": 0.22}},
    "collect_reason": {"turns": (1, 1.0), "hang_up": 0.02, "tool_error": 0.003},
    "offer_times": {"turns": (3, 1.5), "hang_up": 0.03, "tool_error": 0.008, "quick_change": 0.015},
    "confirm": {"turns": (1, 0.3), "callback": 0.03},
    # Callers often hang up once their appointment is cancelled: normal, everywhere.
    "manage_appointment": {"turns": (2, 1.5), "hang_up": 0.25, "tool_error": 0.005,
                           "exits": {"change_done": 0.93, "book_instead": 0.07}},
    "change_confirmed": {"turns": (1, 0.2), "callback": 0.02},
}
OTHER_NODE = {"turns": (1, 1.0), "hang_up": 0.02}  # a node added by customization
ERROR_RATE = 0.001  # a system error ends the call, in any node
REPEAT_LOOP = 0.1
MAX_VISITS = 6
# Calls back within 48 hours, by how the call ended (an end node's own rate wins).
CALLBACK_AFTER = {"completed": 0.03, "hang_up": 0.30, "transfer": 0.05, "error": 0.5}
# Catalog tools a visit calls, with their chance; bookings, registrations and changes
# are added from the visit's outcome.
TOOL_USE = {
    "get_clinic_info": 0.12,
    "lookup_patient": 1.0,
    "list_appointment_types": 0.3,
    "check_coverage": 0.25,
    "find_slots": 1.0,
}
REPEAT_FIND = 0.35
KNOWN_SHARE = 0.82  # callers who are already patients
JITTER = 0.1  # each clinic's rates are the fleet's times 1 +- JITTER, so clinics differ a little

DAY_WEIGHTS = (1.3, 1.1, 1.0, 1.0, 0.9, 0.4, 0.3)  # Monday first
HOUR_WEIGHTS = {7: 0.3, 8: 1.0, 9: 1.4, 10: 1.4, 11: 1.1, 12: 0.8, 13: 0.9, 14: 1.2, 15: 1.2, 16: 1.0,
                17: 0.8, 18: 0.5, 19: 0.2}

FIRST_NAMES = (
    "Ana", "James", "Mei", "Fatima", "Liam", "Sofia", "Noah", "Amara", "Diego", "Hana", "Olivia", "Kwame",
    "Priya", "Lucas", "Yuki", "Elena", "Omar", "Grace", "Mateo", "Aisha", "Ethan", "Leila", "Daniel", "Chloe",
    "Ravi", "Isabel", "Samuel", "Nadia", "Tomas", "Zoe", "Arjun", "Maria", "Felix", "Ingrid", "Kenji", "Rosa",
)
LAST_NAMES = (
    "Lopez", "O'Connor", "Chen", "Okafor", "Patel", "Kim", "Nguyen", "Garcia", "Smith", "Haddad", "Rossi",
    "Kowalski", "Mensah", "Tanaka", "Silva", "Johansson", "Ibrahim", "Murphy", "Novak", "Fischer", "Reyes",
    "Brooks", "Alvarez", "Reed", "Dubois", "Sato", "Hughes", "Moreau", "Costa", "Walsh", "Yilmaz", "Byrne",
)


def scenario() -> dict:
    """The demo scenario: three clinics from the template with different volumes and
    two or three versions each over six weeks, the planted defects and what must not
    be flagged. Rates are absolute; `versions` lists where a defect is active."""
    return {
        "start": "2026-08-31",  # a Monday; six weeks to Sunday 2026-10-11, the eve of Riverside's clock
        "weeks": 6,
        "clinics": [
            {"id": "riverside", "name": "Riverside Family Clinic", "calls_per_week": 11500,
             "versions": [{"version": 1, "from": "2026-08-31"}, {"version": 2, "from": "2026-09-14"},
                          {"version": 3, "from": "2026-09-28"}]},
            {"id": "linden-grove", "name": "Linden Grove Family Practice", "calls_per_week": 1500,
             "versions": [{"version": 1, "from": "2026-08-31"},
                          {"version": 2, "from": "2026-09-21", "add_tools": {"verify_patient": ["transfer_to_human"]}}]},
            {"id": "maple-street", "name": "Maple Street Clinic", "calls_per_week": 150,
             "versions": [{"version": 1, "from": "2026-08-31"}, {"version": 2, "from": "2026-09-21"}]},
        ],
        "defects": [
            {"id": "stall-confirm-name", "shape": "stall", "clinic": "riverside", "versions": [3],
             "node": "confirm_name", "signal": "reentry", "rate": 0.09,
             "what": "Version 3 reads the name back badly: callers correct it again and again."},
            {"id": "tool-errors-booking", "shape": "error", "clinic": "riverside", "versions": [2, 3],
             "node": "offer_times", "signal": "tool_error", "rate": 0.04, "tool": "book_appointment",
             "what": "Version 2 leaves out a booking field, so book_appointment refuses and is retried."},
            {"id": "leak-offer-times", "shape": "leak", "clinic": "linden-grove", "versions": [1, 2],
             "node": "offer_times", "signal": "hang_up", "rate": 0.08,
             "what": "Callers hang up while times are offered, in every version: only other clinics show it."},
            {"id": "detour-verify-transfer", "shape": "detour", "clinic": "linden-grove", "versions": [2],
             "node": "verify_patient", "signal": "transfer", "rate": 0.04,
             "what": "Version 2 transfers callers it cannot find, as the guidelines ask, but also callers who were never patients."},
            {"id": "silent-duplicates", "shape": "silent", "clinic": "linden-grove", "versions": [1],
             "node": "verify_patient", "signal": "duplicate", "rate": 0.025,
             "what": "Version 1 registers a caller it cannot find as a new patient under the misheard name."},
            {"id": "callbacks-after-booking", "shape": "silent", "clinic": "maple-street", "versions": [2],
             "node": "confirm", "signal": "callback", "rate": 0.15,
             "what": "Version 2's confirmation leaves callers unsure, so they call back within 48 hours."},
        ],
        "must_not_flag": [
            {"id": "hang-up-after-cancel", "clinic": "*", "node": "manage_appointment", "signal": "hang_up",
             "why": "Callers hang up once their appointment is cancelled: about 25% everywhere."},
            {"id": "quiet-clinic-noise", "clinic": "maple-street", "node": "*", "signal": "*",
             "why": "150 calls a week: anything flagged there besides the planted callbacks is noise."},
            {"id": "below-min-effect", "clinic": "riverside", "versions": [2, 3], "node": "greeting",
             "signal": "hang_up", "excess": 0.01,
             "why": "A real rise of one point (about 1.12 times): at 50,000 calls a month it is significant, "
                    "but smaller than the minimum effect."},
        ],
    }


# The same kind of defect at several rates and volumes, to find where detection stops
# working (#58): the planted excess over the base, and calls a week (quiet, medium, busy).
SWEEP_EXCESS = (0.005, 0.01, 0.02, 0.03, 0.05)
SWEEP_VOLUMES = (150, 1500, 11500)


def sweep_scenario(calls_per_week: int, excess: float, node: str = "confirm_name", signal: str = "reentry") -> dict:
    """One clinic over four weeks; version 2, from week 3, adds `excess` to one rate."""
    return {
        "start": "2026-09-14",
        "weeks": 4,
        "clinics": [{"id": "sweep", "name": "Sweep clinic", "calls_per_week": calls_per_week,
                     "versions": [{"version": 1, "from": "2026-09-14"}, {"version": 2, "from": "2026-09-28"}]}],
        "defects": [{"id": f"sweep-{node}-{signal}", "shape": "sweep", "clinic": "sweep", "versions": [2],
                     "node": node, "signal": signal, "excess": excess,
                     "what": f"{signal} at {node} up by {excess:.1%} in version 2."}],
        "must_not_flag": [],
    }


# ---- generation -------------------------------------------------------------------------

def generate(scene: dict | None = None, seed: int = SEED, template: dict | None = None) -> tuple[list, list, dict]:
    """(calls, records, labels) for a scenario. Each clinic draws from its own seeded
    stream, so adding a clinic does not change the others."""
    scene = scene or scenario()
    template = template or json.loads(TEMPLATE.read_text())
    start = datetime.fromisoformat(scene["start"])
    end = start + timedelta(weeks=scene["weeks"])
    calls, records, clinics = [], [], []
    for index, clinic in enumerate(scene["clinics"]):
        world = _Clinic(clinic, index, scene, template, seed, start, end)
        world.run()
        calls += world.calls
        records += world.records
        clinics.append(world.label())
    calls.sort(key=lambda c: (c["start"], c["id"]))
    records.sort(key=_record_time)
    labels = {
        "seed": seed,
        "start": _iso(start),
        "end": _iso(end),
        "clinics": clinics,
        "defects": [_with_base(d, clinics) for d in scene["defects"]],
        "must_not_flag": [_with_base(d, clinics) for d in scene["must_not_flag"]],
    }
    return calls, records, labels


def write(out_dir: Path = OUT_DIR, seed: int = SEED, scene: dict | None = None) -> tuple[list, list, dict]:
    calls, records, labels = generate(scene, seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_lines(out_dir / "calls.jsonl", calls)
    _write_lines(out_dir / "records.jsonl", records)
    (out_dir / "labels.json").write_text(json.dumps(labels, indent=2) + "\n")
    return calls, records, labels


def read(out_dir: Path = OUT_DIR) -> tuple[list, list]:
    """The calls and records in a directory, as the detector reads them (no records file:
    no records)."""
    records = out_dir / "records.jsonl"
    return _read_lines(out_dir / "calls.jsonl"), _read_lines(records) if records.exists() else []


def graph_for(template: dict, clinic: dict, version: int) -> dict:
    """The agent a clinic ran in a version: the template plus every customization up to it."""
    agent = copy.deepcopy(template)
    nodes = {node["name"]: node for node in agent["nodes"]}
    for step in clinic["versions"]:
        if step["version"] > version:
            break
        for name, tools in step.get("add_tools", {}).items():
            node = nodes[name]
            node["tools"] = list(node.get("tools", [])) + [t for t in tools if t not in node.get("tools", [])]
    return agent


class _Clinic:
    def __init__(self, clinic: dict, index: int, scene: dict, template: dict, seed: int,
                 start: datetime, end: datetime):
        self.clinic = clinic
        self.id = clinic["id"]
        self.index = index
        self.seed = seed
        self.start, self.end = start, end
        self.rng = random.Random(f"{seed}:{self.id}")
        self.versions = [(datetime.fromisoformat(v["from"]), v["version"]) for v in clinic["versions"]]
        self.graphs, self.rates, self.failing, self.base_rates = {}, {}, {}, {}
        for _, version in self.versions:
            graph = graph_for(template, clinic, version)
            self.graphs[version] = {node["name"]: node for node in graph["nodes"]} | {"": graph["initial_node"]}
            self.rates[version] = self._rates(graph, version, scene)
        self.plans = {version: self._plans(version) for _, version in self.versions}
        self.calls, self.records = [], []
        self.people = 0
        self.patients = 0
        self.bookings = 0

    # ---- rates ---------------------------------------------------------------------------
    def base(self, node: str, signal: str) -> float:
        """The fleet's rate for a node and signal, times this clinic's fixed jitter."""
        if signal == "error":
            fleet = ERROR_RATE
        elif signal.startswith("callback:"):
            fleet = CALLBACK_AFTER[signal.split(":")[1]]
        else:
            fleet = NODES.get(node, OTHER_NODE).get(signal, 0.0)
        jitter = random.Random(f"{self.seed}:{self.id}:{node}:{signal}").uniform(1 - JITTER, 1 + JITTER)
        return fleet * jitter

    def _rates(self, graph: dict, version: int, scene: dict) -> dict:
        rates = {}
        for node in graph["nodes"]:
            name = node["name"]
            for signal in SIGNALS:
                if signal != "callback":
                    rates[(name, signal)] = self.base(name, signal)
            if node.get("end"):
                rates[(name, "callback")] = self.base(name, "callback") if "callback" in NODES.get(name, {}) \
                    else self.base(name, "callback:completed")
        for ending in ("hang_up", "transfer", "error", "completed"):
            rates[("*", "callback:" + ending)] = self.base("*", "callback:" + ending)
        self.base_rates.update(rates)
        for item in scene["defects"] + scene["must_not_flag"]:
            if item["clinic"] == self.id and version in item.get("versions", []) and ("rate" in item or "excess" in item):
                key = (item["node"], item["signal"])
                rates[key] = item["rate"] if "rate" in item else rates[key] + item["excess"]
                if item.get("tool"):
                    self.failing.setdefault(version, {})[item["node"]] = item["tool"]
        return rates

    def label(self) -> dict:
        return {
            "id": self.id,
            "name": self.clinic["name"],
            "calls_per_week": self.clinic["calls_per_week"],
            "calls": len(self.calls),
            "versions": [{"version": v["version"], "from": v["from"], **({"add_tools": v["add_tools"]} if "add_tools" in v else {})}
                         for v in self.clinic["versions"]],
            "base": {f"{node}.{signal}": round(rate, 5) for (node, signal), rate in self.base_rates.items()
                     if node != "*" and rate > 0},
        }

    # ---- the calendar ----------------------------------------------------------------------
    def run(self) -> None:
        rng = self.rng
        queue = []
        seq = 0
        hours, hour_weights = list(HOUR_WEIGHTS), list(HOUR_WEIGHTS.values())
        day = self.start
        per_day = self.clinic["calls_per_week"] / sum(DAY_WEIGHTS)
        while day < self.end:
            mean = per_day * DAY_WEIGHTS[day.weekday()]
            count = max(0, round(rng.gauss(mean, math.sqrt(mean))))
            for hour in rng.choices(hours, hour_weights, k=count):
                at = day + timedelta(hours=hour, seconds=rng.randrange(3600))
                queue.append((at, seq, None))
                seq += 1
            day += timedelta(days=1)
        heapq.heapify(queue)
        while queue:
            at, _, person = heapq.heappop(queue)
            if at >= self.end:
                continue
            person = person or self._person()
            ended_at, back = self._call(at, person)
            if back:
                delay = min(rng.expovariate(1 / (6 * 3600)), (CALLBACK_HOURS - 0.5) * 3600)
                heapq.heappush(queue, (ended_at + timedelta(seconds=120 + delay), seq, person))
                seq += 1

    def _person(self) -> dict:
        rng = self.rng
        self.people += 1
        k = self.people
        return {
            "k": k,
            "name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            "dob": (date(1940, 1, 1) + timedelta(days=rng.randrange(80 * 365))).isoformat(),
            "phone": f"555-{100 * (self.index + 1) + k // 10000:03d}-{k % 10000:04d}",
            "patient": None,  # their patient id, once known
            "booking": None,  # their latest booking id
        }

    def _version(self, at: datetime) -> int:
        version = self.versions[0][1]
        for since, v in self.versions:
            if at >= since:
                version = v
        return version

    # ---- one call --------------------------------------------------------------------------
    def _plans(self, version: int) -> dict:
        """What each node of a version can do, worked out once: the walk only draws."""
        graph, rates = self.graphs[version], self.rates[version]
        plans = {}
        for name, spec in graph.items():
            if not name:
                continue
            behaviour = NODES.get(name, OTHER_NODE)
            edges = spec.get("edges", [])
            functions = {e["function"] for e in edges}
            loops = {f: w for f, w in behaviour.get("loops", {}).items() if f in functions}
            weights = behaviour.get("exits", {})
            forward = [e["function"] for e in edges if e["function"] not in loops]
            tools = [t for t in spec.get("tools", []) if t != "transfer_to_human"]
            least, extra = behaviour["turns"]
            r = lambda signal: rates[(name, signal)]
            plans[name] = {
                "end": bool(spec.get("end")),
                "least": least,
                "more": extra / (1 + extra),
                "tools": tools,
                "use": [(t, TOOL_USE[t]) for t in tools if t in TOOL_USE],
                "loops": (list(loops), list(itertools.accumulate(loops.values()))) if loops else None,
                "forward": (forward, list(itertools.accumulate(weights.get(f, 1.0) for f in forward))),
                "main": max(forward, key=lambda f: weights.get(f, 1.0)) if forward else None,
                "target": {e["function"]: e["target"] for e in edges},
                # Chances, in the order a visit draws them.
                "hang_up": r("hang_up"),
                "transfer": r("transfer") if "transfer_to_human" in spec.get("tools", []) else 0.0,
                "error": r("error"),
                "reentry": r("reentry"),
                "duplicate": r("duplicate") if "register_patient" in tools else 0.0,
                "tool_error": r("tool_error") if tools else 0.0,
                "quick_change": r("quick_change"),
                "failing": self.failing.get(version, {}).get(name),
                "registers": "register_patient" in tools,
                "books": "book_appointment" in tools,
                "changes": [t for t in ("cancel_appointment", "reschedule_appointment") if t in tools],
            }
        return plans

    def _call(self, at: datetime, person: dict) -> tuple[datetime, bool]:
        rng = self.rng
        random_ = rng.random
        version = self._version(at)
        plans, rates = self.plans[version], self.rates[version]
        call_id = f"{self.id}-{len(self.calls) + 1:06d}"
        seconds = 0.0
        path, tools = [], []
        visits = {}
        node, via = self.graphs[version][""], None
        ended = None
        while ended is None:
            plan = plans[node]
            visits[node] = visits.get(node, 0) + 1
            first = visits[node] == 1
            turns = plan["least"]
            while random_() < plan["more"]:
                turns += 1
            seconds += rng.uniform(8, 22) * turns
            path.append([node, turns, via] if via else [node, turns])
            calls = [t for t, chance in plan["use"] if random_() < chance]
            if "find_slots" in calls and random_() < REPEAT_FIND:
                calls.append("find_slots")

            # What the visit ends in.
            duplicate = first and plan["duplicate"] and random_() < plan["duplicate"]
            edge = None
            if plan["end"]:
                outcome = "completed"
            elif duplicate:
                outcome, edge = "forward", plan["main"]  # registered as new: carries on as the main path does
            else:
                u = random_()
                loop = (plan["reentry"] if first else REPEAT_LOOP) if plan["loops"] and visits[node] < MAX_VISITS else 0.0
                cut = plan["hang_up"]
                if u < cut:
                    outcome = "hang_up"
                elif u < (cut := cut + plan["transfer"]):
                    outcome = "transfer"
                elif u < (cut := cut + plan["error"]):
                    outcome = "error"
                elif u < cut + loop:
                    outcome = "loop"
                    edge = rng.choices(plan["loops"][0], cum_weights=plan["loops"][1])[0]
                elif plan["forward"][0]:
                    outcome = "forward"
                    edge = rng.choices(plan["forward"][0], cum_weights=plan["forward"][1])[0]
                else:
                    outcome = "hang_up"  # a dead end: the caller gives up
            main_exit = edge is not None and edge == plan["main"]

            # What the clinic's system records.
            if plan["registers"] and outcome == "forward":
                if duplicate:
                    self._known(person)
                    calls.append("register_patient")
                    self._patient(_garble(person["name"], rng), person, _iso(at + timedelta(seconds=seconds)), call_id)
                elif person["patient"] is None:
                    if not main_exit or random_() < KNOWN_SHARE:  # only patients have appointments to change
                        self._known(person)
                    else:
                        calls.append("register_patient")
                        person["patient"] = self._patient(person["name"], person, _iso(at + timedelta(seconds=seconds)), call_id)
            if plan["books"] and main_exit:
                calls.append("book_appointment")
                self.bookings += 1
                booking = person["booking"] = f"{self.id}-b{self.bookings:06d}"
                booked = at + timedelta(seconds=seconds)
                self.records.append({"type": "booking", "clinic": self.id, "id": booking, "patient": person["patient"],
                                     "created": _iso(booked), "call": call_id})
                if random_() < plan["quick_change"]:
                    later = booked + timedelta(hours=rng.uniform(1, QUICK_CHANGE_HOURS - 1))
                    self._change(booking, later, rng.choice(("rescheduled", "cancelled")), None)
            if plan["changes"] and (main_exit or outcome == "hang_up"):
                # Callers who hang up here mostly do it once the appointment is cancelled.
                action = "cancelled" if outcome == "hang_up" or random_() < 0.55 else "rescheduled"
                tool = "cancel_appointment" if action == "cancelled" else "reschedule_appointment"
                if tool in plan["changes"]:
                    calls.append(tool)
                    # A booking from these logs, or one made before they start.
                    booking = person["booking"] = person["booking"] or f"{self.id}-pre{person['k']:06d}"
                    self._change(booking, at + timedelta(seconds=seconds), action, call_id)
            visit_tools = [[node, tool, True] for tool in calls]
            if first and plan["tool_error"] and random_() < plan["tool_error"]:
                # A failed call, then (when the visit makes it) the retry that worked.
                failing = plan["failing"] if plan["failing"] in plan["tools"] else (calls[0] if calls else plan["tools"][0])
                retry = next((i for i, t in enumerate(visit_tools) if t[1] == failing), len(visit_tools))
                visit_tools.insert(retry, [node, failing, False])
            tools += visit_tools

            if edge is None:
                ended = outcome
            else:
                via = edge
                node = plan["target"][edge]
        clock = at + timedelta(seconds=round(seconds))
        self.calls.append({
            "id": call_id,
            "source": "synthetic",
            "clinic": self.id,
            "version": version,
            "start": _iso(at),
            "end": _iso(clock),
            "caller": person["phone"],
            "path": path,
            "tools": tools,
            "ended": ended,
        })
        last = path[-1][0]
        chance = rates.get((last, "callback")) if ended == "completed" else None
        if chance is None:
            chance = rates[("*", "callback:" + ended)]
        return clock, random_() < chance

    def _known(self, person: dict) -> None:
        """The caller is a patient from before the logs: the clinic has their record."""
        if person["patient"] is None:
            person["patient"] = self._patient(person["name"], person, None, None)

    def _patient(self, name: str, person: dict, created: str | None, call: str | None) -> str:
        self.patients += 1
        patient = f"{self.id}-p{self.patients:06d}"
        self.records.append({"type": "patient", "clinic": self.id, "id": patient, "name": name, "dob": person["dob"],
                             "phone": person["phone"], "created": created, "call": call})
        return patient

    def _change(self, booking: str, at: datetime, action: str, call: str | None) -> None:
        if at < self.end:
            self.records.append({"type": "booking_change", "clinic": self.id, "booking": booking, "at": _iso(at),
                                 "action": action, "call": call})


def _garble(name: str, rng: random.Random) -> str:
    """The name as speech-to-text misheard it: one letter of the last name changed."""
    first, last = name.split(" ", 1)
    letters = [i for i, c in enumerate(last) if c.isalpha() and i > 0]
    i = rng.choice(letters)
    swap = rng.choice([c for c in "aeioulnrst" if c != last[i].lower()])
    return f"{first} {last[:i]}{swap}{last[i + 1:]}"


# ---- checking the planted rates ----------------------------------------------------------

def measure(calls: list, records: list, *, clinic: str, node: str, signal: str, versions=None, end: str | None = None) -> tuple[int, int]:
    """(events, calls) for one signal at one node, measured on the logs the way the
    label defines it: how the planted rates are checked. `end` is when the logs stop,
    so calls too recent for a 48-hour callback or a 24-hour change are left out."""
    chosen = [c for c in calls if c["clinic"] == clinic and (versions is None or c["version"] in versions)]
    if signal == "callback":
        limit = _iso(datetime.fromisoformat(end) - timedelta(hours=CALLBACK_HOURS)) if end else None
        later = {}
        for call in calls:
            if call["clinic"] == clinic:
                later.setdefault(call["caller"], []).append(call["start"])
        k = n = 0
        for call in chosen:
            if call["path"][-1][0] != node or (limit and call["start"] > limit):
                continue
            n += 1
            until = _iso(datetime.fromisoformat(call["end"]) + timedelta(hours=CALLBACK_HOURS))
            k += any(call["end"] < s <= until for s in later[call["caller"]])
        return k, n
    if signal == "quick_change":
        limit = _iso(datetime.fromisoformat(end) - timedelta(hours=QUICK_CHANGE_HOURS)) if end else None
        made = {c["id"] for c in chosen if [node, "book_appointment", True] in c["tools"]}
        changes = {}
        for r in records:
            if r["type"] == "booking_change":
                changes.setdefault(r["booking"], []).append(r["at"])
        k = n = 0
        for r in records:
            if r["type"] == "booking" and r["call"] in made and not (limit and r["created"] > limit):
                n += 1
                until = _iso(datetime.fromisoformat(r["created"]) + timedelta(hours=QUICK_CHANGE_HOURS))
                k += any(r["created"] < at <= until for at in changes.get(r["id"], []))
        return k, n
    duplicates = set()
    if signal == "duplicate":
        seen = {}
        for r in records:
            if r["type"] == "patient" and r["clinic"] == clinic:
                seen.setdefault((r["dob"], r["phone"]), []).append(r)
        for group in seen.values():
            for r in group:
                if r["call"] and any(o is not r and o["name"] != r["name"] for o in group):
                    duplicates.add(r["call"])
    k = n = 0
    for call in chosen:
        nodes = [visit[0] for visit in call["path"]]
        if node not in nodes:
            continue
        n += 1
        if signal == "reentry":
            k += any(a == node and b in nodes[:i + 1] for i, (a, b) in enumerate(zip(nodes, nodes[1:])))
        elif signal in ("hang_up", "transfer", "error"):
            k += call["ended"] == signal and nodes[-1] == node
        elif signal == "tool_error":
            k += any(t[0] == node and not t[2] for t in call["tools"])
        elif signal == "duplicate":
            k += call["id"] in duplicates and [node, "register_patient", True] in call["tools"]
    return k, n


def check(calls: list, records: list, labels: dict) -> list[dict]:
    """Each planted rate next to the rate measured on the logs, with a tolerance of four
    standard errors (the logs are one draw)."""
    rows = []
    for item in labels["defects"] + labels["must_not_flag"]:
        if "rate" not in item:
            continue
        k, n = measure(calls, records, clinic=item["clinic"], node=item["node"], signal=item["signal"],
                       versions=item["versions"], end=labels["end"])
        p = item["rate"]
        tolerance = 4 * math.sqrt(p * (1 - p) / max(n, 1)) + 0.002
        rows.append({"id": item["id"], "clinic": item["clinic"], "node": item["node"], "signal": item["signal"],
                     "base": item.get("base"), "rate": p, "measured": k / n if n else None, "events": k, "calls": n,
                     "ok": bool(n) and abs(k / n - p) <= tolerance})
    return rows


# ---- helpers -----------------------------------------------------------------------------

def _with_base(item: dict, clinics: list) -> dict:
    """A label with the clinic's own base rate next to the planted one."""
    clinic = next((c for c in clinics if c["id"] == item["clinic"]), None)
    if not clinic or not ("rate" in item or "excess" in item):
        return dict(item)
    base = clinic["base"].get(f"{item['node']}.{item['signal']}", 0.0)
    return {**item, "base": base, "rate": item.get("rate", round(base + item.get("excess", 0.0), 5))}


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


def _record_time(record: dict) -> tuple:
    at = record.get("created") or record.get("at") or ""
    return (at, record["type"], record.get("id") or record.get("booking"))


def _write_lines(path: Path, rows: list) -> None:
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False))
            f.write("\n")


def _read_lines(path: Path) -> list:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]
