#
# The judge measured against the planted defects (#32): the only reader of labels.json
# and callers.json besides the generator. Reads the judge's stored results for the
# installed workspace (python -m detect judge writes them).
#
#   recall        planted issues that did harm and that the judge found (the acceptance
#                 metric: at least 80%), and every labelled issue, planted or not
#   false alarms  judge issues that match no label of their call (at most one per 5 calls)
#   blame         found planted issues whose decisive turn is in a node the label names
#                 (at least 80%)
#   agreement     judge issues whose second, sampled run put the decisive turn in the
#                 same place
#   caller cards  the hidden caller's facts found in the card the judge inferred
#   tickets       tickets matched to the call they are about
#

import json
import re
import unicodedata
from pathlib import Path

from copilot.workspace import WORKSPACES_DIR, Workspace
from detect import judge

from .generate import CALLERS, call_id
from .weak import AGENT_ID

LABELS = Path(__file__).resolve().parent / "labels.json"
TICKETS = {"T1": "c01", "T2": "c11", "T3": "c16"}  # which caller each ticket is about


def matches(issue: dict, label: dict) -> bool:
    kinds = [issue["kind"], *issue.get("also", [])]
    return any(k in label["kinds"] for k in kinds) or (issue["requirement"] or None) in label["requirements"]


def labels_for(call: dict, labels: dict) -> list[dict]:
    entries = list(labels["calls"].get(call["id"], {}).get("issues", []))
    visited = {node for node, *_ in judge.summary_of(call)["path"]}
    if "ask_name" in visited:
        entries += labels["present"]
    return entries


def evaluate(workspaces_dir: Path = WORKSPACES_DIR) -> dict:
    labels = json.loads(LABELS.read_text())
    callers = {c["id"]: c for c in json.loads(CALLERS.read_text())["callers"]}
    workspace = Workspace(AGENT_ID, root=workspaces_dir)
    calls = {c["id"]: workspace.call(c["id"]) for c in workspace.calls()}
    results = {r["call"]: r for r in judge.results(workspaces_dir).get(AGENT_ID, [])}
    rows, alarms = [], []
    for cid, call in sorted(calls.items()):
        result = results.get(cid)
        if result is None:
            continue
        found = labels_for(call, labels)
        for issue in result["issues"]:
            if not any(matches(issue, label) for label in found):
                alarms.append({"call": cid, **{k: issue[k] for k in ("kind", "requirement", "turn", "node", "summary")}})
        for label in found:
            if not label["issue"]:
                continue
            hits = [i for i in result["issues"] if matches(i, label)]
            rows.append({
                "call": cid,
                "planted": label["planted"],
                "note": label["note"],
                "found": bool(hits),
                "blamed": any(i["node"] in label["nodes"] for i in hits),
                "turns": [i["turn"] for i in hits],
                "nodes": [i["node"] for i in hits],
            })
    judged = len(results)
    issues = [i for r in results.values() for i in r["issues"]]
    planted = [r for r in rows if r["planted"]]
    found = [r for r in planted if r["found"]]
    return {
        "calls": len(calls),
        "judged": judged,
        "planted": rows_by(planted),
        "planted_found": len(found),
        "planted_total": len(planted),
        "blamed": sum(r["blamed"] for r in found),
        "all_found": sum(r["found"] for r in rows),
        "all_total": len(rows),
        "issues": len(issues),
        "false_alarms": alarms,
        "agreed": sum(i["agreed"] for i in issues),
        "cards": cards(results, calls, labels, callers),
        "tickets": tickets(workspace, calls, callers),
        "rows": rows,
        "usage": _usage(results.values()),
    }


def rows_by(rows: list[dict]) -> dict:
    out = {}
    for r in rows:
        entry = out.setdefault(r["planted"], {"total": 0, "found": 0, "blamed": 0})
        entry["total"] += 1
        entry["found"] += r["found"]
        entry["blamed"] += r["found"] and r["blamed"]
    return out


def cards(results: dict, calls: dict, labels: dict, callers: dict) -> list[dict]:
    """For each card, the share of the hidden caller's facts whose value shows in it."""
    out = []
    for cid, result in sorted(results.items()):
        if not result.get("card"):
            continue
        hidden = callers[labels["calls"][cid]["caller"]]["caller"]["facts"]
        card = result["card"]
        text = _words(" ".join([card["persona"], card["goal"], *(f"{k} {v}" for k, v in card["facts"].items())]))
        seen = [k for k, v in hidden.items() if _fact_in(v, text)]
        out.append({"call": cid, "facts": len(hidden), "seen": len(seen), "missed": [k for k in hidden if k not in seen]})
    return out


def _words(text: str) -> set[str]:
    """Lowercase words without accents or punctuation; "3rd" is "3", a spelling "S-A-R-A-H" is "sarah"."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    plain = re.sub(r"\b(\w)-(?=\w\b)", r"\1", plain)  # letters spelled out: s-a-r-a-h
    plain = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", plain)
    return set(re.findall(r"[a-z0-9]+", plain))


def _fact_in(value: str, text: set[str]) -> bool:
    """Most of a hidden fact's words are in the card (words of 3 letters or more, or numbers)."""
    words = [w for w in _words(str(value)) if len(w) > 2 or w.isdigit()]
    return bool(words) and sum(w in text for w in words) >= (len(words) + 1) // 2


def tickets(workspace: Workspace, calls: dict, callers: dict) -> list[dict]:
    expected = {t: call_id(callers[c]) for t, c in TICKETS.items()}
    matched = judge.match_tickets(judge.tickets(workspace), list(calls.values()))
    return [{"ticket": t, "expected": expected.get(t), "matched": ids, "right": ids == [expected.get(t)]}
            for t, ids in sorted(matched.items())]


def _usage(results) -> dict:
    total, cost = {}, 0.0
    for r in results:
        for model, entry in r["usage"].items():
            mine = total.setdefault(model, {"requests": 0, "input": 0, "cached": 0, "output": 0})
            for k in mine:
                mine[k] += entry[k]
        cost += r.get("cost") or 0
    return {"models": total, "cost": cost}


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({a / b:.0%})" if b else "0/0"


def render(report: dict) -> str:
    if not report["judged"]:
        return "No judge results: run `make judge` first.\n"
    lines = [
        f"Judged {report['judged']} of {report['calls']} calls; {report['issues']} issues.",
        f"Planted issues found: {pct(report['planted_found'], report['planted_total'])} (acceptance: 80%)",
    ]
    for defect, entry in sorted(report["planted"].items()):
        lines.append(f"  {defect:<17} found {entry['found']}/{entry['total']}, decisive turn in the defect's node {entry['blamed']}/{entry['found']}")
    lines += [
        f"All labelled issues found (planted or not): {pct(report['all_found'], report['all_total'])}",
        f"False alarms: {len(report['false_alarms'])} in {report['judged']} calls, "
        f"{len(report['false_alarms']) / report['judged'] * 5:.2f} per 5 calls (acceptance: at most 1)",
    ]
    for alarm in report["false_alarms"]:
        lines.append(f"  {alarm['call']} turn {alarm['turn']} ({alarm['node']}): {alarm['kind']} {alarm['requirement']} {alarm['summary']}")
    lines += [
        f"Decisive turn in the planted defect's node: {pct(report['blamed'], report['planted_found'])} (acceptance: 80%)",
        f"Second run put the decisive turn in the same place: {pct(report['agreed'], report['issues'])}",
        "Missed:",
    ]
    lines += [f"  {r['call']} ({r['planted'] or 'not planted'}): {r['note']}" for r in report["rows"] if not r["found"]] or ["  none"]
    seen = sum(c["seen"] for c in report["cards"])
    facts = sum(c["facts"] for c in report["cards"])
    lines.append(f"Caller cards: {len(report['cards'])}, hidden facts seen {pct(seen, facts)}")
    for card in report["cards"]:
        if card["missed"]:
            lines.append(f"  {card['call']}: missed {', '.join(card['missed'])}")
    lines.append("Tickets: " + ", ".join(f"{t['ticket']} -> {', '.join(t['matched']) or 'none'} ({'right' if t['right'] else 'wrong'})" for t in report["tickets"]))
    usage = report["usage"]
    for model, entry in usage["models"].items():
        lines.append(f"  {model}: {entry['requests']} requests, {entry['input']:,} input ({entry['cached']:,} cached), {entry['output']:,} output")
    lines.append(f"Judge cost for these results: about ${usage['cost']:.2f}")
    return "\n".join(lines) + "\n"
